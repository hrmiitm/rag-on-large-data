"""Bounded cross-shard embedding queue with memory/pressure admission control."""
import contextlib
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
import os
from pathlib import Path
import sqlite3
import time


def pressure():
    available=next(int(l.split()[1])/1024 for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
    rss=next(int(l.split()[1])/1024 for l in Path('/proc/self/status').read_text().splitlines() if l.startswith('VmRSS:'))
    full=0.
    for line in Path('/proc/pressure/memory').read_text().splitlines():
        if line.startswith('full '):full=float(dict(x.split('=') for x in line.split()[1:])['avg10'])
    return {'available_ram_mb':available,'process_rss_mb':rss,'memory_stall_percent_10s':full}


class Admission:
    def __init__(self,maximum,adaptive=True):
        self.maximum=maximum;self.ceiling=maximum;self.adaptive=adaptive
        self.target=min(16,maximum) if adaptive else maximum
        self.last_change=time.monotonic();self.reason='starting';self.metrics={};self.control_error=None
    def control(self,path):
        """A local ceiling can be lowered/raised without cancelling paid requests."""
        self.control_error=None
        try:
            value=json.loads(path.read_text())['concurrency_limit']
            if type(value) is not int or not 1<=value<=self.maximum:raise ValueError('Invalid concurrency_limit')
            self.ceiling=value
        except FileNotFoundError:self.ceiling=self.maximum
        except (OSError,ValueError,KeyError,TypeError) as error:self.control_error=str(error)
        self.target=min(self.target,self.ceiling)
    def limit(self,metrics,rate_limited_at=0,now=None):
        now=time.monotonic() if now is None else now;self.metrics=metrics
        ram,rss,stall=(metrics[k] for k in ('available_ram_mb','process_rss_mb','memory_stall_percent_10s'))
        # PSI is machine-wide. A small background stall is not evidence that this
        # network-bound job needs throttling when several GiB remain available.
        if ram<1536 or rss>1536 or (stall>=15 and ram<2560):
            self.target=0;self.reason='waiting_for_memory_pressure';self.last_change=now
        elif ram<2048 or rss>1024 or (stall>=5 and ram<3072):
            if now-self.last_change>=5:self.target=max(2,self.target//2);self.last_change=now
            self.target=min(self.ceiling,self.target);self.reason='reduced_for_memory_pressure'
        elif rate_limited_at and now-rate_limited_at<60:
            self.target=min(4,self.ceiling);self.reason='gateway_backoff';self.last_change=now
        elif not self.adaptive:
            self.target=self.ceiling;self.reason='fixed_with_memory_guard'
        elif not self.target:
            self.target=min(4,self.ceiling);self.reason='recovering'
        elif now-self.last_change>=10 and ram>=2560 and rss<768:
            self.target=min(self.ceiling,self.target+8);self.last_change=now;self.reason='ramping_or_at_limit'
        else:self.reason='holding'
        return self.target


def schedule(jobs,execute,seal,states,admission,stop,paused_error,report,
             metrics=pressure,rate_limit=lambda:0,control=None):
    """At most maximum futures/text batches; no shard-wide request barrier."""
    pending={};exhausted=False;finished=0;cached=0;started=time.monotonic()
    with ThreadPoolExecutor(max_workers=admission.maximum) as pool:
        while pending or not exhausted:
            if control is not None:admission.control(control)
            target=admission.limit(metrics(),rate_limit())
            while not exhausted and not stop.is_set() and len(pending)<target:
                try:job=next(jobs)
                except StopIteration:exhausted=True;break
                job['state']['pending']+=1
                pending[pool.submit(execute,job)]=job
            if pending:
                done,_=wait(pending,timeout=1,return_when=FIRST_COMPLETED)
                for future in done:
                    job=pending.pop(future);job['state']['pending']-=1
                    try:result=future.result()
                    except paused_error:
                        if not stop.is_set():raise
                        continue
                    finished+=1;cached+=result.get('cache_hit',False)
            elif not stop.is_set() and not exhausted:time.sleep(1)
            for state in states:
                if state['closed'] and state['pending']==0 and not state['sealed'] and not stop.is_set():
                    seal(state);state['sealed']=True
                    # Bound retained IDs/path lists even for a long corpus.
                    state['ids'].clear();state['batches'].clear()
            report({'active_batches':len(pending),'target_concurrency':admission.target,
                'maximum_concurrency':admission.maximum,'admission_reason':admission.reason,
                'concurrency_limit':admission.ceiling,'control_error':admission.control_error,
                'resources':admission.metrics,'completed_batches_session':finished,
                'cached_batches_session':cached,'elapsed_seconds':time.monotonic()-started,
                'stopping':stop.is_set()})
            if stop.is_set() and not pending:raise paused_error('Stopped after checkpointing active requests')


def ingest(config,args,s,report_name='embedding-report.json'):
    cache=s.SHARED/'embedding-batches';cache.mkdir(exist_ok=True)
    embedder=s.Embedder();started=time.monotonic();states=[];verified=0
    questions=[json.loads(l) for l in (s.SRC/'questions.jsonl').read_text().splitlines()]
    texts=[s.clean_query(q['question']) for q in questions]
    qp=cache/'queries.bin';s.batch_cache(embedder,texts,[q['id'] for q in questions],qp)
    raw=qp.read_bytes();queries={t:raw[i*s.DIMS*4:(i+1)*s.DIMS*4] for i,t in enumerate(texts)}
    def jobs():
        nonlocal verified
        for shard in config['shards']:
            if s.STOP.is_set():return
            root=s.SHARED/shard['index'];ready=root/'vectors-ready.json'
            if ready.exists():
                if s.sha256(root/'local-vectors.bin')!=json.loads(ready.read_text())['sha256']:raise ValueError('Native vector file changed')
                verified+=shard['chunks'];continue
            if s.shutil.disk_usage(s.SHARED).free<3<<30:raise RuntimeError('Less than 3 GiB disk headroom; saved batches retained')
            desc=cache/(shard['name']+'.jsonl')
            if not desc.exists():s.native('describe',root,desc)
            state={'shard':shard,'ids':[],'batches':[],'closed':False,'pending':0,'sealed':False}
            states.append(state);seen=set();group=[];offset=0;native_count=0
            with desc.open() as f:
                for line in f:
                    d=json.loads(line);native_count+=1
                    if d['id'] in seen:continue
                    seen.add(d['id']);state['ids'].append(d['id']);group.append(d)
                    if len(group)==args.batch_size:
                        path=cache/f"{shard['name']}-{offset:06d}.bin";state['batches'].append(path)
                        yield {'rows':group,'path':path,'state':state};offset+=len(group);group=[]
            if group:
                path=cache/f"{shard['name']}-{offset:06d}.bin";state['batches'].append(path)
                yield {'rows':group,'path':path,'state':state}
            if native_count!=shard['chunks']:raise ValueError('Native/source count mismatch')
            state['closed']=True
    def execute(job):
        if s.STOP.is_set():raise s.IngestionPaused('No new request after pause')
        texts=[];ids=[]
        with contextlib.closing(sqlite3.connect(f'file:{s.SHARED}/chunks.sqlite?mode=ro',uri=True)) as conn:
            for row in job['rows']:
                c=conn.execute('SELECT title,body FROM chunks WHERE file=? AND line=?',(Path(row['file']).name,row['line'])).fetchone()
                if c is None:raise ValueError('Unmapped native section')
                ids.append(row['id']);texts.append(c[0]+'\n'+c[1])
        was_cached=job['path'].exists() and job['path'].with_suffix('.json').exists()
        s.batch_cache(embedder,texts,ids,job['path'])
        return {'cache_hit':was_cached}
    def seal(state):
        nonlocal verified
        shard=state['shard'];root=s.SHARED/shard['index'];target=root/'local-vectors.bin'
        s.write_vectors(target,state['ids'],state['batches'],queries)
        validation=json.loads(s.native('validate',root))
        s.save(root/'vectors-ready.json',{'sha256':s.sha256(target),'chunks':shard['chunks'],
            'unique_vectors':len(state['ids']),'model':s.EMBED_MODEL,'dimensions':s.DIMS,**validation})
        for path in state['batches']:path.unlink()
        verified+=shard['chunks'];print(f"Native vectors ready: {verified}/{config['chunks']} chunks ({shard['name']})",flush=True)
    last_report=0
    def report(value):
        nonlocal last_report
        now=time.monotonic()
        if now-last_report<2 and not value['stopping']:return
        last_report=now
        s.save(s.SHARED/'embedding-runtime.json',{'pid':os.getpid(),'updated_at':s.datetime.datetime.now(s.datetime.timezone.utc).isoformat(),
            'mode':'adaptive_cross_shard_queue' if args.adaptive else 'bounded_cross_shard_queue',
            'verified_chunks':verified,'gateway':embedder.gateway.snapshot() if hasattr(embedder,'gateway') else None,**value})
    schedule(iter(jobs()),execute,seal,states,Admission(args.concurrency,args.adaptive),s.STOP,s.IngestionPaused,report,
             rate_limit=lambda:embedder.rate_limited_at,control=s.SHARED/'embedding-control.json')
    receipts=[json.loads(p.read_text()) for p in cache.glob('*.json')]
    usage=[r.get('usage') or {} for r in receipts]
    counts=[u.get('prompt_tokens') for u in usage];costs=[u.get('cost') for u in usage]
    s.save(s.SHARED/report_name,{'complete':True,'documents':config['documents'],'chunks':verified,
        'dimensions':s.DIMS,'model':s.EMBED_MODEL,'gateway':embedder.base+'/openrouter/v1/embeddings',
        'successful_batches':len(receipts),'reported_input_tokens':sum(counts) if all(isinstance(x,int) for x in counts) else None,
        'reported_cost_usd':sum(costs) if all(isinstance(x,(int,float)) for x in costs) else None,
        'cost_scope':'successful cached corpus/query batches; interrupted or unknown remote outcomes remain in audit',
        'max_native_rss_mb':max(json.loads((s.SHARED/z['index']/'vectors-ready.json').read_text())['peak_rss_kib']/1024 for z in config['shards']),
        'scheduler':'bounded_cross_shard','adaptive':args.adaptive,'maximum_concurrency':args.concurrency,
        'session_elapsed_seconds':time.monotonic()-started})
