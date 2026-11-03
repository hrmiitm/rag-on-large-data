import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import spending as s

class SpendingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'budget.json'
        self.env=patch.dict(os.environ,{'RAG_SPEND_LEDGER':str(self.path)});self.env.start()
        self.payload=s.constrained({'model':'google/gemini-3.8-flash','messages':[{'role':'user','content':'hello'}],'max_tokens':8192},'/chat/completions')
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_parallel_admission(self):
        with s.ledger() as data:data['limit_usd']=.2
        def one(i):
            try:s.reserve(str(i),self.payload,'/chat/completions','q1');return True
            except s.BudgetExceeded:return False
        with ThreadPoolExecutor(10) as pool:results=list(pool.map(one,range(10)))
        self.assertGreater(sum(results),0);self.assertLess(sum(results),10)
        data=json.loads(self.path.read_text());self.assertLessEqual(sum(a['accounted_usd'] for a in data['attempts'].values()),.2)
    def test_unknown_retry_and_receipt(self):
        first=s.reserve('a',self.payload,'/chat/completions','q1')
        s.settle({'call_id':'a','http_status':503,'response':{}})
        s.reserve('b',self.payload,'/chat/completions','q1')
        s.settle({'call_id':'b','http_status':200,'response':{'id':'gen1','usage':{'cost':.01}}})
        d=json.loads(self.path.read_text());self.assertEqual(d['attempts']['a']['accounted_usd'],first);self.assertEqual(d['attempts']['b']['accounted_usd'],.01)
    def test_metadata_and_rejection(self):
        s.reserve('a',self.payload,'/chat/completions','q1');s.settle({'call_id':'a','http_status':200,'response':{'id':'gen1'}})
        s.reconcile({'data':{'id':'gen1','total_cost':.02}})
        s.reserve('b',self.payload,'/chat/completions','q1');s.settle({'call_id':'b','http_status':429,'response':{}})
        d=json.loads(self.path.read_text());self.assertEqual(d['attempts']['a']['accounted_usd'],.02);self.assertEqual(d['attempts']['b']['accounted_usd'],0)
    def test_no_judge_or_corpus_embeddings(self):
        with self.assertRaises(s.BudgetExceeded):s.constrained({'model':'anthropic/claude-sonnet-5.5','max_tokens':8192},'/chat/completions')
        with self.assertRaises(s.BudgetExceeded):s.constrained({'model':'openai/text-embedding-3-small','input':['a','b']},'/embeddings')
    def test_http_integration_and_no_send_after_denial(self):
        import common as c
        from unittest.mock import Mock
        log=Mock();log.run_id='offline'
        response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        response.status=200;response.headers={};response.read.return_value=b'{"id":"offline","usage":{"cost":0.01}}'
        calls=[]
        with patch.object(c.urllib.request,'urlopen',return_value=response) as opening:
            c.http_call('https://offline.invalid','dummy','/openrouter/v1/chat/completions',self.payload,'google/gemini-3.8-flash',log,'q1',calls)
            sent=json.loads(opening.call_args.args[0].data)
            self.assertEqual(sent['provider']['max_price']['completion'],7.5)
        self.assertEqual(calls[0]['budget_receipt']['reported_cost_usd'],.01)
        with s.ledger() as data:data['limit_usd']=.01
        with patch.object(c.urllib.request,'urlopen') as opening:
            with self.assertRaises(s.BudgetExceeded):c.http_call('https://offline.invalid','dummy','/openrouter/v1/chat/completions',self.payload,'google/gemini-3.8-flash',log,'q1',[])
            opening.assert_not_called()
