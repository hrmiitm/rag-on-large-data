import json
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import cost_control as budget

class CostControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'budget.json'
        self.path.write_text(json.dumps({'limit_usd':.2,'attempts':{}}))
        self.env=patch.dict(os.environ,{'RAG_JUDGE_BUDGET_LEDGER':str(self.path)});self.env.start()
        self.body=budget.constrain({'model':'anthropic/claude-sonnet-5.5','max_tokens':4096,'messages':[{'role':'user','content':'test'}]},'/openrouter/v1/chat/completions')
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_parallel_cap_and_no_over_admission(self):
        def one(i):
            try:budget.reserve(str(i),self.body,'fixture',wait=False);return True
            except budget.BudgetExceeded:return False
        with ThreadPoolExecutor(10) as pool:results=list(pool.map(one,range(10)))
        self.assertGreater(sum(results),0);self.assertLess(sum(results),10)
        data=json.loads(self.path.read_text());self.assertLessEqual(sum(a['accounted_usd'] for a in data['attempts'].values()),.2)
    def test_unknown_cost_retains_reservation_and_receipt_releases(self):
        upper=budget.reserve('a',self.body,'fixture');budget.settle({'call_id':'a','http_status':503,'response':{}})
        budget.reserve('b',self.body,'fixture');budget.settle({'call_id':'b','http_status':200,'response':{'id':'gen','usage':{'cost':.01}}})
        data=json.loads(self.path.read_text());self.assertEqual(data['attempts']['a']['accounted_usd'],upper);self.assertEqual(data['attempts']['b']['accounted_usd'],.01)
    def test_credit_rejection_halts_and_releases(self):
        budget.reserve('a',self.body,'fixture');budget.settle({'call_id':'a','http_status':402,'response':{}})
        with self.assertRaises(budget.BudgetExceeded):budget.reserve('b',self.body,'fixture')
        self.assertEqual(json.loads(self.path.read_text())['attempts']['a']['accounted_usd'],0)
    def test_rejects_other_models_and_native_submissions(self):
        with self.assertRaises(budget.BudgetExceeded):budget.constrain({**self.body,'model':'other/model'},'/openrouter/v1/chat/completions')
        with self.assertRaises(budget.BudgetExceeded):budget.constrain(self.body,'/openrouter/v1/batches')
    def test_unadmitted_call_does_not_send_http(self):
        import eval as runner
        with budget.ledger() as data:data['limit_usd']=0
        client=runner.Client('https://offline.invalid','secret',Path(self.tmp.name)/'audit.jsonl')
        with patch.object(runner.urllib.request,'build_opener') as opening:
            response,calls=client.call('/openrouter/v1/chat/completions',self.body)
            opening.assert_not_called()
        self.assertIsNone(response);self.assertFalse(calls[0]['http_attempted']);self.assertEqual(runner.usage_metrics(calls,response)['llm_api_calls'],0)
