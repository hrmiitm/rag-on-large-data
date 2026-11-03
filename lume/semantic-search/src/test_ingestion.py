"""Offline checks for bounded cross-shard dispatch and pressure backoff."""
import threading
import time
import unittest
import argparse
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
from unittest.mock import patch
import ingestion
import setup as s
from ingestion import Admission, schedule

HEALTHY={'available_ram_mb':4096,'process_rss_mb':180,'memory_stall_percent_10s':0.}

class Paused(RuntimeError):pass

class QueueTests(unittest.TestCase):
    def test_ingestion_checkpoint_compatibility_and_zero_request_resume(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);db=root/'db';db.mkdir();src=root/'src';src.mkdir()
            (src/'questions.jsonl').write_text(''.join(json.dumps({'id':str(i),'question':f'profit {i}','as_of':'2025-06-30'})+'\n' for i in range(50)))
            conn=sqlite3.connect(db/'chunks.sqlite');conn.execute('CREATE TABLE chunks(file TEXT,line INTEGER,title TEXT,body TEXT)')
            for i in range(4):conn.execute('INSERT INTO chunks VALUES(?,?,?,?)',(f'f{i}.txt',1,'Filing','profit text'))
            conn.commit();conn.close()
            class Fake:
                calls=0;base='https://fixture.invalid';rate_limited_at=0
                def request(self,texts,batch):
                    self.calls+=1
                    vector=struct.pack('<'+'f'*s.DIMS,1,*([0.]*(s.DIMS-1)))
                    return [vector]*len(texts),{'model':'text-embedding-3-small','usage':{'prompt_tokens':len(texts),'cost':.001}}
            fake=Fake()
            def native(command,root,output=None):
                root=Path(root);root.mkdir(parents=True,exist_ok=True)
                if command=='describe':
                    start=0 if root.name=='a' else 2
                    Path(output).write_text(''.join(json.dumps({'id':f'{i:016x}','file':f'f{i}.txt','line':1})+'\n' for i in range(start,start+2)))
                    return ''
                return json.dumps({'chunks':2,'peak_rss_kib':1024})
            config={'documents':4,'chunks':4,'shards':[{'name':name,'index':'index/'+name,'chunks':2} for name in ('a','b')]}
            original_schedule=ingestion.schedule
            def controlled(*args,**kwargs):return original_schedule(*args,**{**kwargs,'metrics':lambda:HEALTHY})
            with patch.object(s,'SHARED',db),patch.object(s,'SRC',src),patch.object(s,'Embedder',lambda:fake),patch.object(s,'native',native),patch.object(ingestion,'schedule',controlled):
                args=argparse.Namespace(concurrency=2,adaptive=False,batch_size=2)
                ingestion.ingest(config,args,s)
                first=fake.calls
                self.assertEqual(first,3)  # query cache + one batch per shard
                self.assertTrue(json.loads((db/'embedding-report.json').read_text())['complete'])
                ingestion.ingest(config,args,s)
                self.assertEqual(fake.calls,first)
                self.assertEqual(len(list((db/'index').glob('*/vectors-ready.json'))),2)

    def test_pressure_backoff_recovery_and_rate_limit(self):
        a=Admission(64);a.last_change=0
        self.assertEqual(a.limit(HEALTHY,now=11),24)
        self.assertEqual(a.limit(HEALTHY,now=22),32)
        self.assertEqual(a.limit({**HEALTHY,'available_ram_mb':1400},now=23),0)
        self.assertEqual(a.limit(HEALTHY,now=24),4)
        self.assertEqual(a.limit(HEALTHY,rate_limited_at=24,now=25),4)
        self.assertEqual(a.reason,'gateway_backoff')
        self.assertEqual(a.limit({**HEALTHY,'memory_stall_percent_10s':16,'available_ram_mb':2400},now=26),0)
        self.assertEqual(a.limit({**HEALTHY,'process_rss_mb':1600},now=27),0)

    def test_background_pressure_with_headroom_does_not_collapse_pool(self):
        a=Admission(64);a.last_change=0
        self.assertEqual(a.limit({**HEALTHY,'memory_stall_percent_10s':2.2},now=11),24)
        self.assertEqual(a.limit({**HEALTHY,'memory_stall_percent_10s':2.2,'process_rss_mb':520},now=22),32)
        self.assertEqual(a.limit({**HEALTHY,'available_ram_mb':1900},now=28),16)
        # Avoid halving again on every fast scheduler iteration.
        self.assertEqual(a.limit({**HEALTHY,'available_ram_mb':1900},now=29),16)

    def test_live_control_changes_ceiling_without_cancelling_requests(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'control.json';a=Admission(64,False)
            path.write_text('{"concurrency_limit":32}');a.control(path)
            self.assertEqual(a.limit(HEALTHY),32)
            path.write_text('{"concurrency_limit":64}');a.control(path)
            self.assertEqual(a.limit(HEALTHY),64)
            path.write_text('{"concurrency_limit":65}');a.control(path)
            self.assertEqual(a.limit(HEALTHY),64);self.assertIsNotNone(a.control_error)

    def test_sixty_four_workers_remain_bounded_and_complete_every_batch(self):
        states=[];barrier=threading.Barrier(64);active=0;peak=0;finished=[];lock=threading.Lock()
        def jobs():
            state={'ids':[],'batches':[],'pending':0,'closed':False,'sealed':False};states.append(state)
            for i in range(128):yield {'state':state,'id':i}
            state['closed']=True
        def execute(job):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            if job['id']<64:barrier.wait(5)
            time.sleep(.01)
            with lock:active-=1;finished.append(job['id'])
            return {'cache_hit':False}
        schedule(iter(jobs()),execute,lambda state:None,states,Admission(64,False),threading.Event(),Paused,lambda x:None,metrics=lambda:HEALTHY)
        self.assertEqual(peak,64);self.assertEqual(sorted(finished),list(range(128)))

    def test_next_shard_runs_before_slow_previous_batch_and_seals_after_completion(self):
        states=[];slow=threading.Event();next_shard=threading.Event();finished=[];sealed=[];active=0;peak=0;lock=threading.Lock()
        def jobs():
            for name,ids in [('a',[0,1]),('b',[2,3])]:
                state={'name':name,'ids':[1],'batches':[1],'pending':0,'closed':False,'sealed':False};states.append(state)
                for i in ids:yield {'state':state,'id':i}
                state['closed']=True
        def execute(job):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            if job['id']==0:
                self.assertTrue(next_shard.wait(3));slow.set()
            elif job['id']==2:next_shard.set()
            time.sleep(.01)
            with lock:active-=1;finished.append(job['id'])
            return {'cache_hit':False}
        def seal(state):
            expected={0,1} if state['name']=='a' else {2,3}
            self.assertTrue(expected.issubset(finished));sealed.append(state['name'])
        schedule(iter(jobs()),execute,seal,states,Admission(2,False),threading.Event(),Paused,lambda x:None,metrics=lambda:HEALTHY)
        self.assertTrue(slow.is_set());self.assertEqual(set(sealed),{'a','b'});self.assertEqual(peak,2)

    def test_pause_drains_only_admitted_work(self):
        stop=threading.Event();states=[];started=[]
        def jobs():
            state={'ids':[],'batches':[],'pending':0,'closed':False,'sealed':False};states.append(state)
            for i in range(20):yield {'state':state,'id':i}
            state['closed']=True
        def execute(job):
            started.append(job['id']);stop.set();return {'cache_hit':False}
        with self.assertRaises(Paused):
            schedule(iter(jobs()),execute,lambda s:None,states,Admission(1,False),stop,Paused,lambda x:None,metrics=lambda:HEALTHY)
        self.assertEqual(started,[0])

if __name__=='__main__':unittest.main()
