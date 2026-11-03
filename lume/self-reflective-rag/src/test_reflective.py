"""Synthetic offline tests; Foundry HTTP and production retrieval are mocked."""
from __future__ import annotations
import contextlib,copy,importlib.util,io,json,re,tempfile,threading,time,unittest
from collections import Counter
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch
import reflective as r
from bootstrap import rt,c,base
MODEL='google/gemini-3.8-flash'
OTHER='anthropic/claude-fixture'

def hit(name):
    body='Revenue was 10 million dollars.'
    return {'file':name+'.txt','line':1,'document_id':name,'source_hash':'hash-'+name,'shard':'fixture','filing_date':20250101,
        'section':'financial','section_start':0,'section_end':len(body),'start_char':0,'end_char':len(body),'title':'SEC filing '+name,
        'body':body,'retrieval_score':.8,'scores':{'bm25':1.,'cosine':.8,'hybrid':1.4}}

def review(decision,query='additional evidence'):
    checks={key:True for key in r.CHECKS}
    if decision=='retrieve':checks['evidence_sufficient']=False
    if decision=='revise':checks['entities_periods_units_correct']=False
    return {'decision':decision,'reason':'Check the financial evidence.','search_query':query if decision=='retrieve' else None,'checks':checks}

class ParsingTests(unittest.TestCase):
    def body(self,value,finish='stop'):
        return {'choices':[{'message':{'content':json.dumps(value)},'finish_reason':finish}]}
    def test_three_valid_decisions(self):
        for decision in ('accept','revise','retrieve'):self.assertEqual(r.parse_reflection(self.body(review(decision)))['decision'],decision)
    def test_inconsistent_and_unbounded_reflections_fail_closed(self):
        bad=review('accept');bad['checks']['evidence_sufficient']=False
        for value in [bad,{**review('retrieve'),'search_query':None},{**review('revise'),'search_query':'unexpected'},
                      {**review('retrieve'),'search_query':'x'*1001},{**review('accept'),'extra':'field'}]:
            with self.assertRaises(Exception):r.parse_reflection(self.body(value))
        with self.assertRaises(ValueError):r.parse_reflection(self.body(review('accept'),finish='length'))
    def test_alternating_context_keeps_sources_and_deduplicates(self):
        with patch.object(c,'context',lambda hits,budget:('fixture',hits)):
            chunks,context=r.merge_context([hit('a'),hit('b')],[hit('c'),hit('a')],{'context_k':10,'context_tokens':12000})
        self.assertEqual([chunk['document_id'] for chunk in chunks],['a','c','b'])
        self.assertEqual(len(context['chunk_ids']),3)
    def test_real_context_tokenization_uses_owned_cache(self):
        import os,tiktoken
        text,selected=c.context([hit(str(i)) for i in range(10)],50)
        self.assertTrue(selected)
        self.assertLessEqual(len(tiktoken.get_encoding('cl100k_base').encode_ordinary(text)),50)
        self.assertEqual(Path(os.environ['TIKTOKEN_CACHE_DIR']),r.SRC/'.cache/tiktoken')

class FakeDispatcher:
    queries=[]
    def __init__(self,*args,**kwargs):pass
    def submit(self,text,cutoff,technique,vector=None,include_vectors=False):
        self.queries.append({'text':text,'cutoff':cutoff,'technique':technique,'vector':copy.deepcopy(vector)})
        prefix='new-'+re.sub(r'[^a-zA-Z0-9]','',text)[-30:] if text.startswith('additional evidence') else 'original'
        hits=[hit(prefix+str(i)) for i in range(3)]
        future=Future();future.set_result((hits,{'retrieval_time_ms':1.,'requested_top_k':10,'retrieval_engine_time_ms':1.,
            'query_scoring_time_ms':.1,'native_process_lock_wait_ms':0.,'retrieval_batch_size':5,'retrieval_peak_rss_mb':20.,
            'db_queries':36,'retrieval_db_queries':33,'metadata_db_queries':3,'tool_calls':1,'retrieval_tool_calls':1,'documents_retrieved':3}))
        return future
    def close(self):pass

class DriverTests(unittest.TestCase):
    def exercise(self,workers=5,sample=None,models=(MODEL,),fault=None,decisions=None,metadata=False):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);src=root/'src';src.mkdir();db=root/'db';db.mkdir();shared=root/'shared';shared.mkdir()
            (shared/'metadata.lock').touch();support=root/'support';(support/'db').mkdir(parents=True)
            questions=[{'id':f'q{i:03d}','question':f'What was revenue item {i}?','as_of':'2025-06-30'} for i in range(50)]
            (src/'questions.jsonl').write_text(''.join(json.dumps(q)+'\n' for q in questions))
            config={'method':'self-reflective-rag','candidate_k':10,'context_k':10,'context_tokens':12000,'reflection_rounds':1,
                'reflection_model_policy':'same_as_answer_model','additional_searches_per_model':1,'reflection_reasoning':'LOW',
                'reflection_max_tokens':2048,'reflection_temperature':0,'embedding_model':'openai/text-embedding-3-small','embedding_dimensions':2}
            (db/'config.json').write_text(json.dumps(config))
            vectors={r.clean_query(q['question']):[1.,0.] for q in questions}
            (support/'db/original-queries.json').write_text(json.dumps({'vectors':vectors}))
            count=sample or 50;barrier=threading.Barrier(min(workers,count));lock=threading.Lock()
            stats={'active':0,'peak':0,'generation':0,'metadata':0,'fault_sent':False};events=[];FakeDispatcher.queries=[]
            def fake_http(url,key,path,payload,model,log,qid,calls,kind='generation',attempts=3):
                if kind=='metadata':
                    stats['metadata']+=1
                    data={'data':{'total_cost':.001,'provider_name':'fixture'}};category='metadata'
                else:
                    category=log.stage['category']
                    with lock:
                        stats['generation']+=1;ordinal=stats['generation'];stats['active']+=1;stats['peak']=max(stats['peak'],stats['active'])
                    if ordinal<=min(workers,count):barrier.wait(timeout=10)
                    log.write('api_request',model,question_id=qid,call_id=f'request-{ordinal}',request={'url':url+path,'body':payload})
                    time.sleep(.002)
                    if category=='embedding':
                        data={'model':'text-embedding-3-small','data':[{'index':0,'embedding':[1.,0.]}],'usage':{'prompt_tokens':5,'cost':.0001}}
                    else:
                        decision=decisions or ('accept','revise','retrieve')[int(qid[1:])%3]
                        if len(models)>1:decision='retrieve' if model==models[0] else 'accept'
                        if fault in ('invalid_reflection','interrupt_after_response') and category=='reflection' and not stats['fault_sent']:
                            decision='accept';stats['fault_qid']=qid
                        if stats.get('fault_qid')==qid and fault in ('invalid_reflection','interrupt_after_response'):decision='accept'
                        text=json.dumps(review(decision,'additional evidence '+qid+' '+model)) if category=='reflection' else 'Revenue was 10 million dollars [1].'
                        if fault=='invalid_reflection' and category=='reflection' and not stats['fault_sent']:
                            text='not valid JSON';stats['fault_sent']=True
                        finish='stop'
                        if fault=='truncated_revision' and category=='revision' and not stats['fault_sent']:
                            finish='length';stats['fault_sent']=True;stats['fault_qid']=qid
                        data={'id':f'fixture-{qid}-{model}-{category}-{ordinal}','model':model,'provider':'fixture',
                            'choices':[{'message':{'role':'assistant','content':text},'finish_reason':finish}],
                            'usage':{'prompt_tokens':10,'completion_tokens':6,'completion_tokens_details':{'reasoning_tokens':2},'prompt_tokens_details':{'cached_tokens':0},'cost':.001}}
                call={'call_id':f'call-{qid}-{category}-{len(calls)}','kind':kind,'stage':category,'model_requested':model,'attempt':1,
                    'request':{'url':url+path,'body':payload},'http_status':200,'response':data,'raw_response':json.dumps(data),'response_headers':{},
                    'started_at':c.utc_now(),'ended_at':c.utc_now(),'latency_ms':2.,'error':None}
                calls.append(call);events.append((qid,model,category,payload));log.write('api_response',model,question_id=qid,call=call)
                if kind!='metadata':
                    with lock:stats['active']-=1
                if fault=='interrupt_after_response' and category=='reflection' and not stats['fault_sent']:
                    stats['fault_sent']=True;raise InterruptedError('fixture process interrupted after durable response')
                return data
            with contextlib.ExitStack() as stack:
                for name,value in {'HOME':root,'DB':db,'METHOD':'self-reflective-rag','SRC':support/'src','SHARED':shared}.items():stack.enter_context(patch.object(rt,name,value))
                stack.enter_context(patch.object(c,'HOME',root));stack.enter_context(patch.object(c,'METHOD','self-reflective-rag'))
                stack.enter_context(patch.object(r,'validate',lambda *args:None));stack.enter_context(patch.object(r,'code_identity',lambda:'fixture'))
                stack.enter_context(patch.object(c,'environment',lambda **kwargs:('https://fixture.invalid','fixture-key',{})))
                stack.enter_context(patch.object(c,'http_call',fake_http));stack.enter_context(patch.object(r,'RetrievalBatcher',FakeDispatcher))
                stack.enter_context(patch.object(c,'context',lambda hits,budget:('\n'.join(f'[{i}] '+h['body'] for i,h in enumerate(hits,1)),hits)))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                args=['--concurrency',str(workers),'--defer-metadata']
                for model in models:args+=['--model',model]
                if sample:args+=['--sample-size',str(sample),'--seed','77']
                if fault:
                    with self.assertRaises(SystemExit):r.main(args)
                    before=stats['generation'];native_before=len(FakeDispatcher.queries)
                    r.main(args)
                    self.assertEqual(stats['generation']-before,0 if fault=='interrupt_after_response' else 1)
                    self.assertEqual(len(FakeDispatcher.queries),native_before)
                else:r.main(args)
                rows=[json.loads(line) for line in (root/'q-a.jsonl').read_text().splitlines()]
                self.assertEqual(len(rows),count);self.assertEqual(stats['peak'],min(workers,count))
                decisions_seen=set()
                for row in rows:
                    c.RECORD_VALIDATOR.validate(row);self.assertEqual(row['status'],'completed')
                    for model,answer in row['answers'].items():
                        decision=answer['reflection']['decision'];decisions_seen.add(decision)
                        tally=Counter(call['stage'] for call in answer['api_calls'])
                        self.assertEqual(tally['draft'],1);self.assertEqual(tally['reflection'],2 if fault=='invalid_reflection' and row['question_id']==stats.get('fault_qid') else 1)
                        self.assertLessEqual(answer['metrics']['additional_retrievals'],1)
                        normal_chats=2 if decision=='accept' else 3
                        retries=1 if fault in ('invalid_reflection','truncated_revision') and row['question_id']==stats.get('fault_qid') else 0
                        expected_chats=normal_chats+retries
                        self.assertEqual(answer['metrics']['output_tokens'],6*expected_chats)
                        self.assertEqual(answer['metrics']['reasoning_tokens'],2*expected_chats)
                        self.assertEqual(answer['metrics']['llm_api_calls'],expected_chats)
                        self.assertEqual(answer['metrics']['query_embedding_api_calls'],int(decision=='retrieve'))
                        self.assertAlmostEqual(answer['metrics']['api_cost_usd'],expected_chats*.001+(.0001 if decision=='retrieve' else 0))
                        self.assertEqual(answer['metrics']['total_tokens'],answer['metrics']['input_tokens']+answer['metrics']['output_tokens'])
                        self.assertEqual(answer['citations'][0]['chunk_id'],answer['context']['chunk_ids'][0])
                        self.assertEqual([chunk['rank'] for chunk in answer['retrieval']['chunks']],list(range(1,len(answer['retrieval']['chunks'])+1)))
                        ids={query['query_id'] for query in answer['retrieval']['queries']}
                        self.assertTrue(all(occ['query_id'] in ids for chunk in answer['retrieval']['chunks'] for occ in chunk.get('occurrences',[])))
                    if len(models)>1:
                        self.assertNotEqual(row['answers'][models[0]]['context']['chunk_ids'],row['answers'][models[1]]['context']['chunk_ids'])
                        self.assertEqual(row['context']['by_model'][models[0]],row['answers'][models[0]]['context'])
                        self.assertEqual(row['metrics']['tool_calls'],2)
                if count==50 and not fault:self.assertEqual(decisions_seen,{'accept','revise','retrieve'})
                self.assertTrue(all(q['cutoff']=='2025-06-30' and q['technique']=='hybrid' for q in FakeDispatcher.queries))
                for _,_,category,payload in events:
                    if payload is not None:
                        serialized=json.dumps(payload)
                        self.assertNotIn('gold_answer',serialized);self.assertNotIn('expected_answer',serialized)
                # The shared judge must use the FINAL model-specific context and
                # remove all raw execution state from presentation exports.
                spec=importlib.util.spec_from_file_location('reflective_judge_compat',rt.REPO/'judge/eval.py')
                judge=importlib.util.module_from_spec(spec);spec.loader.exec_module(judge)
                source=copy.deepcopy(rows[0]);gold={'id':source['question_id'],'question':source['question'],'as_of':source['as_of'],'category':'fixture',
                    'expected_answer':'10 million','evidence':[{'document_id':'original0','passage':'Revenue was 10 million dollars.'}]}
                judge_args=judge.parser().parse_args(['fixture','--export-only'])
                tasks=judge.prepare({source['question_id']:source},{source['question_id']:gold},{},judge_args,'https://fixture.invalid')
                for task in tasks.values():
                    supplied=json.loads(task['body']['messages'][1]['content'])['context_sent_to_answer_model']
                    self.assertEqual(supplied,source['answers'][task['answer_model']]['context'])
                compact=judge.presentation_record(source)
                c.Draft202012Validator(json.loads((rt.REPO/'judge/evaluation.schema.json').read_text())).validate(compact)
                for key in ('api_calls','raw_response','reflective_models','execution_checkpoint'):
                    self.assertNotIn('"'+key+'"',json.dumps(compact))
                before=stats['generation'];native_before=len(FakeDispatcher.queries)
                r.main(args);self.assertEqual(stats['generation'],before);self.assertEqual(len(FakeDispatcher.queries),native_before)
                if metadata:
                    r.main(args+['--refresh-metadata','--metadata-delay','0'])
                    self.assertEqual(stats['metadata'],sum(a['metrics']['llm_api_calls'] for row in rows for a in row['answers'].values()))
                    enriched=[json.loads(line) for line in (root/'q-a.jsonl').read_text().splitlines()]
                    self.assertTrue(all(row['metrics']['generation_metadata_complete'] for row in enriched))
                    collected=stats['metadata'];r.main(args+['--refresh-metadata','--metadata-delay','0'])
                    self.assertEqual(stats['metadata'],collected);self.assertEqual(stats['generation'],before)
                keep=db/'keep.txt';keep.write_text('unchanged')
                # --fresh resets only owned output records; a sampled fresh run
                # cannot delete indexes or unrelated state.
                fresh=args+['--fresh']
                if sample is None:fresh+=['--sample-size','5','--seed','77']
                r.main(fresh);self.assertEqual(keep.read_text(),'unchanged')
                if sample is None:
                    self.assertEqual(len((root/'q-a.jsonl').read_text().splitlines()),5)
                    r.main(args);self.assertEqual(len((root/'q-a.jsonl').read_text().splitlines()),50)
    def test_fifty_questions_five_workers_all_decisions_resume_and_fresh(self):self.exercise()
    def test_ten_workers(self):self.exercise(workers=10,sample=10)
    def test_independent_models_contexts_and_record_costs(self):self.exercise(workers=5,sample=5,models=(MODEL,OTHER))
    def test_invalid_reflection_retries_only_critic(self):self.exercise(workers=1,sample=1,fault='invalid_reflection')
    def test_interruption_after_response_replays_without_new_call(self):self.exercise(workers=1,sample=1,fault='interrupt_after_response')
    def test_truncated_revision_retries_only_revision(self):self.exercise(workers=1,sample=1,fault='truncated_revision',decisions='revise')
    def test_metadata_covers_draft_critic_revision_and_skips_embeddings(self):self.exercise(workers=1,sample=1,decisions='retrieve',metadata=True)

if __name__=='__main__':unittest.main()
