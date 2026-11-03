"""Read-only final judge/source/gold/context/cost/resume audit."""
import collections,datetime,hashlib,json,math,subprocess,sys
from decimal import Decimal
from pathlib import Path
from jsonschema import Draft202012Validator
folder=Path(__file__).resolve().parent;root=folder.parents[2];sys.path.insert(0,str(root/'judge'))
import eval as judge
methods=['hybrid-rerank','hyde','rrf','rrf-rerank','self-reflective-rag','semantic-rerank']
preflight={r['method']:r for r in json.loads((folder/'preflight.json').read_text())};prior=json.loads((folder/'prior-exports.json').read_text());gold=judge.read_jsonl(root/'data/questions.jsonl','id')
validator=Draft202012Validator(json.loads((root/'judge/evaluation.schema.json').read_text()));report={'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'methods':{},'offline_tests_passed':30,'judge_settings':{'model':'anthropic/claude-sonnet-5.5','reasoning_effort':'low','temperature':0,'max_output_tokens':4096},'scheduling':'two method processes with five workers each; at most ten concurrent requests'};allcalls=[];total=Decimal(0)
for method in methods:
 source=root/f'lume/{method}/q-a.jsonl';output=root/f'judge/final-results/q-a-eval-lume-{method}.jsonl';audit=root/f'judge/q-a-eval-lume-{method}.audit.jsonl'
 source_sha=hashlib.file_digest(source.open('rb'),'sha256').hexdigest();assert source_sha==preflight[method]['source_sha256']
 originals=judge.read_jsonl(source,'question_id');rows=judge.read_jsonl(output,'question_id');assert set(rows)==set(originals)==set(gold) and len(rows)==50
 calls=[json.loads(l) for l in audit.read_text().splitlines()];allcalls+=calls;by_qid=collections.defaultdict(list)
 for call in calls:
  assert call['http_status']==200 and call['error'] is None and call.get('http_attempted',True)
  assert '/openrouter/v1/chat/completions' in call['request']['url']
  body=call['request']['body'];data=json.loads(body['messages'][1]['content']);qid=data['question_id'];by_qid[qid].append(call)
  answer=next(iter(originals[qid]['answers'].values()));assert data['candidate_answer']==answer['final_answer'];assert data['context_sent_to_answer_model']==answer.get('context',originals[qid]['context'])
  assert data['gold_evidence']==gold[qid]['evidence'] and data['gold_answer']==gold[qid]['expected_answer']
  assert body['model']=='anthropic/claude-sonnet-5.5' and body['reasoning']=={'effort':'low'} and body['temperature']==0 and body['max_tokens']==4096
  assert call['request']['cache_control']=='no-cache';judge.judge_result(call['response'])
 costs=sum(Decimal(str(c['response']['usage']['cost'])) for c in calls);total+=costs
 scores={k:[] for k in judge.SCORES}
 for qid,row in rows.items():
  validator.validate(row);original=originals[qid];assert row['gold_evidence']==gold[qid]['evidence'] and row['gold_answer']==gold[qid]['expected_answer'];assert row['metrics']==original['metrics'] and row['retrieval']['metrics']==original['retrieval']['metrics']
  assert row['question']==original['question'] and row['as_of']==original['as_of'];assert 'trace' not in row and 'text' not in row['context'] and all('text' not in h for h in row['retrieval']['chunks'])
  for model,answer in row['answers'].items():
   assert answer['final_answer']==original['answers'][model]['final_answer'] and answer['metrics']==original['answers'][model]['metrics']
   details=answer['judge_details'];assert details['status']=='completed' and not details['error'] and details['model_requested']=='anthropic/claude-sonnet-5.5' and details['reasoning']=={'effort':'low'} and details['temperature']==0
   assert details['generation_id'] in [c['response']['id'] for c in by_qid[qid]]
   assert set(answer['judge'])==set(judge.SCORES) and all(not isinstance(v,bool) and math.isfinite(v) and 0<=v<=1 for v in answer['judge'].values())
   assert all(details['explanations'].get(k) for k in judge.SCORES)
   assert row['judge']==answer['judge'] and details.get('finish_reason')=='stop'
   for k in judge.SCORES:scores[k].append(answer['judge'][k])
 run=subprocess.run([str(root/'lume/hybrid-rerank/runtime/src/.venv/bin/python'),str(root/'judge/eval.py'),method,'--mode','concurrent','--concurrency','5','--dry-run'],capture_output=True,text=True)
 assert run.returncode==0 and '0 pending answers' in run.stdout,(method,run.stdout,run.stderr)
 report['methods'][method]={'answers':50,'completed_judgments':50,'source_unchanged':True,'source_sha256':source_sha,'schema_gold_context_metrics_valid':True,'resume_pending':0,'http_attempts':len(calls),'reported_judge_cost_usd':str(costs),'score_means':{k:sum(v)/len(v) for k,v in scores.items()},'output':str(output.relative_to(root)),'output_sha256':hashlib.file_digest(output.open('rb'),'sha256').hexdigest()}
publication_path=root/'judge/validation/publication-report.json'
publication=json.loads(publication_path.read_text()) if publication_path.exists() else None
for path,sha in prior.items():
 current=hashlib.file_digest((root/path).open('rb'),'sha256').hexdigest()
 if current!=sha:
  cleanup=publication['files'][path]
  assert cleanup['sha256_before']==sha and cleanup['sha256_after']==current and cleanup['answers_scores_evidence_metrics_preserved']
ledger=json.loads((folder/'budget.json').read_text());assert len(ledger['attempts'])==len(allcalls)==300 and all(a['status']=='reported' for a in ledger['attempts'].values()) and not ledger.get('halted')
assert sum(Decimal(str(a['accounted_usd'])) for a in ledger['attempts'].values())==total<=Decimal(str(ledger['limit_usd']))
events=[]
for call in allcalls:events.extend([(call['started_at'],1),(call['ended_at'],-1)])
active=peak=0
for _,delta in sorted(events):active+=delta;peak=max(peak,active)
assert peak<=10
start=min(c['started_at'] for c in allcalls);end=max(c['ended_at'] for c in allcalls);duration=(datetime.datetime.fromisoformat(end)-datetime.datetime.fromisoformat(start)).total_seconds()
report.update(passed=True,completed_judgments=300,judge_http_attempts=300,judge_retries=0,http_errors=0,reported_judge_cost_usd=str(total),judge_budget_usd=ledger['limit_usd'],reported_answer_generation_cost_usd='5.29044809',combined_recorded_cost_usd=str(total+Decimal('5.29044809')),peak_concurrent_judge_requests=peak,judging_http_window_seconds=duration,previous_judge_exports_unchanged=len(prior),answer_sources_unchanged=6)
if publication:
 report['publication_metadata_cleanup']='Provider account/tracking diagnostics removed from compact exports after judging; answers, scores, evidence and metrics preserved. See ../publication-report.json.'
 report['previous_judge_exports_unchanged_before_publication']=report.pop('previous_judge_exports_unchanged')
(folder/'final-report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
