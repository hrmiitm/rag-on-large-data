"""Offline real agent-loop, concurrent checkpoint/resume and budget tests."""
import copy
from concurrent.futures import ThreadPoolExecutor
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
spec=importlib.util.spec_from_file_location('es_eval',Path(__file__).with_name('eval.py'))
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)
import budget
from search import filters,TOOLS

class Log:
    run_id='fixture-run'
    key='fixture-key'
    def write(self,*args,**kwargs):pass

def passage(q,line=1):
    body=f"Evidence for {q['id']} passage {line}."
    return dict(file=q['id']+'.txt',line=line,document_id=q['id'],source_hash='source',shard='source.parquet',
                filing_date=20250101,section='financials',section_start=0,section_end=10000,
                start_char=line*100,end_char=line*100+len(body),title=q['id'],body=body,
                elasticsearch_id=f"{q['id']}:{line}",retrieval_score=1.,scores={'rrf':1.},retrieval_query=q['question'])

class Dispatcher:
    def __init__(self,*args):pass
    def close(self):pass
    def search(self,q,query,model,event,values):return [passage(q)],self.metrics()
    def read(self,q,anchors,model,event):return [passage(q,26)],self.metrics()
    def metrics(self):return {'retrieval_time_ms':1,'db_queries':1,'retrieval_db_queries':1,'metadata_db_queries':0,'retrieval_peak_rss_mb':None}

class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);(self.home/'db').mkdir()
        self.patch=patch.multiple(e,HOME=self.home,DB=self.home/'db',RetrievalBatcher=Dispatcher)
        self.patch.start();self.addCleanup(self.patch.stop);e.SERIALIZED.clear()
        self.args=SimpleNamespace(batch_size=5,thinking_level='HIGH',max_output_tokens=128,context_tokens=16000,
                                  max_steps=6,max_searches=6,max_tool_calls=8,k=5,prices={},search_batch_wait_ms=0)
        self.config={'source_sha256':'corpus','questions_sha256':'questions'}

    def test_real_loop_five_and_ten_workers_checkpoint_and_resume(self):
        for workers in (5,10):
            with self.subTest(workers=workers):
                self.args.batch_size=workers;e.SERIALIZED.clear();records={};seen={};lock=threading.Lock()
                barrier=threading.Barrier(workers);active=0;peak=0
                questions=[{'id':f'q{i:03d}','question':f'Question {i}','as_of':'2025-06-30'} for i in range(50)]
                def http(base,key,path,payload,model,log,qid,calls,**kwargs):
                    nonlocal active,peak
                    with lock:
                        turn=seen.get(qid,0);seen[qid]=turn+1;active+=1;peak=max(peak,active)
                    if turn==0 and int(qid[1:])<workers:barrier.wait(timeout=10)
                    if turn>0:self.assertTrue(any(m.get('reasoning_details')==[{'opaque':'signature'}] for m in payload['messages']))
                    if turn==0:message={'tool_calls':[{'id':qid+'search','type':'function','function':{'name':'search_filings','arguments':json.dumps({'query':qid,'mode':'hybrid'})}}]}
                    elif turn==1:message={'tool_calls':[{'id':qid+'read','type':'function','function':{'name':'read_passages','arguments':json.dumps({'passage_ids':[qid+':1']})}}]}
                    else:message={'content':f'Supported answer for {qid} [1] [2].'}
                    message['reasoning_details']=[{'opaque':'signature'}]
                    data={'id':qid+str(turn),'model':model,'choices':[{'message':message,'finish_reason':'stop'}],
                          'usage':{'prompt_tokens':10,'completion_tokens':2,'completion_tokens_details':{'reasoning_tokens':1},'cost':.001}}
                    calls.append({'call_id':qid+str(turn),'kind':'generation','stage':'fixture','model_requested':model,
                                  'attempt':1,'request':{'body':copy.deepcopy(payload)},'response':data,'raw_response':json.dumps(data),
                                  'http_status':200,'response_headers':{},'started_at':e.utc_now(),'ended_at':e.utc_now(),'latency_ms':1,'error':None})
                    with lock:active-=1
                    return data
                with patch.object(e,'http_call',side_effect=http),contextlib.redirect_stdout(io.StringIO()):
                    e.run_questions(questions,questions,records,['fixture/model'],'fixture',self.config,Log(),{},self.args,'https://foundry.invalid','fixture-key')
                self.assertEqual(peak,workers)
                self.assertEqual(len(records),50)
                for q in questions:
                    r=records[q['id']];e.RECORD_VALIDATOR.validate(r);a=r['answers']['fixture/model']
                    self.assertEqual(a['status'],'ok');self.assertEqual(a['metrics']['output_tokens'],6)
                    self.assertEqual(a['metrics']['reasoning_tokens'],3)
                    self.assertEqual(len(a['tool_executions']),2)
                    self.assertTrue(all(q['id'] in c['text'] for c in a['retrieval']['chunks']))
                    self.assertEqual(len(a['context']['chunk_ids']),2)
                snapshot=[json.loads(line) for line in (self.home/'q-a.jsonl').read_text().splitlines()]
                self.assertEqual(len(snapshot),50)
                with patch.object(e,'http_call') as no_calls,contextlib.redirect_stdout(io.StringIO()):
                    e.run_questions(questions,questions,records,['fixture/model'],'fixture',self.config,Log(),{},self.args,'https://foundry.invalid','fixture-key')
                no_calls.assert_not_called()

    def test_passage_reads_reject_unknown_ids_without_search(self):
        q={'id':'q001','question':'Question','as_of':'2025-06-30'}
        result=e.initial_answer(q,'fixture/model',self.args,'https://foundry.invalid',Log())
        call={'id':'read','function':{'name':'read_passages','arguments':json.dumps({'passage_ids':['unknown:1']})}}
        d=Dispatcher()
        with patch.object(d,'read') as read:
            response=e.tool_result(q,result,call,self.args,self.config,Log(),d)
        read.assert_not_called();self.assertIn('error',json.loads(response['content']))

    def test_model_cannot_override_cutoff(self):
        schema=TOOLS[0]['function']['parameters']
        with self.assertRaises(Exception):e.Draft202012Validator(schema).validate({'query':'revenue','as_of':'2099-01-01'})
        self.assertEqual(filters({'as_of':'2025-01-31'},{'company':'ACME'})[0],{'range':{'filing_date':{'lte':'2025-01-31'}}})

    def test_access_rejection_stops_queued_questions(self):
        questions=[{'id':f'q{i:03d}','question':'Question','as_of':'2025-06-30'} for i in range(50)]
        records={};seen=[];lock=threading.Lock();barrier=threading.Barrier(5)
        def rejected(base,key,path,payload,model,log,qid,calls,**kwargs):
            with lock:seen.append(qid)
            barrier.wait(timeout=5)
            calls.append({'call_id':qid,'kind':'generation','stage':'fixture','model_requested':model,'attempt':1,
                          'request':{'body':payload},'response':{'error':{'code':403}},'raw_response':'{}',
                          'http_status':403,'response_headers':{},'started_at':e.utc_now(),'ended_at':e.utc_now(),
                          'latency_ms':1,'error':{'type':'http_error','message':'Forbidden'}})
            return None
        with patch.object(e,'http_call',side_effect=rejected),contextlib.redirect_stdout(io.StringIO()):
            e.run_questions(questions,questions,records,['fixture/model'],'fixture',self.config,Log(),{},self.args,'https://foundry.invalid','fixture-key')
        self.assertEqual(len(seen),5)
        self.assertEqual(sum(r['status']=='pending' for r in records.values()),45)

    def test_denied_local_admissions_are_not_http_calls(self):
        metrics=e.call_metrics([{'kind':'generation','error':{'type':'budget_admission_denied'}}],None)
        self.assertEqual(metrics['llm_api_calls'],0)
        self.assertEqual(metrics['api_http_calls'],0)
        self.assertEqual(metrics['budget_admissions_denied'],1)

class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.p=patch.object(budget,'PATH',Path(self.temp.name)/'budget.json');self.p.start();self.addCleanup(self.p.stop)

    def test_concurrent_reservations_settle_and_unknown_cost_stays_reserved(self):
        body=budget.constrain({'model':budget.MODEL,'max_tokens':128,'messages':[]})
        with ThreadPoolExecutor(max_workers=10) as pool:list(pool.map(lambda i:budget.reserve(str(i),body,'q'),range(10)))
        budget.settle({'call_id':'0','http_status':200,'response':{'id':'generation','usage':{'cost':.001}}})
        budget.settle({'call_id':'1','http_status':None,'response':None})
        data=json.loads(budget.PATH.read_text())
        self.assertEqual(data['attempts']['0']['accounted_usd'],.001)
        self.assertEqual(data['attempts']['1']['status'],'remote_cost_unknown_reserved')
        self.assertGreater(data['attempts']['1']['accounted_usd'],0)

    def test_seven_dollar_eval_cap_preserves_judge_reserve(self):
        budget.initialize();data=json.loads(budget.PATH.read_text());data['attempts']['spent']={'phase':'evaluation','status':'reported','accounted_usd':7}
        budget.PATH.write_text(json.dumps(data))
        with self.assertRaises(budget.BudgetExceeded):budget.reserve('new',{'max_tokens':128},'q')

    def test_access_halt_requires_explicit_restore_and_keeps_history(self):
        budget.initialize();data=json.loads(budget.PATH.read_text())
        data['halted']='Authentication, credit or access rejection; stop admissions';budget.PATH.write_text(json.dumps(data))
        with self.assertRaises(budget.BudgetExceeded):budget.initialize()
        budget.initialize(True)
        data=json.loads(budget.PATH.read_text());self.assertNotIn('halted',data);self.assertEqual(len(data['halt_history']),1)

if __name__=='__main__':unittest.main()
