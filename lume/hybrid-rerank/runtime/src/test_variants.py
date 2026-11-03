"""Offline fixtures only: no Foundry requests and no production retrieval runs."""
from __future__ import annotations
import contextlib, copy, importlib.util, io, json, math, os, sqlite3, struct, subprocess, tempfile, threading, time, unittest
from concurrent.futures import Future,ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import algorithms as a
import client
import common as c
import runtime as rt
import runner as r
from retrieval import RetrievalBatcher
from reranker import CrossEncoder,window_starts
from setup_variants import original_queries

MODEL='google/gemini-3.8-flash'
def hit(name='a',vector=None):
    row={'file':name+'.txt','line':1,'document_id':name,'source_hash':'hash-'+name,'shard':'fixture','filing_date':20250101,
        'section':'financial','section_start':0,'section_end':30,'start_char':0,'end_char':30,'title':'SEC filing '+name,
        'body':'Revenue was 10 million dollars.','retrieval_score':.8,'scores':{'cosine':.8,'hybrid':1.2}}
    if vector is not None:row['_vector']=vector
    return row

class Algorithms(unittest.TestCase):
    def test_rrf_deduplicates_and_retains_source_ranks(self):
        rows=a.rrf([[hit('a'),hit('b')],[hit('b'),hit('c')]],['bm25','dense'])
        self.assertEqual(rows[0]['document_id'],'b');self.assertEqual(len(rows),3)
        self.assertAlmostEqual(rows[0]['scores']['rrf'],1/62+1/61)
        self.assertEqual(rows[0]['ranks'],{'bm25':2,'dense':1});self.assertEqual(len(rows[0]['occurrences']),2)
    def test_decomposition_round_robin_keeps_subquestion_coverage(self):
        rows=a.balanced_merge([[hit('a'),hit('b')],[hit('c'),hit('a')],[hit('a'),hit('d')]],['sub1','sub2','original'])
        self.assertEqual([h['document_id'] for h in rows],['a','c','b','d'])
    def test_mmr_diversity_uses_existing_vectors(self):
        rows=a.mmr([hit('a',[1.,0]),hit('b',[1.,0]),hit('c',[0,1.])],2,.3)
        self.assertEqual([h['document_id'] for h in rows[:2]],['a','c'])
        with self.assertRaises(ValueError):a.mmr([hit()],1)
    def test_complete_window_coverage(self):
        for size in (0,10,400,800,2500):
            starts=window_starts(size,380,64);covered=set()
            for start in starts:covered.update(range(start,min(size,start+380)))
            self.assertEqual(covered,set(range(size)))

class DummyLog:
    run_id='fixture'
    def write(self,*args,**kwargs):pass

class ClientTests(unittest.TestCase):
    def test_response_replay_does_not_repeat_paid_stage_and_rejects_request_change(self):
        stage={};saved=[];calls=[]
        def http(base,key,path,payload,model,log,qid,items,**kw):
            calls.append(payload);items.append({'kind':'generation','error':None,'response':{'id':'fixture'}});log.write('api_response',model);return items[-1]['response']
        cli=client.Client('https://fixture.invalid','key',DummyLog(),lambda:saved.append(copy.deepcopy(stage)))
        with patch.object(c,'http_call',http):
            cli.call(stage,{'input':'q'},MODEL,'q','query_generation')
            cli.call(stage,{'input':'q'},MODEL,'q','query_generation')
            self.assertEqual(len(calls),1)
            with self.assertRaises(ValueError):cli.call(stage,{'input':'different'},MODEL,'q','query_generation')
            stage['needs_retry']=True
            cli.call(stage,{'input':'q'},MODEL,'q','query_generation');self.assertEqual(len(calls),2)
        self.assertTrue(saved)
    def test_cost_and_tokens_include_query_stages_without_double_reasoning(self):
        def call(usage):return {'kind':'generation','latency_ms':10,'response':{'usage':usage}}
        stages=[{'category':'query_generation','api_calls':[call({'prompt_tokens':20,'completion_tokens':10,'completion_tokens_details':{'reasoning_tokens':4},'cost':.01})]},
            {'category':'embedding','api_calls':[call({'prompt_tokens':5,'total_tokens':5,'cost':.001})]}]
        stats=client.metrics(stages)
        self.assertEqual(stats['input_tokens'],25);self.assertEqual(stats['output_tokens'],10);self.assertEqual(stats['total_tokens'],35)
        self.assertEqual(stats['reasoning_tokens'],4);self.assertAlmostEqual(stats['api_cost_usd'],.011)
        stages[0]['ambiguous_attempts']=[{}];self.assertIsNone(client.metrics(stages)['api_cost_usd'])
    def test_embedding_dimension_and_model_fail_closed(self):
        self.assertEqual(client.embedding({'model':'text-embedding-3-small','data':[{'embedding':[1.,0.]}]},2),[1.,0.])
        for d in [{'model':'wrong','data':[]},{'model':'text-embedding-3-small','data':[{'embedding':[0.,0.]}]}]:
            with self.assertRaises(ValueError):client.embedding(d,2)
    def test_missing_token_details_remain_unknown(self):
        stage={'category':'answer','api_calls':[{'kind':'generation','latency_ms':1,'response':{'usage':{'prompt_tokens':3,'completion_tokens':2,'cost':.01}}}]}
        counts=client.metrics([stage])
        self.assertEqual(counts['total_tokens'],5)
        self.assertIsNone(counts['reasoning_tokens']);self.assertIsNone(counts['cached_input_tokens']);self.assertIsNone(counts['visible_output_tokens'])
    def test_route_rejects_direct_hosts_and_headers_sanitized(self):
        with patch.dict(os.environ,{'LLMFOUNDRY_BASE_URL':'https://openrouter.ai/api','LLMFOUNDRY_API_KEY':'test'}):
            with self.assertRaises(ValueError):c.environment()
        self.assertNotIn('authorization',c.safe_headers({'Authorization':'secret','x-request-id':'id'}))

class DispatcherTests(unittest.TestCase):
    def test_ten_queries_coalesce_and_map_exactly(self):
        batches=[]
        def execute(self,queries):
            batches.append(len(queries));return [([{'text':q['text']}],{}) for q in queries]
        with patch.object(RetrievalBatcher,'execute',execute):
            dispatcher=RetrievalBatcher({},DummyLog(),max_queries=10,wait_ms=100)
            try:
                futures=[dispatcher.submit(str(i),'2025-06-30','hybrid') for i in range(10)]
                self.assertEqual([f.result()[0][0]['text'] for f in futures],[str(i) for i in range(10)])
                self.assertEqual(batches,[10])
            finally:dispatcher.close()

class CheckpointTests(unittest.TestCase):
    def test_reranker_failure_resumes_saved_candidates_without_native_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);db=root/'db';db.mkdir()
            q={'id':'qfixture','question':'What is revenue?','as_of':'2025-06-30'}
            config={'candidate_k':50,'context_k':10,'context_tokens':12000}
            row=c.new_record(q,[],[],'',{},[MODEL],'fixture-signature',{},DummyLog(),{})
            class FailingReranker:
                def score(self,*args):raise RuntimeError('fixture scoring failure')
            with patch.object(rt,'HOME',root),patch.object(rt,'DB',db),patch.object(rt,'METHOD','hybrid-rerank'),patch.object(c,'context',lambda hits,budget:('fixture',hits)):
                before=len(FakeDispatcher.batches)
                with self.assertRaises(RuntimeError):r.retrieve_question(row,config,FakeDispatcher(),None,lambda:None,{'What is revenue':[1.,0.]},FailingReranker())
                self.assertTrue(row['retrieval']['candidate_checkpoint'])
                self.assertEqual(len(row['retrieval']['chunks']),2)
                calls=len(FakeDispatcher.batches)
                r.retrieve_question(row,config,FakeDispatcher(),None,lambda:None,{'What is revenue':[1.,0.]},FakeReranker())
                self.assertEqual(calls,before+1);self.assertEqual(len(FakeDispatcher.batches),calls)
                self.assertTrue(row['retrieval']['ready'])

    def test_metadata_visits_query_and_answer_ids_once_and_excludes_embedding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'metadata.lock').touch();q={'id':'qfixture','question':'Revenue?','as_of':'2025-06-30'}
            row=c.new_record(q,[],[],'',{'retrieval_time_ms':1,'tool_calls':0,'db_queries':0,'documents_retrieved':0},[MODEL],'fixture',{},DummyLog(),{})
            state=r.execution_state(row)
            def generation(gid):return {'kind':'generation','stage':'answer','model_requested':MODEL,'error':None,'response':{'id':gid,'usage':{'prompt_tokens':1,'completion_tokens':2}},'latency_ms':1}
            state['preparation']={'query':{'category':'query_generation','model_requested':MODEL,'api_calls':[generation('query-id')]},'embed':{'category':'embedding','api_calls':[generation('embedding-id')]}}
            state['answer_stages']={MODEL:{'category':'answer','model_requested':MODEL,'api_calls':[generation('answer-id')]}}
            row['answers']={MODEL:{'status':'ok','final_answer':'10','generation_id':'answer-id','api_calls':[],'metrics':{}}}
            class MemoryStore:
                def get(self,qid):return copy.deepcopy(row)
                def put(self,snapshot):row.clear();row.update(copy.deepcopy(snapshot))
            ids=[]
            def http(base,key,path,payload,model,log,qid,calls,**kwargs):
                ids.append(path);calls.append({'kind':'metadata','http_status':200,'latency_ms':1});return {'data':{'total_cost':.001}}
            with patch.object(rt,'SHARED',root),patch.object(c,'http_call',http):
                args=type('Args',(),{'metadata_delay':0})()
                r.collect_metadata(MemoryStore(),[q],args,'https://fixture.invalid','key',DummyLog())
                r.collect_metadata(MemoryStore(),[q],args,'https://fixture.invalid','key',DummyLog())
            self.assertEqual(len(ids),2);self.assertIn('query-id',ids[0]);self.assertIn('answer-id',ids[1])
    def test_batch_failure_wakes_every_waiter(self):
        with patch.object(RetrievalBatcher,'execute',side_effect=RuntimeError('fixture batch failure')):
            dispatcher=RetrievalBatcher({},DummyLog(),max_queries=10,wait_ms=100)
            try:
                futures=[dispatcher.submit(str(i),'2025-06-30','hybrid') for i in range(10)]
                for future in futures:
                    with self.assertRaises(RuntimeError):future.result(timeout=2)
            finally:dispatcher.close()

class FakeDispatcher:
    batches=[]
    def __init__(self,*args,**kwargs):pass
    def submit(self,text,cutoff,technique,vector=None,include_vectors=False):
        future=Future();self.batches.append((text,cutoff,technique))
        hits=[hit('a',[1.,0.] if include_vectors else None),hit('b',[0.,1.] if include_vectors else None)]
        future.set_result((hits,{'db_queries':35,'retrieval_db_queries':33,'metadata_db_queries':2,'retrieval_peak_rss_mb':10,
            'retrieval_engine_time_ms':1,'retrieval_batch_size':5,'query_scoring_time_ms':.1,'native_process_lock_wait_ms':0}))
        return future
    def close(self):pass

class FakeReranker:
    def __init__(self,*args,**kwargs):pass
    def score(self,query,hits):
        for h in hits:h['scores']['cross_encoder']=1.
        return hits,{'reranker_api_calls':0,'reranking_time_ms':1}

class DriverTests(unittest.TestCase):
    def fixture(self,root,method,workers=5):
        src=root/'src';src.mkdir(exist_ok=True);db=root/'db';db.mkdir(exist_ok=True)
        support=root/'support';support.mkdir(exist_ok=True)
        questions=[{'id':f'q{i:03d}','question':f'What is revenue {i}?','as_of':'2025-06-30'} for i in range(50)]
        (src/'questions.jsonl').write_text(''.join(json.dumps(q)+'\n' for q in questions))
        config={'method':method,'candidate_k':50,'context_k':10,'context_tokens':12000,'rrf_constant':60,'mmr_weight':.7,
            'max_subquestions':3,'query_model':MODEL,'query_reasoning':'HIGH','query_max_tokens':4096,
            'embedding_model':'openai/text-embedding-3-small','embedding_dimensions':2,'reranker_model_dir':'db/reranker'}
        (db/'config.json').write_text(json.dumps(config))
        vectors={' '.join(c.re.findall(r'[^\W_]+',q['question'])):[1.,0.] for q in questions}
        (support/'db').mkdir()
        (support/'db/original-queries.json').write_text(json.dumps({'vectors':vectors}))
        return questions,db,support
    def run_fixture(self,method,workers,truncate=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);qs,db,support=self.fixture(root,method,workers)
            lock=threading.Lock();barrier=threading.Barrier(workers);counts={'calls':0,'active':0,'peak':0}
            def http(base,key,path,payload,model,log,qid,calls,kind='generation',attempts=3):
                with lock:
                    counts['calls']+=1;counts['active']+=1;counts['peak']=max(counts['peak'],counts['active']);ordinal=counts['calls']
                if ordinal<=workers:barrier.wait(timeout=10)
                log.write('api_request',model,question_id=qid,call_id='request-'+str(counts['calls']),request={'url':base+path,'body':payload})
                time.sleep(.005)
                if path.endswith('/embeddings'):
                    data={'model':'text-embedding-3-small','data':[{'index':0,'embedding':[1.,0.]}],'usage':{'prompt_tokens':5,'cost':.0001}}
                else:
                    instruction=payload['messages'][0]['content']
                    text=json.dumps({'subquestions':['What is operating revenue?','What is net revenue?']}) if 'subquestions' in instruction else ('A hypothetical filing passage' if 'hypothetical' in instruction else 'Revenue was 10 million [1].')
                    finish='length' if truncate and qid=='q000' and counts.get('truncation_sent') is None else 'stop'
                    if finish=='length':counts['truncation_sent']=True
                    data={'id':f'id-{qid}-{len(calls)}','model':model,'provider':'fixture','choices':[{'message':{'role':'assistant','content':text},'finish_reason':finish}],
                          'usage':{'prompt_tokens':20,'completion_tokens':10,'completion_tokens_details':{'reasoning_tokens':4},'cost':.001}}
                call={'call_id':f'call-{qid}-{len(calls)}','kind':kind,'stage':'answer','model_requested':model,'attempt':1,
                    'request':{'url':base+path,'body':payload},'http_status':200,'response':data,'raw_response':json.dumps(data),'response_headers':{},
                    'started_at':c.utc_now(),'ended_at':c.utc_now(),'latency_ms':5.,'error':None}
                calls.append(call);log.write('api_response',model,question_id=qid,call=call)
                with lock:counts['active']-=1
                return data
            with contextlib.ExitStack() as stack:
                for name,value in {'HOME':root,'DB':db,'METHOD':method,'SRC':support/'src'}.items():stack.enter_context(patch.object(rt,name,value))
                for name,value in {'HOME':root,'METHOD':method}.items():stack.enter_context(patch.object(c,name,value))
                stack.enter_context(patch.object(r,'validate_setup',lambda *a,**kw:None))
                stack.enter_context(patch.object(r,'code_identity',lambda:'fixture-code'))
                stack.enter_context(patch.object(c,'environment',lambda **kw:('https://fixture.invalid','fixture-key',{})))
                stack.enter_context(patch.object(c,'http_call',http))
                stack.enter_context(patch.object(c,'context',lambda hits,budget:('[1] Revenue was 10 million.',hits)))
                stack.enter_context(patch.object(r,'RetrievalBatcher',FakeDispatcher))
                stack.enter_context(patch.object(r,'CrossEncoder',FakeReranker))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                args=['--batch-size',str(workers),'--defer-metadata']
                if truncate:
                    with self.assertRaises(SystemExit):r.main(args)
                    calls_before=counts['calls'];retrievals_before=len(FakeDispatcher.batches)
                    r.main(args)
                    self.assertEqual(counts['calls'],calls_before+1);self.assertEqual(len(FakeDispatcher.batches),retrievals_before)
                else:r.main(args)
                rows=[json.loads(line) for line in (root/'q-a.jsonl').read_text().splitlines()]
                self.assertEqual(len(rows),50);self.assertEqual(counts['peak'],workers)
                if truncate:
                    prior=rows[0]['answers'][MODEL]['attempt_history'][0]
                    self.assertEqual(prior['status'],'truncated');self.assertEqual(len(prior['api_calls']),1)
                for row in rows:
                    c.RECORD_VALIDATOR.validate(row);self.assertEqual(row['status'],'completed')
                    answer=row['answers'][MODEL]
                    expected_output=20 if method in ('hyde','query-decomposition') else 10
                    if truncate and row['question_id']=='q000':expected_output+=10
                    self.assertEqual(answer['metrics']['output_tokens'],expected_output)
                    self.assertEqual(answer['metrics']['reasoning_tokens'],expected_output*4//10)
                    self.assertEqual(answer['citations'][0]['chunk_id'],row['context']['chunk_ids'][0])
                    self.assertFalse(any('_vector' in chunk for chunk in row['retrieval']['chunks']))
                before=counts['calls'];retrievals=len(FakeDispatcher.batches)
                spec=importlib.util.spec_from_file_location('variant_judge_compat',rt.REPO/'judge/eval.py')
                judge=importlib.util.module_from_spec(spec);spec.loader.exec_module(judge)
                source=copy.deepcopy(rows[0]);gold={'id':source['question_id'],'question':source['question'],'as_of':source['as_of'],
                    'category':'fixture','expected_answer':'10 million','evidence':[{'document_id':'a','passage':'Revenue was 10 million.'}]}
                judge_args=judge.parser().parse_args(['fixture','--export-only'])
                judge.prepare({source['question_id']:source},{source['question_id']:gold},{},judge_args,'https://fixture.invalid')
                compact=judge.presentation_record(source)
                c.Draft202012Validator(json.loads((rt.REPO/'judge/evaluation.schema.json').read_text())).validate(compact)
                serialized=json.dumps(compact)
                for raw_key in ('api_calls','raw_response','answer_stages','execution_checkpoint'):
                    self.assertNotIn('"'+raw_key+'"',serialized)
                r.main(args);self.assertEqual(counts['calls'],before);self.assertEqual(len(FakeDispatcher.batches),retrievals)
                # A sampled fresh run replaces only the two owned output files.
                keep=db/'keep.txt';keep.write_text('untouched')
                r.main(args+['--fresh','--sample-size','5','--seed','77'])
                self.assertEqual(len((root/'q-a.jsonl').read_text().splitlines()),5);self.assertEqual(keep.read_text(),'untouched')
                # Full resume retains the five completed answers and adds the other 45.
                r.main(args);self.assertEqual(len((root/'q-a.jsonl').read_text().splitlines()),50)
    def test_all_five_methods_five_workers(self):
        for method in rt.METHODS:
            with self.subTest(method=method):self.run_fixture(method,5)
    def test_ten_workers_and_resume(self):self.run_fixture('hyde',10)
    def test_truncated_answer_retries_only_its_generation_stage(self):self.run_fixture('rrf',5,truncate=True)

class LocalModelTests(unittest.TestCase):
    def test_real_onnx_on_synthetic_text_and_full_window_mapping(self):
        model=CrossEncoder(rt.SRC.parent/'db/reranker',batch_size=2)
        rows=[hit('mars'),hit('venus')]
        rows[0]['body']='Mars is known as the red planet.'
        rows[1]['body']='Venus has thick clouds and a hot surface.'
        ranked,stats=model.score('Which planet is called the red planet?',rows)
        self.assertEqual(ranked[0]['document_id'],'mars');self.assertEqual(stats['reranker_pairs'],2)
        long=hit('long');long['body']='Annual financial report. '*800+' Revenue was 10 million.'
        windows=model.windows('What was revenue?',long['body']);self.assertGreater(len(windows),1)
        self.assertTrue(all(len(q)+len(p)+3<=512 for q,p in windows))

class NativeTests(unittest.TestCase):
    def test_actual_native_on_three_document_fixture_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);corpus=root/'corpus';corpus.mkdir();index=root/'index';index.mkdir()
            for name,body in [('a','profit profit profit'),('b','quarterly earnings sales'),('c','profit forecast')]:
                (corpus/(name+'.txt')).write_text(body+'\n')
            (corpus/'lume.schema.json').write_text(json.dumps({'filing_date':'integer'}))
            (corpus/'lume.meta.jsonl').write_text(''.join(json.dumps({'path':n+'.txt','fields':{'filing_date':20270101 if n=='c' else 20250101}})+'\n' for n in ('a','b','c')))
            env={**os.environ,'XDG_CACHE_HOME':str(root),'TMPDIR':str(root),'LUME_STEM':'1','LUME_TITLE_FALLBACK':'0'}
            binary=rt.REPO/'lume/semantic-search/src/bin/lume'
            subprocess.run([str(binary),'index',str(corpus),'--db',str(index)],env=env,check=True,capture_output=True)
            desc=root/'desc.jsonl';subprocess.run([str(rt.HELPER),'describe',str(index),str(desc)],check=True,capture_output=True)
            rows=[json.loads(line) for line in desc.read_text().splitlines()]
            ids=sorted(r['id'] for r in rows);by_id={r['id']:r for r in rows};dims=1536
            values={key:([.2,math.sqrt(.96)] if Path(by_id[key]['file']).name=='a.txt' else [1.,0.])+[0.]*(dims-2) for key in ids}
            out=bytearray(struct.pack('<8sHHIQIIII',b'LUMEVEC1',1,0,0x01020304,0,dims,len(ids),1,0))
            for s in ['text-embedding-3-small','document','query']:
                b=s.encode();out+=struct.pack('<H',len(b))+b
            for key in ids:
                b=key.encode();out+=struct.pack('<I',len(b))+b
            for key in ids:out+=struct.pack('<'+'f'*dims,*values[key])
            out+=struct.pack('<I',6)+b'profit';out+=struct.pack('<'+'f'*dims,1.,*([0.]*(dims-1)));struct.pack_into('<Q',out,16,len(out))
            (index/'local-vectors.bin').write_bytes(out)
            self.assertEqual(len(original_queries(index/'local-vectors.bin')['profit']),dims)
            stats=root/'stats.json';old=rt.REPO/'lume/bm25/src/native/target/release/lume-bm25-bounded'
            subprocess.run([str(old),'stats',str(index),str(stats)],check=True,capture_output=True)
            st=json.loads(stats.read_text());terms={}
            for name,col in [('title_dfs',0),('body_dfs',1)]:
                for word,df in st[name].items():terms.setdefault(word,[0,0])[col]=df
            (root/'global.json').write_text(json.dumps({'num_docs':3,'avg_title_len':st['title_length_sum']/3,'avg_body_len':st['body_length_sum']/3,'terms':terms}))
            (root/'filing-dates.json').write_text(json.dumps({'a.txt':20250101,'b.txt':20250101,'c.txt':20270101}))
            (root/'config.json').write_text(json.dumps({'global_stats':'global.json','shards':[{'index':'index'}],'technique':'per-query'}))
            qfile=root/'queries.json';query={'text':'profit','cutoff':20251231,'technique':'semantic-search','include_vectors':True}
            def search(queries):
                qfile.write_text(json.dumps(queries));return subprocess.run(rt.limited_command([rt.HELPER,'search-batch',root/'config.json',qfile,'10']),capture_output=True,text=True,env=env)
            before=(index/'local-vectors.bin').read_bytes()
            result=search([query,{**query,'technique':'hybrid'},{**query,'technique':'bm25'},{**query,'text':'not cached','vector':[0.,1.]+[0.]*(dims-2)}])
            self.assertEqual(result.returncode,0,result.stderr)
            entries=json.loads(result.stdout)['results']
            self.assertEqual([Path(h['file']).name for h in entries[0]['hits']],['b.txt','a.txt'])
            for entry in entries:
                self.assertNotIn('c.txt',[Path(h['file']).name for h in entry['hits']])
            for h in entries[1]['hits']:
                s=h['scores'];self.assertAlmostEqual(h['score'],s['bm25']*(1+.5*s['cosine']) if s['bm25']>0 else s['cosine'])
            for h in entries[2]['hits']:self.assertAlmostEqual(h['score'],h['scores']['bm25'])
            self.assertEqual(search([{**query,'text':'missing'}]).returncode,1)
            self.assertEqual(before,(index/'local-vectors.bin').read_bytes())
            self.assertLess(entries[0]['peak_rss_kib']/1024,2048)

if __name__=='__main__':unittest.main()
