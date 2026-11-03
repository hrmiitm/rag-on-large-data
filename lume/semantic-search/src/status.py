#!/usr/bin/env python3
"""Read-only pipeline progress, reported API costs and measured-rate estimates."""
import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from setup import resource_waits

REPO=Path(__file__).resolve().parents[3]
SHARED=REPO/'lume/semantic-search/db'
METHODS=('semantic-search','hybrid')
TOTAL=640745

def jsonl(path):
    if not path.exists():return []
    rows=[]
    with path.open() as f:
        for line in f:
            if not line.endswith('\n'):break  # An append may still be in flight.
            if line.strip():rows.append(json.loads(line))
    return rows

def answer_cost(answer,seen):
    cost=0.
    for call in answer.get('api_calls',[]):
        identity=call.get('call_id')
        if call.get('kind')!='generation' or identity in seen:continue
        seen.add(identity)
        value=((call.get('response') or {}).get('usage') or {}).get('cost')
        if value is None:value=((call.get('generation_metadata') or {}).get('data') or {}).get('total_cost')
        if isinstance(value,(int,float)):cost+=value
    return cost+sum(answer_cost(a,seen) for a in answer.get('attempt_history',[]))

def judge_cost(details):
    value=(details.get('metrics') or {}).get('api_cost_usd')
    return (value if isinstance(value,(int,float)) else 0.)+sum(judge_cost(h) for h in details.get('attempt_history',[]))

def snapshot():
    now=dt.datetime.now(dt.timezone.utc)
    state=json.loads((SHARED/'pipeline-state.json').read_text())
    events=jsonl(SHARED/'embedding-audit.jsonl')
    requests={r['call_id']:r for r in events if r.get('event')=='request'}
    open_requests=set(requests)
    for event in events:
        if event.get('event') in ('response','error','interrupted'):open_requests.discard(event['call_id'])
    responses=[r for r in events if r.get('event')=='response']
    documents={r['batch_id']:r for r in responses if not r['batch_id'].endswith('/queries.bin')}
    count=sum(r['count'] for r in documents.values())
    seals=[json.loads(p.read_text()) for p in (SHARED/'index').glob('*/vectors-ready.json')]
    verified=sum(s['chunks'] for s in seals)
    embedded=TOTAL if verified==TOTAL else min(count,TOTAL)
    observed_cost=sum((r.get('usage') or {}).get('cost') or 0 for r in responses)
    doc_cost=sum((r.get('usage') or {}).get('cost') or 0 for r in documents.values())
    cost_complete=all(isinstance((r.get('usage') or {}).get('cost'),(int,float)) for r in responses)
    first=min(dt.datetime.fromisoformat(r['time_utc']) for r in requests.values())
    elapsed=(now-first).total_seconds()
    overall_rate=count/max(1,elapsed)
    session_start=dt.datetime.fromisoformat(state.get('started_at',first.isoformat()))
    window_start=max(now-dt.timedelta(minutes=10),session_start,first)
    window_seconds=max(1,(now-window_start).total_seconds())
    recent_count=0;short_count=0
    short_start=max(window_start,now-dt.timedelta(minutes=2))
    short_seconds=max(1,(now-short_start).total_seconds())
    for r in documents.values():
        request=requests.get(r['call_id'],{})
        if not request.get('time_utc'):continue
        completed=dt.datetime.fromisoformat(request['time_utc'])+dt.timedelta(seconds=r['latency_seconds'])
        if completed>=window_start:recent_count+=r['count']
        if completed>=short_start:short_count+=r['count']
    recent_rate=recent_count/window_seconds
    short_rate=short_count/short_seconds
    remaining=max(0,TOTAL-embedded)
    # Historical throughput includes pauses and obsolete worker settings. Use
    # current-session windows for the live forecast after enough replies arrive.
    rates=([recent_rate] if recent_count>=1280 and window_seconds>=60 else [])+([short_rate] if short_count>=1280 and short_seconds>=60 else [])
    etas=[remaining/r for r in rates if r>0]
    waits=resource_waits()
    answer_count=judge_count=0;generation_cost=judging_cost=0.;seen=set()
    for method in METHODS:
        for record in jsonl(REPO/'lume'/method/'q-a.jsonl'):
            for answer in record.get('answers',{}).values():
                answer_count+=answer.get('status')=='ok'
                generation_cost+=answer_cost(answer,seen)
        for record in jsonl(REPO/'judge/final-results'/f'q-a-eval-lume-{method}.jsonl'):
            for answer in record.get('answers',{}).values():
                details=answer.get('judge_details') or {}
                judge_count+=details.get('status')=='completed'
                judging_cost+=judge_cost(details)
    # Local measured BM25 costs are a planning proxy, not a new price lookup.
    generation=[];judgments=[]
    for record in jsonl(REPO/'judge/final-results/q-a-eval-lume-bm25.jsonl'):
        for model,answer in record.get('answers',{}).items():
            value=(answer.get('metrics') or {}).get('api_cost_usd')
            if model=='google/gemini-3.8-flash' and answer.get('status')=='ok' and isinstance(value,(int,float)):generation.append(value)
            details=answer.get('judge_details') or {};value=(details.get('metrics') or {}).get('api_cost_usd')
            if details.get('model_requested')=='anthropic/claude-sonnet-5.5' and details.get('status')=='completed' and isinstance(value,(int,float)):judgments.append(value)
    query_cost=sum((r.get('usage') or {}).get('cost') or 0 for r in responses if r['batch_id'].endswith('/queries.bin'))
    embedding_estimate=doc_cost/count*TOTAL+query_cost if count else None
    generation_estimate=sum(generation)/len(generation)*100 if generation else None
    judge_estimate=sum(judgments)/len(judgments)*100 if judgments else None
    total_estimate=sum((embedding_estimate,generation_estimate,judge_estimate)) if all(v is not None for v in (embedding_estimate,generation_estimate,judge_estimate)) else None
    alive=Path(f"/proc/{state.get('supervisor_pid')}").exists()
    runtime_path=SHARED/'embedding-runtime.json'
    runtime=json.loads(runtime_path.read_text()) if runtime_path.exists() else None
    if runtime and not Path(f"/proc/{runtime['pid']}").exists():runtime=None
    if runtime:
        runtime['snapshot_age_seconds']=(now-dt.datetime.fromisoformat(runtime['updated_at'])).total_seconds()
        runtime['audit_open_http_requests']=len(open_requests)
    lease_path=SHARED/'resource-lease.json'
    lease=json.loads(lease_path.read_text()) if lease_path.exists() else None
    if lease:
        lease['watcher_alive']=Path(f"/proc/{lease['pid']}").exists()
        lease['maximum_remaining_seconds']=max(0,lease['maximum_seconds']-(now-dt.datetime.fromisoformat(lease['started_at'])).total_seconds())
    return {'checked_at_utc':now.isoformat(),'stage':state.get('stage'),'status':state.get('status'),'supervisor_alive':alive,'resource_waits':waits,'embedding_execution':runtime,'resource_lease':lease,
        'embedding':{'received_vectors':embedded,'total_chunks':TOTAL,'percent':embedded/TOTAL*100,'verified_chunks':verified,'verified_shards':len(seals),'total_shards':33,
            'error_attempts':sum(r.get('event')=='error' for r in events),'reported_cost_usd':observed_cost,'reported_cost_complete':cost_complete,
            'elapsed_seconds':elapsed,'overall_vectors_per_second':overall_rate,'recent_10m_vectors_per_second':recent_rate,'recent_window_seconds':window_seconds,
            'recent_2m_vectors_per_second':short_rate,'recent_2m_window_seconds':short_seconds,
            'estimated_total_cost_usd':embedding_estimate,'eta_seconds_low':min(etas) if etas else None,'eta_seconds_high':max(etas) if etas else None},
        'answers':{'completed':answer_count,'total':100,'reported_cost_usd':generation_cost,'estimated_total_cost_usd':generation_estimate},
        'judges':{'completed':judge_count,'total':100,'reported_cost_usd':judging_cost,'estimated_total_cost_usd':judge_estimate},
        'reported_total_cost_usd':observed_cost+generation_cost+judging_cost,'estimated_total_cost_usd':total_estimate,
        'historical_cost_sample_counts':{'bm25_answers':len(generation),'bm25_judgments':len(judgments)},'resources':state.get('resources'),
        'notes':['Costs are reported API amounts; unreported charges are unavailable.','Embedding ETA excludes later answer generation, metadata and judging.','ETA compares current-session recent 2/10-minute rates after warmup; it is not a confidence interval.','Answer/judge forecasts use measured BM25 averages for the same models; token counts and retries may differ.']}

def duration(seconds):
    if seconds is None:return 'unavailable'
    minutes=round(seconds/60);return f'{minutes//60}h {minutes%60:02d}m'

def money(value):return f'${value:.2f}' if value is not None else 'unavailable'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--json',action='store_true');parser.add_argument('--timezone',default='Asia/Kolkata');args=parser.parse_args()
    s=snapshot()
    if args.json:print(json.dumps(s,indent=2));return
    e=s['embedding'];zone=ZoneInfo(args.timezone);now=dt.datetime.fromisoformat(s['checked_at_utc'])
    print(f"Checked {now.astimezone(zone):%d %b %Y, %H:%M:%S %Z} | {s['status']} | stage: {s['stage']} | supervisor: {'alive' if s['supervisor_alive'] else 'not running'}")
    print(f"Embeddings received: {e['received_vectors']:,}/{e['total_chunks']:,} ({e['percent']:.2f}%)")
    print(f"Native storage verified: {e['verified_chunks']:,} chunks | {e['verified_shards']}/{e['total_shards']} shards ({e['verified_chunks']/TOTAL*100:.2f}%)")
    run=s.get('embedding_execution')
    if run:
        print(f"Embedding batch workers: {run['active_batches']} outstanding | target {run['target_concurrency']}/{run['maximum_concurrency']} | live ceiling {run.get('concurrency_limit',run['maximum_concurrency'])} | {run['admission_reason']} | process RSS {run['resources'].get('process_rss_mb',0):.0f} MiB")
        gateway=run.get('gateway') or {}
        if gateway:print(f"HTTP requests: {gateway['http_inflight']} active | {gateway['workers_waiting']} workers waiting | gateway limit {gateway['http_concurrency_limit']} | cooldown {gateway['cooldown_seconds']:.0f}s")
        if run.get('snapshot_age_seconds',0)>15:print(f"Worker snapshot is {run['snapshot_age_seconds']:.0f}s old; audit has {run['audit_open_http_requests']} open HTTP requests.")
    lease=s.get('resource_lease')
    if lease and lease['status']=='active' and lease['watcher_alive']:
        print(f"Desktop file extractor temporarily paused; automatic restore at ingestion end/stop or within {duration(lease['maximum_remaining_seconds'])}.")
    print(f"Answers: {s['answers']['completed']}/100 | Judgments: {s['judges']['completed']}/100 | Embedding API error attempts: {e['error_attempts']}")
    print(f"Reported costs so far: embedding {money(e['reported_cost_usd'])} + answers {money(s['answers']['reported_cost_usd'])} + judging {money(s['judges']['reported_cost_usd'])} = {money(s['reported_total_cost_usd'])}")
    print(f"Projected full costs: embedding {money(e['estimated_total_cost_usd'])} + answers {money(s['answers']['estimated_total_cost_usd'])} + judging {money(s['judges']['estimated_total_cost_usd'])} = {money(s['estimated_total_cost_usd'])}")
    print(f"Embedding elapsed (includes pauses): {duration(e['elapsed_seconds'])} | Rate: historical {e['overall_vectors_per_second']:.1f}/sec, recent {round(e['recent_window_seconds']/60)}m {e['recent_10m_vectors_per_second']:.1f}/sec, last {round(e['recent_2m_window_seconds']/60)}m {e['recent_2m_vectors_per_second']:.1f}/sec")
    if s['status']=='waiting_for_gateway' or (run and (run.get('gateway') or {}).get('cooldown_seconds',0)>0):
        print('Gateway recovery/backoff is active; saved progress retained. ETA unavailable during backoff.')
    elif run and run.get('admission_reason')=='waiting_for_memory_pressure':
        print('New embedding requests are waiting for system memory pressure to ease; saved progress retained.')
        print('ETA unavailable during memory-pressure wait.')
    elif s.get('resource_waits'):
        for wait in s['resource_waits']:print(f"Waiting for RAM: {wait['available_ram_mb']:.0f} MiB available; {wait['required_available_ram_mb']:.0f} MiB required. Saved progress retained.")
        print('ETA unavailable during resource wait; ingestion resumes automatically when RAM recovers.')
    elif s['supervisor_alive'] and e['eta_seconds_low'] is None:
        print('ETA unavailable while gathering current-session throughput samples.')
    elif s['supervisor_alive'] or e['received_vectors']==TOTAL:
        print(f"Estimated ingestion remaining: {duration(e['eta_seconds_low'])} - {duration(e['eta_seconds_high'])}")
        if e['eta_seconds_low'] is not None:
            early=now+dt.timedelta(seconds=e['eta_seconds_low']);late=now+dt.timedelta(seconds=e['eta_seconds_high'])
            print(f"Estimated ingestion finish: {early.astimezone(zone):%d %b %H:%M %Z} - {late.astimezone(zone):%d %b %H:%M %Z}")
    else:print('ETA unavailable while supervisor is not running.')
    r=s.get('resources') or {}
    if r:print(f"Last resource sample: job RSS {r['supervised_rss_mb']:.0f} MiB | system available RAM {r['system_available_ram_mb']/1024:.1f} GiB | free disk {r['free_disk_gib']:.1f} GiB")
    print('Estimates vary with gateway speed and token usage. Ingestion ETA excludes later answering/judging.')

if __name__=='__main__':main()
