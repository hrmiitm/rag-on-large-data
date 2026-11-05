"""Summarize actual answer/judge records and the shared spending ledger."""
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo
from common import DB, HOME, REPO, save

def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []

def average(values):
    values=[v for v in values if isinstance(v,(int,float)) and math.isfinite(v)]
    return {'mean':mean(values) if values else None,'n':len(values)}

def summarize():
    source=HOME/'q-a.jsonl'
    rows=read(source)
    answers=[a for r in rows for a in r['answers'].values()]
    successful=[a for a in answers if a.get('status')=='ok' and a.get('final_answer')]
    exported=read(REPO/'judge/final-results/q-a-eval-elasticsearch.jsonl')
    judged=[a for r in exported for a in r['answers'].values()
            if a.get('judge_details',{}).get('status')=='completed' and isinstance(a.get('judge'),dict)]
    ledger=json.loads((DB/'budget-ledger.json').read_text())
    attempts=list(ledger['attempts'].values())
    evaluation=[a for a in attempts if a.get('phase')=='evaluation']
    judges=[a for a in attempts if a.get('phase')!='evaluation']
    scores={key:average([a['judge'].get(key) for a in judged]) for key in
            ('answer_correctness','faithfulness','context_relevance','answer_relevance')}
    latencies=average([a.get('metrics',{}).get('answer_ready_time_seconds') for a in successful])
    costs=average([a.get('metrics',{}).get('api_cost_usd') for a in successful])
    calls={}
    def collect(answer):
        for call in answer.get('api_calls',[]):calls[call['call_id']]=call
        for previous in answer.get('attempt_history',[]):collect(previous)
    for answer in answers:collect(answer)
    events=[]
    for call in calls.values():
        if call['kind']=='generation' and call.get('http_status')==200:
            events.extend([(datetime.fromisoformat(call['started_at']),1),(datetime.fromisoformat(call['ended_at']),-1)])
    active=peak=0
    for _,change in sorted(events):active+=change;peak=max(peak,active)
    complete=len(rows)==50 and len(successful)==50 and len(judged)==50
    return {'status':'completed' if complete else 'in_progress_or_blocked','reported_at_ist':datetime.now(ZoneInfo('Asia/Kolkata')).isoformat(),
      'questions':len(rows),'successful_answers':len(successful),'judged_answers':len(judged),
      'answer_status':dict(Counter(a['status'] for a in answers)),
      'judge_status':dict(Counter(a.get('judge_details',{}).get('status','pending') for r in exported for a in r['answers'].values())),
      'average_answer_ready_seconds':latencies,'average_serving_api_cost_usd':costs,
      'quality':scores,'fully_correct_answers':sum(a['judge']['answer_correctness']==1 for a in judged),
      'evaluation_reported_cost_usd':sum(a.get('reported_cost_usd',0) for a in evaluation),
      'judge_reported_cost_usd':sum(a.get('reported_cost_usd',0) for a in judges),
      'total_reported_cost_usd':sum(a.get('reported_cost_usd',0) for a in attempts),
      'total_accounted_or_reserved_usd':sum(a['accounted_usd'] for a in attempts),
      'unknown_cost_attempts':sum(a['status'] not in ('reported','rejected_before_generation') for a in attempts),
      'budget_limit_usd':ledger['limit_usd'],'budget_halted':ledger.get('halted'),
      'successful_generation_http_peak_concurrency':peak,
      'metadata_status':dict(Counter(a.get('metadata_status') for a in successful)),
      'new_embedding_api_calls':0,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
      'metric_notes':['Correctness is mean model-judge rubric score, not a human-verified accuracy rate.',
                      'Answer-ready time is active question execution; excludes pre-worker queue, metadata enrichment and judging.',
                      'Serving API cost excludes judge overhead. Reasoning tokens are already included in output.']}

if __name__=='__main__':
    report=summarize()
    save(DB/'final-report.json',report)
    print(json.dumps(report,indent=2))
