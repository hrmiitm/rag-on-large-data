"""No-network tests for coordinated outage backoff and preserving billing audit."""
from concurrent.futures import ThreadPoolExecutor
import io
import base64
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error

from gateway import GatewayGuard
import setup as s
import run_all


class GatewayTests(unittest.TestCase):
    def test_supervisor_recovers_only_explicit_transient_failure(self):
        args=type('Args',(),{'embedding_concurrency':32,'embedding_batch_size':256})()
        state={'stage_exit_codes':{'ingestion':{'shared':76}}}
        with patch.object(run_all,'stage',side_effect=[False,True]) as stage,patch.object(run_all,'update'),patch.object(run_all.time,'sleep') as sleep:
            run_all.ingest_with_recovery(state,args,['--adaptive'])
        self.assertEqual(stage.call_count,2);self.assertEqual(sleep.call_count,12)
        self.assertEqual(len(state['ingestion_recovery_history']),1)
        state={'stage_exit_codes':{'ingestion':{'shared':1}}}
        with patch.object(run_all,'stage',return_value=False) as stage,patch.object(run_all.time,'sleep') as sleep:
            with self.assertRaises(RuntimeError):run_all.ingest_with_recovery(state,args,[])
        self.assertEqual(stage.call_count,1);sleep.assert_not_called()

    def test_supervisor_recovery_is_bounded(self):
        args=type('Args',(),{'embedding_concurrency':32,'embedding_batch_size':256})()
        state={'stage_exit_codes':{'ingestion':{'shared':76}}}
        with patch.object(run_all,'stage',return_value=False) as stage,patch.object(run_all,'update'),patch.object(run_all.time,'sleep'):
            with self.assertRaises(RuntimeError):run_all.ingest_with_recovery(state,args,[])
        self.assertEqual(stage.call_count,4);self.assertEqual(len(state['ingestion_recovery_history']),3)

    def test_errors_activate_cooldown_and_gradual_recovery(self):
        clock=[100.];guard=GatewayGuard(clock=lambda:clock[0])
        guard.error(502);guard.error(None)
        self.assertFalse(guard.snapshot()['degraded'])
        guard.error(502)
        self.assertEqual(guard.snapshot()['http_concurrency_limit'],4)
        self.assertEqual(guard.snapshot()['cooldown_seconds'],15)
        clock[0]=175
        self.assertEqual(guard.snapshot()['http_concurrency_limit'],8)
        clock[0]=220
        self.assertEqual(guard.snapshot()['http_concurrency_limit'],64)
        guard.error(429,30)
        self.assertEqual(guard.snapshot()['cooldown_seconds'],30)

    def test_already_queued_retries_obey_shared_four_request_limit(self):
        guard=GatewayGuard(cooldown=0)
        for _ in range(3):guard.error(502)
        lock=threading.Lock();peak=0;completed=[]
        def task(i):
            nonlocal peak
            with guard.slot(lambda:None):
                with lock:peak=max(peak,guard.snapshot()['http_inflight'])
                time.sleep(.01)
            completed.append(i)
        with ThreadPoolExecutor(max_workers=32) as pool:list(pool.map(task,range(32)))
        self.assertEqual(peak,4);self.assertEqual(sorted(completed),list(range(32)))
        self.assertEqual(guard.snapshot()['http_inflight'],0)

    def test_pause_interrupts_gateway_wait_without_sending_request(self):
        guard=GatewayGuard();guard.error(429)
        stop=threading.Event();entered=[]
        def check():
            if stop.is_set():raise s.IngestionPaused('test pause')
        def worker():
            with guard.slot(check):entered.append(True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(worker);stop.set()
            with self.assertRaises(s.IngestionPaused):future.result(timeout=2)
        self.assertEqual(entered,[]);self.assertEqual(guard.snapshot()['workers_waiting'],0)

    def test_gateway_exhaustion_is_retryable_and_audited_without_secret(self):
        with tempfile.TemporaryDirectory() as d,patch.object(s,'SHARED',Path(d)),patch.object(s,'credentials',return_value=('https://fixture.invalid','fixture-secret')):
            embed=s.Embedder();embed.gateway.cooldown=0
            def failed(*args,**kwargs):raise urllib.error.HTTPError('https://fixture.invalid',502,'upstream',{},io.BytesIO(b'upstream fixture-secret'))
            with patch.object(s.urllib.request,'urlopen',side_effect=failed) as request,patch.object(s.STOP,'wait',return_value=False):
                with self.assertRaises(s.TransientEmbeddingError):embed.request(['body'],'batch')
            embed.audit.close()
            self.assertEqual(request.call_count,6)
            raw=(Path(d)/'embedding-audit.jsonl').read_text()
            self.assertNotIn('fixture-secret',raw)
            self.assertEqual(sum(json.loads(l)['event']=='error' for l in raw.splitlines()),6)

    def test_truncated_response_retries_and_saves_successful_transport_metrics(self):
        with tempfile.TemporaryDirectory() as d,patch.object(s,'SHARED',Path(d)),patch.object(s,'credentials',return_value=('https://fixture.invalid','fixture-secret')):
            embed=s.Embedder()
            blob=s.struct.pack('<'+'f'*s.DIMS,1.,*([0.]*(s.DIMS-1)))
            raw=json.dumps({'model':s.EMBED_MODEL,'data':[{'index':0,'embedding':base64.b64encode(blob).decode()}],'usage':{'prompt_tokens':1,'cost':.000001}}).encode()
            class Response:
                headers={}
                def __enter__(self):return self
                def __exit__(self,*args):pass
                def read(self):return raw
            with patch.object(s.urllib.request,'urlopen',side_effect=[http.client.IncompleteRead(b'partial'),Response()]) as request,patch.object(s.STOP,'wait',return_value=False):
                vectors,info=embed.request(['body'],'batch')
            embed.audit.close()
            self.assertEqual(vectors,[blob]);self.assertEqual(request.call_count,2)
            self.assertEqual(info['transport']['response_wire_bytes'],len(raw))
            rows=[json.loads(l) for l in (Path(d)/'embedding-audit.jsonl').read_text().splitlines()]
            self.assertEqual([x['event'] for x in rows],['request','error','request','response'])
            self.assertEqual(rows[1]['remote_outcome'],'unknown')


if __name__=='__main__':unittest.main()
