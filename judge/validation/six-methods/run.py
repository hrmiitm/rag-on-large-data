"""Two method processes, five workers each; shared $14 admission ledger."""
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import datetime,json,os,subprocess,sys
from pathlib import Path
folder=Path(__file__).resolve().parent;root=folder.parents[2];os.chdir(root)
methods=sys.argv[1:] or ['hybrid-rerank','hyde','rrf','rrf-rerank','self-reflective-rag','semantic-rerank']
ledger=folder/'budget.json'
if not ledger.exists():ledger.write_text(json.dumps({'limit_usd':14,'scope':'six-method Sonnet judging; separate from answer generation','attempts':{}},indent=2))
env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','RAG_JUDGE_BUDGET_LEDGER':str(ledger)}
python=root/'lume/hybrid-rerank/runtime/src/.venv/bin/python';progress=folder/'progress.json'
def run(method):
 command=[str(python),str(root/'judge/eval.py'),method,'--mode','concurrent','--concurrency','5','--model','anthropic/claude-sonnet-5.5','--reasoning-effort','low','--temperature','0','--max-output-tokens','4096']
 if os.environ.get('RAG_JUDGE_RETRY_ERRORS')=='1':command+=['--retry-errors']
 print('START',method,flush=True)
 with (folder/f'{method}.log').open('a') as log:code=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
 data=json.loads(ledger.read_text());summary={'method':method,'exit_code':code,'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reported_usd':sum(a.get('reported_cost_usd',0) for a in data['attempts'].values()),'committed_usd':sum(a['accounted_usd'] for a in data['attempts'].values())}
 print(json.dumps(summary),flush=True);return summary
with ThreadPoolExecutor(2) as pool:
 queue=iter(methods);active={};failed=False;records=[]
 def fill():
  while len(active)<2 and not failed:
   method=next(queue,None)
   if method is None:return
   active[pool.submit(run,method)]=method
 fill()
 while active:
  done,_=wait(active,return_when=FIRST_COMPLETED)
  for f in done:
   item=f.result();active.pop(f);records.append(item);failed=failed or item['exit_code']!=0
  progress.write_text(json.dumps(records,indent=2));fill()
if failed:raise SystemExit(1)
print('ALL REQUESTED JUDGE RUNS COMPLETE',flush=True)
