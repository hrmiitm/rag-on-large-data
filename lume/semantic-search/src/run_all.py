#!/usr/bin/env python3
"""Durable local supervisor: ingestion -> both 50-question runs -> both judges.

No Git operations. Re-running resumes saved embedding batches, answers and judges.
Use --wait-for-ingestion-pid only to adopt an already-running ingestion process.
"""
import argparse, datetime, fcntl, json, os, signal, subprocess, sys, time
from pathlib import Path
from setup import REPO, SHARED, save, resource_waits

PYTHON=Path(sys.executable).absolute()
METHODS=('semantic-search','hybrid')
STATE=SHARED/'pipeline-state.json'
STOP_REQUESTED=False
CHILDREN=[]
class PipelinePaused(RuntimeError):pass

def stop_pipeline(*unused):
    global STOP_REQUESTED
    STOP_REQUESTED=True
    for process in CHILDREN:
        if process.poll() is None:process.send_signal(signal.SIGTERM)

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def process_stats(extra_pids=()):
    found={os.getpid(),*extra_pids};rows=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            info=dict(l.split(':',1) for l in (p/'status').read_text().splitlines() if ':' in l)
            rows.append((int(p.name),int(info['PPid']),int(info.get('VmRSS','0 kB').split()[0])))
        except (OSError,ValueError):pass
    for _ in range(8):
        before=len(found);found.update(pid for pid,ppid,rss in rows if ppid in found)
        if before==len(found):break
    rss=sum(r for pid,ppid,r in rows if pid in found)/1024
    available=next(int(l.split()[1])/1024 for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
    return {'supervised_rss_mb':rss,'system_available_ram_mb':available,'free_disk_gib':__import__('shutil').disk_usage(REPO).free/(1<<30)}

def update(state,stage,**extra):
    state.update(stage=stage,updated_at=now(),**extra)
    roots=[state['ingestion_pid']] if state.get('ingestion_pid') and stage=='ingestion' else []
    resources=process_stats(roots);previous=state.get('resource_peaks',{})
    audit=SHARED/'embedding-audit.jsonl'
    progress=state.setdefault('embedding_progress',{'returned_document_vectors':0,'returned_query_vectors':0,'successful_http_responses':0,'reported_cost_usd':0.,'error_attempts':0})
    if audit.exists():
        with audit.open() as f:
            f.seek(state.get('_audit_offset',0))
            while True:
                position=f.tell();line=f.readline()
                if not line or not line.endswith('\n'):f.seek(position);break
                event=json.loads(line)
                if event.get('event')=='response':
                    field='returned_query_vectors' if event.get('batch_id','').endswith('/queries.bin') else 'returned_document_vectors'
                    progress[field]+=event.get('count',0);progress['successful_http_responses']+=1
                    progress['reported_cost_usd']+=(event.get('usage') or {}).get('cost') or 0
                elif event.get('event')=='error':progress['error_attempts']+=1
            state['_audit_offset']=f.tell()
    seals=[json.loads(p.read_text()) for p in (SHARED/'index').glob('*/vectors-ready.json')]
    progress['verified_native_shards']=len(seals)
    progress['verified_native_chunks']=sum(s['chunks'] for s in seals)
    state['resource_waits']=resource_waits()
    runtime=SHARED/'embedding-runtime.json'
    value=json.loads(runtime.read_text()) if runtime.exists() else None
    state['embedding_execution']=value if value and Path(f"/proc/{value['pid']}").exists() else None
    state['resources']=resources
    state['resource_peaks']={'max_supervised_rss_mb':max(previous.get('max_supervised_rss_mb',0),resources['supervised_rss_mb']),
        'min_system_available_ram_mb':min(previous.get('min_system_available_ram_mb',float('inf')),resources['system_available_ram_mb']),
        'min_free_disk_gib':min(previous.get('min_free_disk_gib',float('inf')),resources['free_disk_gib'])}
    save(STATE,state)

def stage(state,name,commands):
    if STOP_REQUESTED:raise PipelinePaused('User requested pause')
    running=[]
    for label,command,log_path in commands:
        log=log_path.open('a',buffering=1);log.write('\nSUPERVISOR START '+now()+'\n')
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1');env.pop('LUME_SEARCH_METHOD',None)
        p=subprocess.Popen(list(map(str,command)),cwd=REPO,stdout=log,stderr=subprocess.STDOUT,env=env)
        running.append((label,p,log));CHILDREN.append(p)
    update(state,name,status='running',processes={label:p.pid for label,p,log in running})
    while any(p.poll() is None for label,p,log in running):
        time.sleep(5);update(state,name)
    codes={label:p.returncode for label,p,log in running}
    for label,p,log in running:
        log.close();CHILDREN.remove(p)
    state.setdefault('stage_exit_codes',{})[name]=codes;update(state,name,processes={})
    if STOP_REQUESTED or 75 in codes.values():raise PipelinePaused('Active requests checkpointed; user requested pause')
    return all(code==0 for code in codes.values())

def count_records(path,judged=False):
    records=[json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    good=0;errors=0;cost=0.
    for r in records:
        for a in r.get('answers',{}).values():
            if judged:
                details=a.get('judge_details') or {};status=details.get('status')
                if isinstance(a.get('judge'),dict) and all(isinstance(v,(int,float)) for v in a['judge'].values()):good+=1
                elif status not in ('completed','ok'):errors+=1
                cost+=(details.get('metrics') or {}).get('api_cost_usd') or 0
            else:
                good+=a.get('status')=='ok';errors+=a.get('status') not in ('ok','truncated')
                cost+=(a.get('metrics') or {}).get('api_cost_usd') or 0
    return {'records':len(records),'successful_answers' if not judged else 'judged_answers':good,'errors_or_pending':errors,'reported_api_cost_usd':cost}

def ingest_with_recovery(state,args,adaptive_flags):
    command=[PYTHON,Path(__file__).with_name('setup.py'),'--concurrency',args.embedding_concurrency,'--batch-size',args.embedding_batch_size,*adaptive_flags]
    for attempt in range(4):
        if stage(state,'ingestion',[('shared',command,REPO/'lume/semantic-search/ingestion-progress.log')]):return
        if state['stage_exit_codes']['ingestion'].get('shared')!=76 or attempt==3:
            raise RuntimeError('Ingestion failed; completed batches remain saved')
        state.setdefault('ingestion_recovery_history',[]).append({'time_utc':now(),'exit_code':76,'recovery':attempt+1})
        # Only explicitly classified transient gateway failures are retried.
        # Every new process reuses durable caches, with no fresh corpus pass.
        for remaining in range(60,0,-5):
            if STOP_REQUESTED:raise PipelinePaused('Checkpointed; operator requested pause')
            update(state,'ingestion',status='waiting_for_gateway',retry_in_seconds=remaining)
            time.sleep(5)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-for-ingestion-pid',type=int)
    parser.add_argument('--embedding-concurrency',type=int,default=6)
    parser.add_argument('--embedding-batch-size',type=int,default=256)
    parser.add_argument('--adaptive-embeddings',action='store_true')
    parser.add_argument('--answer-concurrency-per-method',type=int,default=5)
    parser.add_argument('--judge-concurrency-per-method',type=int,default=5)
    args=parser.parse_args();SHARED.mkdir(parents=True,exist_ok=True)
    if not 1<=args.embedding_concurrency<=64:parser.error('Embedding concurrency must be 1..64')
    for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,stop_pipeline)
    adaptive_flags=['--adaptive'] if args.adaptive_embeddings else []
    with (SHARED/'pipeline.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state={'started_at':now(),'status':'running','supervisor_pid':os.getpid(),'requested_questions_per_method':50,'methods':list(METHODS),'settings':vars(args)}
        try:
            if args.wait_for_ingestion_pid:
                while Path(f'/proc/{args.wait_for_ingestion_pid}').exists():
                    update(state,'ingestion',ingestion_pid=args.wait_for_ingestion_pid);time.sleep(5)
                if not all((REPO/'lume'/m/'db/config.json').exists() for m in METHODS):
                    pause=SHARED/'ingestion-pause-before.json'
                    if pause.exists() and json.loads(pause.read_text()).get('reason')=='transfer-to-detached-supervisor':
                        pause.unlink()
                        command=[PYTHON,Path(__file__).with_name('setup.py'),'--concurrency',args.embedding_concurrency,'--batch-size',args.embedding_batch_size,*adaptive_flags]
                        if not stage(state,'ingestion_resume',[('shared',command,REPO/'lume/semantic-search/ingestion-progress.log')]):raise RuntimeError('Detached ingestion resume failed; completed batches remain saved')
                    else:raise RuntimeError('Adopted ingestion stopped before databases became ready; inspect ingestion-progress.log, then resume run_all.py')
            else:ingest_with_recovery(state,args,adaptive_flags)
            # Full real-corpus retrievals are checked by the evaluator as it writes each audited context.
            commands=[(m,[PYTHON,REPO/'lume'/m/'src/eval.py','--model','google/gemini-3.8-flash','--thinking-level','HIGH','--batch-size',args.answer_concurrency_per_method,'--defer-metadata'],REPO/'lume'/m/'evaluation-progress.log') for m in METHODS]
            if not stage(state,'answer_generation',commands):
                if not stage(state,'answer_generation_resume',commands):raise RuntimeError('Answer generation still has errors after one saved resume; inspect method logs')
            summary={m:count_records(REPO/'lume'/m/'q-a.jsonl') for m in METHODS}
            if any(v['records']!=50 or v['successful_answers']!=50 for v in summary.values()):raise RuntimeError('Expected 50 successful, nontruncated answers per method before judging')
            update(state,'answers_complete',answer_summary=summary)
            commands=[(m,[PYTHON,REPO/'lume'/m/'src/eval.py','--model','google/gemini-3.8-flash','--refresh-metadata'],REPO/'lume'/m/'evaluation-progress.log') for m in METHODS]
            if not stage(state,'generation_metadata',commands):raise RuntimeError('Generation metadata refresh failed; saved answers remain intact')
            summary={m:count_records(REPO/'lume'/m/'q-a.jsonl') for m in METHODS}
            update(state,'metadata_collected',answer_summary=summary)
            commands=[(m,[PYTHON,REPO/'judge/eval.py',m,'--mode','concurrent','--concurrency',args.judge_concurrency_per_method],REPO/'lume'/m/'judge-progress.log') for m in METHODS]
            if not stage(state,'judging',commands):
                retry_commands=[(label,[*command,'--retry-errors'],path) for label,command,path in commands]
                if not stage(state,'judging_resume',retry_commands):raise RuntimeError('Judge still reported errors after one saved retry; use judge artifacts to resume')
            results={m:count_records(REPO/'judge/final-results'/f'q-a-eval-lume-{m}.jsonl',True) for m in METHODS}
            if any(v['records']!=50 or v['judged_answers']!=50 for v in results.values()):raise RuntimeError('Judgments incomplete; inspect compact exports and judge audit')
            update(state,'complete',status='complete',completed_at=now(),judge_summary=results)
        except PipelinePaused as e:
            update(state,state.get('stage','unknown'),status='paused',paused_at=now(),pause_reason=str(e),processes={})
        except BaseException as e:
            update(state,state.get('stage','unknown'),status='failed',error=str(e));raise

if __name__=='__main__':main()
