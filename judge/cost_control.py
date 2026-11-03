"""Optional durable spending admission shared by concurrent judge processes."""
import copy
from contextlib import contextmanager
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import time

class BudgetExceeded(ValueError):
    pass

def enabled():
    return bool(os.environ.get('RAG_JUDGE_BUDGET_LEDGER'))

@contextmanager
def ledger():
    path=Path(os.environ['RAG_JUDGE_BUDGET_LEDGER'])
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=json.loads(path.read_text())
        yield data
        tmp=path.with_suffix('.tmp')
        with tmp.open('w') as stream:
            json.dump(data,stream,indent=2);stream.flush();os.fsync(stream.fileno())
        tmp.replace(path)

def owner(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
    except (OSError,IndexError):return None

def constrain(body,path):
    if path!='/openrouter/v1/chat/completions' or body.get('model')!='anthropic/claude-sonnet-5.5':
        raise BudgetExceeded('This budget admits only concurrent Sonnet 5.5 judging')
    if not 1<=body.get('max_tokens',0)<=4096:raise BudgetExceeded('Judge output limit exceeds campaign bounds')
    value=copy.deepcopy(body)
    value.setdefault('provider',{})['max_price']={'prompt':3,'completion':15,'request':0}
    return value

def reserve(call_id,body,scope,wait=True):
    size=len(json.dumps(body,ensure_ascii=False).encode())+8192
    upper=(Decimal(size)*3+Decimal(body['max_tokens'])*15)/Decimal(1000000)
    while True:
        waiting=False;reason=None
        with ledger() as data:
            items=list(data['attempts'].values())
            for item in items:
                if item['status']=='reserved' and owner(item['pid'])!=item['owner_start']:
                    item['status']='interrupted_remote_cost_unknown_reserved'
            committed=sum(Decimal(str(a['accounted_usd'])) for a in items)
            if data.get('halted'):reason=data['halted']
            elif committed+upper<=Decimal(str(data['limit_usd'])):
                data['attempts'][call_id]={'scope':scope,'upper_bound_usd':float(upper),'accounted_usd':float(upper),
                    'status':'reserved','pid':os.getpid(),'owner_start':owner(os.getpid())}
            elif wait and any(a['status']=='reserved' for a in items):waiting=True
            else:reason=f'Judge budget exhausted: ${committed:.6f} committed/reserved; next bound ${upper:.6f}; limit ${data["limit_usd"]}'
        if reason:raise BudgetExceeded(reason)
        if not waiting:return float(upper)
        time.sleep(.1)

def settle(call):
    response=call.get('response') or {};cost=(response.get('usage') or {}).get('cost')
    with ledger() as data:
        item=data['attempts'][call['call_id']];item['http_status']=call['http_status'];item['generation_id']=response.get('id')
        if isinstance(cost,(int,float)) and cost>=0:
            item.update(accounted_usd=cost,reported_cost_usd=cost,status='reported')
            if cost>item['upper_bound_usd']:data['halted']='Reported cost exceeded conservative reservation'
        elif call['http_status'] in (400,401,402,403,404,422,429) and not response.get('id'):
            item.update(accounted_usd=0,status='rejected_before_generation')
        else:item['status']='remote_cost_unknown_reserved'
        if call['http_status'] in (401,402,403):data['halted']='Authentication, credit or access rejection; stop further admissions'
        return copy.deepcopy(item)
