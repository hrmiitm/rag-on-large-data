"""Durable, cross-process admission control for an explicitly budgeted campaign.

Unknown remote acceptance retains the entire reservation; retries reserve again.
Only the current answer model and single-query embeddings are admitted.
"""
import copy
import fcntl
import json
import os
from pathlib import Path
from decimal import Decimal
from contextlib import contextmanager

class BudgetExceeded(RuntimeError):
    pass

@contextmanager
def ledger():
    path=Path(os.environ['RAG_SPEND_LEDGER'])
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=json.loads(path.read_text()) if path.exists() else {'limit_usd':9.5,'user_cap_usd':10,'attempts':{}}
        yield data
        tmp=path.with_suffix('.tmp')
        with tmp.open('w') as output:
            json.dump(data,output,indent=2);output.flush();os.fsync(output.fileno())
        tmp.replace(path)

def enabled():
    return bool(os.environ.get('RAG_SPEND_LEDGER'))

def constrained(payload,path):
    result=copy.deepcopy(payload)
    if path.endswith('/chat/completions'):
        if result.get('model')!='google/gemini-3.8-flash':raise BudgetExceeded('Campaign admits only Gemini 3.8 Flash; no judge')
        if not 1<=result.get('max_tokens',0)<=8192:raise BudgetExceeded('Unbounded output request')
        result.setdefault('provider',{})['max_price']={'prompt':1.5,'completion':7.5,'request':0}
    elif path.endswith('/embeddings'):
        inputs=result.get('input')
        if result.get('model')!='openai/text-embedding-3-small' or not (isinstance(inputs,str) or isinstance(inputs,list) and len(inputs)==1 and isinstance(inputs[0],str)):
            raise BudgetExceeded('Only one query embedding per request is admitted')
        if len(json.dumps(inputs).encode())>20000:raise BudgetExceeded('Query embedding is too large')
    else:raise BudgetExceeded('Paid route outside answer campaign')
    return result

def reserve(call_id,payload,path,question_id):
    # UTF-8 payload bytes conservatively bound input tokens, including scaffolding.
    size=len(json.dumps(payload,ensure_ascii=False).encode())+8192
    upper=(Decimal(size)*Decimal('1.5')+Decimal(payload.get('max_tokens',0))*Decimal('7.5'))/Decimal(1000000)
    if path.endswith('/embeddings'):upper=max(Decimal('.01'),Decimal(size)/Decimal(1000000))
    with ledger() as data:
        committed=sum(Decimal(str(a['accounted_usd'])) for a in data['attempts'].values())
        if data.get('halted') or committed+upper>Decimal(str(data['limit_usd'])):
            raise BudgetExceeded(f'Budget admission stopped: committed/reserved ${committed:.6f}; next upper bound ${upper:.6f}; admission limit ${data["limit_usd"]}')
        data['attempts'][call_id]={'method':os.environ.get('LUME_VARIANT','hybrid-rerank'),'question_id':question_id,'model':payload['model'],'upper_bound_usd':float(upper),'accounted_usd':float(upper),'status':'reserved'}
    return float(upper)

def settle(call):
    response=call.get('response') or {};cost=(response.get('usage') or {}).get('cost')
    with ledger() as data:
        item=data['attempts'][call['call_id']]
        item['generation_id']=response.get('id');item['http_status']=call.get('http_status')
        if isinstance(cost,(float,int)) and cost>=0:
            item.update(accounted_usd=cost,reported_cost_usd=cost,status='reported')
            if cost>item['upper_bound_usd']:data['halted']='Reported cost exceeded conservative reservation'
        elif call.get('http_status') in (400,401,402,403,404,422,429) and not response.get('id'):
            item.update(accounted_usd=0,status='rejected_before_generation')
        else:item['status']='remote_cost_unknown_reserved'
        return copy.deepcopy(item)

def reconcile(response):
    stats=response.get('data') or {};gid=stats.get('id');cost=stats.get('total_cost')
    if not gid or not isinstance(cost,(int,float)) or cost<0:return
    with ledger() as data:
        for item in data['attempts'].values():
            if item.get('generation_id')==gid and item.get('reported_cost_usd') is None:
                item.update(accounted_usd=cost,reported_cost_usd=cost,status='metadata_reported')
                if cost>item['upper_bound_usd']:data['halted']='Metadata cost exceeded reservation'
