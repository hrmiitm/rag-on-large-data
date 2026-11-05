#!/usr/bin/env python3
"""Run the existing shared judge against the top-level Elasticsearch method.

The shared judge CLI currently accepts only lume/ folders; this adapter reuses
its exact evaluation, gold joins, compact export, scoring and resume functions
without relocating the Elasticsearch method or changing other experiments.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

from common import DB, HOME, REPO, save
import budget


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--concurrency',type=int,default=5)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--export-only',action='store_true')
    parser.add_argument('--retry-errors',action='store_true')
    parser.add_argument('--resume-after-access-restored',action='store_true')
    args=parser.parse_args(argv)
    if not 1<=args.concurrency<=10:parser.error('concurrency must be 1..10')
    if args.dry_run and args.export_only:parser.error('Choose dry-run or export-only')
    if args.dry_run and args.resume_after_access_restored:parser.error('Dry-run cannot clear an access halt')
    if args.resume_after_access_restored:
        budget.initialize(True)
    elif not args.dry_run and not budget.PATH.exists():
        budget.initialize()
    os.environ['RAG_JUDGE_BUDGET_LEDGER']=str(budget.PATH)
    spec=importlib.util.spec_from_file_location('shared_sec_judge',REPO/'judge/eval.py')
    judge=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(judge)
    source=HOME/'q-a.jsonl'
    before=sha256(source)
    records=judge.read_jsonl(source,'question_id')
    eligible=sum(a.get('status')=='ok' and isinstance(a.get('final_answer'),str) and bool(a['final_answer'].strip())
                 for r in records.values() for a in r['answers'].values())
    options=['elasticsearch','--mode','concurrent','--concurrency',str(args.concurrency)]
    for name in ('dry_run','export_only','retry_errors'):
        if getattr(args,name):options.append('--'+name.replace('_','-'))
    settings=judge.parser().parse_args(options)
    base,key=judge.environment(require_key=eligible>0 and not (args.dry_run or args.export_only))
    output=REPO/'judge/final-results/q-a-eval-elasticsearch.jsonl'
    artifacts=REPO/'judge'/output.name
    state=artifacts.with_suffix('.state.json')
    audit=artifacts.with_suffix('.audit.jsonl')
    if args.dry_run:
        result=judge.evaluate(settings,source,output,state,audit,base,key)
    else:
        with artifacts.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=judge.evaluate(settings,source,output,state,audit,base,key)
    if sha256(source)!=before:raise RuntimeError('Source changed while judging; inspect the source writer before resuming')
    if not args.dry_run:
        exported=judge.read_jsonl(output,'question_id')
        statuses={}
        for row in exported.values():
            for answer in row['answers'].values():
                status=answer.get('judge_details',{}).get('status','pending')
                statuses[status]=statuses.get(status,0)+1
                if status!='completed' and answer.get('judge') is not None:
                    raise ValueError('Uncompleted judgment must retain null scores')
        ledger=json.loads(budget.PATH.read_text())
        attempts=[a for a in ledger['attempts'].values() if a.get('phase')!='evaluation']
        save(REPO/'judge/validation/elasticsearch-judge-report.json',{
            'status':'no_eligible_answers' if not eligible else 'completed' if statuses.get('completed')==eligible else 'incomplete',
            'source':str(source.relative_to(REPO)),'source_sha256':before,'source_preserved':True,
            'output':str(output.relative_to(REPO)),'questions':len(exported),'eligible_answers':eligible,
            'judge_status_counts':statuses,'judge_model':settings.model,'reasoning_effort':settings.reasoning_effort,
            'temperature':settings.temperature,'mode':settings.mode,'concurrency':args.concurrency,
            'judge_budget_accounted_usd':sum(a['accounted_usd'] for a in attempts),
            'new_judge_generation_calls':0 if not eligible else None,'total_budget_limit_usd':15,
            'not_a_completed_scored_benchmark':statuses.get('completed',0)!=len(exported)})
    return result


if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,OSError) as error:
        print(f'Judge failed: {error}',file=sys.stderr)
        sys.exit(1)
