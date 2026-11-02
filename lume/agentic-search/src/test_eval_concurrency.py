"""Offline concurrency/checkpoint tests; all writes use temporary experiment directories."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SRC=Path(__file__).resolve().parent
sys.path.insert(0,str(SRC))
spec=importlib.util.spec_from_file_location('agentic_eval_under_test',SRC/'eval.py')
e=importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


class Log:
    run_id='fixture-run'
    def __init__(self):
        self.events=[]
        self.lock=threading.Lock()
    def write(self,event,model,**details):
        with self.lock:self.events.append({'event':event,'model':model,**details})


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.db=self.home/'db';self.db.mkdir()
        self.src=self.home/'src';self.src.mkdir()
        self.patches=patch.multiple(e,HOME=self.home,DB=self.db,SRC=self.src)
        self.patches.start();self.addCleanup(self.patches.stop)
        self.args=SimpleNamespace(batch_size=5,thinking_level='HIGH',max_output_tokens=128,
            context_tokens=16000,max_steps=6,max_searches=6,max_tool_calls=8,k=5,prices={})
        self.log=Log();self.models=['fixture/model']
        self.config={'source_sha256':'corpus','questions_sha256':'questions'}
        self.records={};self.base='https://foundry.invalid'

    def questions(self,count):
        return [{'id':f'q{i:03d}','question':f'Question {i}?','as_of':'2025-06-30'} for i in range(count)]

    def run_pool(self,questions,agent):
        with patch.object(e,'run_agent',side_effect=agent),contextlib.redirect_stdout(io.StringIO()):
            e.run_questions(questions,questions,self.records,self.models,'fixture',self.config,
                self.log,{'question_ids':[q['id'] for q in questions]},self.args,self.base,'fixture-key')

    def finish(self,q,result,args,checkpoint):
        result['agent_state'].update(steps=2,search_attempts=1,elapsed_seconds=.01)
        result.update(status='ok',final_answer=f"{q['id']}:{result['model_requested']}")
        e.recompute_answer(result,args)
        checkpoint()

    def test_five_and_ten_workers_keep_every_checkpoint_valid(self):
        for concurrency in (5,10):
            with self.subTest(concurrency=concurrency):
                self.args.batch_size=concurrency;self.records={}
                questions=self.questions(50)
                barrier=threading.Barrier(concurrency)
                lock=threading.Lock();active=0;peak=0;calls=[];snapshots=[]
                original_writer=e.write_answers
                def checked_writer(records,all_questions):
                    original_writer(records,all_questions)
                    snapshot=[json.loads(s) for s in (self.home/'q-a.jsonl').read_text().splitlines()]
                    self.assertEqual(len({r['question_id'] for r in snapshot}),len(snapshot))
                    for row in snapshot:
                        e.RECORD_VALIDATOR.validate(row)
                        for model,a in row['answers'].items():
                            if a['status']=='ok':self.assertEqual(a['final_answer'],f"{row['question_id']}:{model}")
                    snapshots.append(len(snapshot))
                def agent(q,result,args,config,base,key,log,checkpoint,stop_event=None,**unused):
                    nonlocal active,peak
                    with lock:
                        active+=1;peak=max(peak,active);calls.append(q['id'])
                    if int(q['id'][1:])<concurrency:barrier.wait(timeout=5)
                    e.recompute_answer(result,args);checkpoint()
                    self.finish(q,result,args,checkpoint)
                    with lock:active-=1
                with patch.object(e,'write_answers',side_effect=checked_writer):self.run_pool(questions,agent)
                self.assertEqual(peak,concurrency)
                self.assertEqual(len(calls),50)
                self.assertGreaterEqual(len(snapshots),101)
                self.assertEqual(len(self.records),50)
                self.assertTrue(all(r['status']=='completed' for r in self.records.values()))
                self.assertTrue(all(r['provenance']['execution']['native_search_concurrency']==1 for r in self.records.values()))

    def test_next_question_starts_without_waiting_for_slowest(self):
        questions=self.questions(7);next_started=threading.Event()
        def agent(q,result,args,config,base,key,log,checkpoint,stop_event=None,**unused):
            if q['id']=='q000':self.assertTrue(next_started.wait(5),'Pool waited at a batch barrier')
            if q['id']=='q005':next_started.set()
            self.finish(q,result,args,checkpoint)
        self.run_pool(questions,agent)
        self.assertTrue(next_started.is_set())
        self.assertEqual(len(self.records),7)

    def test_models_for_one_question_are_sequential(self):
        self.models=['fixture/a','fixture/b'];questions=self.questions(10)
        active=set();lock=threading.Lock();calls=[]
        def agent(q,result,args,config,base,key,log,checkpoint,stop_event=None,**unused):
            with lock:
                self.assertNotIn(q['id'],active);active.add(q['id']);calls.append((q['id'],result['model_requested']))
            self.finish(q,result,args,checkpoint)
            with lock:active.remove(q['id'])
        self.run_pool(questions,agent)
        for q in questions:
            self.assertEqual([m for qid,m in calls if qid==q['id']],self.models)
            self.assertEqual(set(self.records[q['id']]['answers']),set(self.models))

    def test_completed_answers_resume_without_calls(self):
        questions=self.questions(5)
        self.run_pool(questions,lambda q,r,a,c,b,k,l,cp,**kw:self.finish(q,r,a,cp))
        before=copy.deepcopy(self.records)
        with patch.object(e,'run_agent') as agent,contextlib.redirect_stdout(io.StringIO()):
            e.run_questions(questions,questions,self.records,self.models,'fixture',self.config,
                self.log,{},self.args,self.base,'fixture-key')
        agent.assert_not_called();self.assertEqual(self.records,before)

    def test_pending_state_resumes_and_failed_history_is_saved(self):
        questions=self.questions(2)
        for q in questions:
            row=e.new_question(q,self.models,'fixture',self.config,self.log,{})
            a=e.initial_answer(q,self.models[0],self.args,self.base,self.log)
            row['answers'][self.models[0]]=a
            if q['id']=='q000':a['agent_state'].update(steps=2,search_attempts=1,elapsed_seconds=10)
            else:a.update(status='error',errors=[{'type':'fixture_failure'}])
            e.recompute_answer(a,self.args);e.update_record(row,self.models);self.records[q['id']]=row
        def agent(q,result,args,config,base,key,log,checkpoint,**kw):
            if q['id']=='q000':self.assertEqual(result['agent_state']['elapsed_seconds'],10)
            else:self.assertEqual(result['attempt_history'][0]['errors'][0]['type'],'fixture_failure')
            self.finish(q,result,args,checkpoint)
        self.run_pool(questions,agent)
        self.assertTrue(all(r['status']=='completed' for r in self.records.values()))

    def test_native_retrieval_stays_serial_at_ten_workers(self):
        self.args.batch_size=10;questions=self.questions(10)
        sqlite3.connect(self.db/'chunks.sqlite').close()
        lock=threading.Lock();active=0;peak=0;calls=0
        def retrieve(*args,**kwargs):
            nonlocal active,peak,calls
            with lock:active+=1;peak=max(peak,active);calls+=1
            time.sleep(.005)
            with lock:active-=1
            return [],{'retrieval_time_ms':5,'db_queries':33}
        def execute(q):
            answer=e.initial_answer(q,self.models[0],self.args,self.base,self.log)
            tc={'id':q['id'],'function':{'name':'lume_search','arguments':json.dumps({'query':q['question']})}}
            return e.tool_result(q,answer,tc,self.args,self.config,self.log)
        encoder=SimpleNamespace(get_encoding=lambda _:SimpleNamespace(encode_ordinary=lambda s:[]))
        with patch.object(e,'retrieve',side_effect=retrieve),patch.dict(sys.modules,{'tiktoken':encoder}):
            with e.ThreadPoolExecutor(max_workers=10) as pool:results=list(pool.map(execute,questions))
        self.assertEqual(calls,10);self.assertEqual(peak,1)
        self.assertTrue(all('error' not in json.loads(r['content']) for r in results))

    def test_run_agent_stop_checkpoints_without_an_api_call(self):
        q=self.questions(1)[0];answer=e.initial_answer(q,self.models[0],self.args,self.base,self.log)
        stop=threading.Event();stop.set();checkpoints=[]
        with patch.object(e,'http_call') as http:
            e.run_agent(q,answer,self.args,self.config,self.base,'fixture-key',self.log,
                lambda:checkpoints.append(copy.deepcopy(answer)),stop_event=stop)
        http.assert_not_called();self.assertEqual(answer['status'],'pending');self.assertEqual(len(checkpoints),1)

    def test_ten_searches_share_one_native_batch_and_keep_mapping(self):
        sqlite3.connect(self.db/'chunks.sqlite').close()
        questions=self.questions(10);barrier=threading.Barrier(10);calls=[]
        def native(qs,config,metadata,k,log,models):
            calls.append(copy.deepcopy(qs))
            return [([{'question_id':q['id'],'query':q['question']}],{'retrieval_batch_size':len(qs)}) for q in qs]
        def search(dispatcher,q):
            barrier.wait(5);event={}
            hits,metrics=dispatcher.search(q,'query '+q['id'],'fixture/model',event)
            return q,hits,metrics,event
        with patch.object(e,'retrieve_batch',side_effect=native):
            dispatcher=e.RetrievalBatcher(self.config,5,self.log,10,1000)
            try:
                with e.ThreadPoolExecutor(max_workers=10) as pool:
                    results=list(pool.map(lambda q:search(dispatcher,q),questions))
            finally:dispatcher.close()
        self.assertEqual(len(calls),1);self.assertEqual(len(calls[0]),10)
        self.assertEqual(len({metrics['retrieval_batch_id'] for _,_,metrics,_ in results}),1)
        for q,hits,metrics,event in results:
            self.assertEqual(hits[0],{'question_id':q['id'],'query':'query '+q['id']})
            self.assertEqual(metrics['retrieval_batch_size'],10)
            self.assertGreaterEqual(event['queue_time_ms'],0)

    def test_searches_arriving_during_a_pass_are_grouped_next(self):
        sqlite3.connect(self.db/'chunks.sqlite').close()
        questions=self.questions(10);started=threading.Event();release=threading.Event();sizes=[]
        def native(qs,*unused):
            sizes.append(len(qs))
            if len(sizes)==1:
                started.set();self.assertTrue(release.wait(5))
            return [([],{'retrieval_batch_size':len(qs)}) for _ in qs]
        with patch.object(e,'retrieve_batch',side_effect=native):
            dispatcher=e.RetrievalBatcher(self.config,5,self.log,10,0)
            try:
                with e.ThreadPoolExecutor(max_workers=10) as pool:
                    first=pool.submit(dispatcher.search,questions[0],'first','fixture/model',{})
                    self.assertTrue(started.wait(5))
                    rest=[pool.submit(dispatcher.search,q,q['id'],'fixture/model',{}) for q in questions[1:]]
                    deadline=time.monotonic()+5
                    while True:
                        with dispatcher.condition:
                            ready=len(dispatcher.pending)==9
                        if ready or time.monotonic()>deadline:break
                        time.sleep(.001)
                    self.assertTrue(ready);release.set()
                    first.result(5)
                    for future in rest:future.result(5)
            finally:release.set();dispatcher.close()
        self.assertEqual(sizes,[1,9])

    def test_failed_search_batch_wakes_every_waiter(self):
        sqlite3.connect(self.db/'chunks.sqlite').close()
        with patch.object(e,'retrieve_batch',side_effect=RuntimeError('fixture native failure')):
            dispatcher=e.RetrievalBatcher(self.config,5,self.log,10,1000)
            try:
                with e.ThreadPoolExecutor(max_workers=10) as pool:
                    futures=[pool.submit(dispatcher.search,q,q['id'],'fixture/model',{}) for q in self.questions(10)]
                    for future in futures:
                        with self.assertRaisesRegex(RuntimeError,'fixture native failure'):future.result(5)
            finally:dispatcher.close()
        with self.assertRaisesRegex(RuntimeError,'closed'):
            dispatcher.search(self.questions(1)[0],'late','fixture/model',{})

    def test_actual_agent_loop_overlaps_ten_http_calls_after_shared_retrieval(self):
        self.args.batch_size=10;self.args.search_batch_wait_ms=1000
        sqlite3.connect(self.db/'chunks.sqlite').close()
        questions=self.questions(10)
        first=threading.Barrier(10);second=threading.Barrier(10)
        lock=threading.Lock();active=0;peak=0;http_count=0;batch_sizes=[]
        def native(qs,*unused):
            batch_sizes.append(len(qs))
            return [([],{'retrieval_batch_size':len(qs),'retrieval_time_ms':1,
                'retrieval_db_queries':33,'metadata_db_queries':0,'db_queries':33,
                'retrieval_peak_rss_mb':1}) for _ in qs]
        def http(base,key,path,payload,model,log,qid,calls,kind='generation',attempts=3,stage='answer'):
            nonlocal active,peak,http_count
            followup=any(m['role']=='tool' for m in payload['messages'])
            with lock:active+=1;peak=max(peak,active);http_count+=1
            (second if followup else first).wait(5)
            message=({'role':'assistant','content':f'{qid}:{model}'} if followup else
                {'role':'assistant','content':None,'tool_calls':[{'id':qid+'-search','type':'function',
                    'function':{'name':'lume_search','arguments':json.dumps({'query':qid})}}]})
            body={'id':f'gen-{qid}-{len(calls)}','model':model,'provider':'fixture',
                'choices':[{'finish_reason':'stop' if followup else 'tool_calls','message':message}],
                'usage':{'prompt_tokens':10,'completion_tokens':5,'cost':.001}}
            calls.append({'call_id':f'{qid}-{len(calls)}','kind':'generation','stage':stage,
                'model_requested':model,'attempt':1,'request':{'body':copy.deepcopy(payload)},
                'http_status':200,'response':body,'raw_response':json.dumps(body),'response_headers':{},
                'started_at':e.utc_now(),'ended_at':e.utc_now(),'latency_ms':1,'error':None})
            with lock:active-=1
            return body
        encoder=SimpleNamespace(get_encoding=lambda _:SimpleNamespace(encode_ordinary=lambda s:[]))
        with patch.object(e,'http_call',side_effect=http),patch.object(e,'retrieve_batch',side_effect=native), \
             patch.dict(sys.modules,{'tiktoken':encoder}),contextlib.redirect_stdout(io.StringIO()):
            e.run_questions(questions,questions,self.records,self.models,'fixture',self.config,
                self.log,{},self.args,self.base,'fixture-key')
        self.assertEqual(peak,10);self.assertEqual(http_count,20);self.assertEqual(batch_sizes,[10])
        self.assertTrue(all(r['status']=='completed' for r in self.records.values()))
        for row in self.records.values():
            answer=row['answers'][self.models[0]]
            self.assertEqual(answer['metrics']['llm_api_calls'],2)
            self.assertEqual(answer['tool_executions'][0]['metrics']['retrieval_batch_size'],10)

    def test_worker_failure_cancels_queued_work(self):
        self.args.batch_size=1;questions=self.questions(20);calls=[]
        def agent(q,result,args,config,base,key,log,checkpoint,**kw):
            calls.append(q['id']);raise RuntimeError('fixture fatal writer')
        with self.assertRaisesRegex(RuntimeError,'fixture fatal writer'):self.run_pool(questions,agent)
        self.assertLess(len(calls),20)

    def main_fixture(self,argv):
        questions=self.questions(50)
        (self.src/'questions.jsonl').write_text(''.join(json.dumps(q)+'\n' for q in questions))
        binary=self.src/'binary';helper=self.src/'helper';stats=self.db/'global-stats.json'
        for p in (binary,helper,stats):p.write_text('fixture')
        config={**self.config,'binary_sha256':e.sha256(binary),'helper_sha256':e.sha256(helper),
            'global_stats_sha256':e.sha256(stats),'alpha':0,'graph':0,
            'questions_sha256':e.sha256(self.src/'questions.jsonl')}
        (self.db/'config.json').write_text(json.dumps(config))
        metadata_calls=[]
        def metadata(records,questions,models,args,*unused):
            self.assertTrue(all(r['status']=='completed' for r in records.values()))
            metadata_calls.append(args.batch_size);return 0
        def agent(q,r,a,c,b,k,l,cp,**kw):self.finish(q,r,a,cp)
        with patch.multiple(e,BIN=binary,HELPER=helper), \
             patch.object(e,'environment',return_value=(self.base,'fixture-key',{})), \
             patch.object(e,'run_agent',side_effect=agent), \
             patch.object(e,'collect_metadata',side_effect=metadata), \
             contextlib.redirect_stdout(io.StringIO()):
            try:e.main(argv)
            finally:
                if e.ACTIVE_LOG:e.ACTIVE_LOG.file.close()
        return metadata_calls

    def test_fresh_ten_resets_only_outputs_and_collects_metadata_last(self):
        (self.home/'q-a.jsonl').write_text('old output')
        (self.home/'raw-eval.log').write_text('old audit')
        marker=self.db/'keep-index';marker.write_text('unchanged')
        self.assertEqual(self.main_fixture(['--fresh','--concurrency','10']),[10])
        rows=[json.loads(s) for s in (self.home/'q-a.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),50);self.assertTrue(all(r['status']=='completed' for r in rows))
        self.assertEqual(marker.read_text(),'unchanged')
        self.assertNotIn('old audit',(self.home/'raw-eval.log').read_text())

    def test_default_is_five(self):
        self.assertEqual(self.main_fixture([]),[5])

    def test_invalid_concurrency_rejected_before_work(self):
        for value in ('0','11'):
            with self.subTest(value=value),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as raised:
                e.main(['--batch-size',value])
            self.assertEqual(raised.exception.code,2)


if __name__=='__main__':unittest.main()
