"""Durable shared $15 admission ledger; evaluation may account at most $7.

Uncertain accepted requests retain their full reservation. Compatible ledger
attempt fields allow the separate existing judge guard to share the total later.
"""
from contextlib import contextmanager
from decimal import Decimal
import copy
import fcntl
import json
import os
import time
from pathlib import Path
from common import DB, save

PATH=DB/'budget-ledger.json'
MODEL='google/gemini-3.8-flash'

class BudgetExceeded(ValueError):pass

def owner(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
    except (OSError,IndexError):return None

@contextmanager
def ledger():
    PATH.parent.mkdir(parents=True,exist_ok=True)
    with PATH.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        data=json.loads(PATH.read_text()) if PATH.exists() else {'limit_usd':15,'evaluation_limit_usd':7,'attempts':{}}
        if data['limit_usd']!=15 or data['evaluation_limit_usd']!=7:raise BudgetExceeded('Unexpected budget limits')
        yield data
        save(PATH,data)

def initialize(access_restored=False):
    with ledger() as data:
        if access_restored and data.get('halted'):
            if data['halted']!='Authentication, credit or access rejection; stop admissions':
                raise BudgetExceeded('Only an access halt may be cleared; spending reservations remain preserved')
            data.setdefault('halt_history',[]).append({'reason':data.pop('halted'),'cleared_at_unix':time.time()})
        if data.get('halted'):
            raise BudgetExceeded(data['halted']+'; restore access before using --resume-after-access-restored')

def constrain(body):
    if body.get('model')!=MODEL or not 128<=body.get('max_tokens',0)<=8192:
        raise BudgetExceeded('Budget admits Gemini 3.8 Flash with output capped at 8192')
    value=copy.deepcopy(body)
    value.setdefault('provider',{})['max_price']={'prompt':0.75,'completion':3.75,'request':0}
    return value

def reserve(call_id,body,question_id):
    # UTF-8 byte count upper-bounds text tokens conservatively, with extra room
    # for tool/message formatting. Output already includes reasoning tokens.
    size=len(json.dumps(body,ensure_ascii=False).encode())+8192
    upper=(Decimal(size)*Decimal('.75')+Decimal(body['max_tokens'])*Decimal('3.75'))/Decimal(1000000)
    while True:
        waiting=False
        with ledger() as data:
            for item in data['attempts'].values():
                if item['status']=='reserved' and owner(item['pid'])!=item['owner_start']:
                    item['status']='interrupted_remote_cost_unknown_reserved'
            items=list(data['attempts'].values())
            total=sum(Decimal(str(a['accounted_usd'])) for a in items)
            evaluation=sum(Decimal(str(a['accounted_usd'])) for a in items if a.get('phase')=='evaluation')
            if data.get('halted'):raise BudgetExceeded(data['halted'])
            if total+upper<=Decimal('15') and evaluation+upper<=Decimal('7'):
                data['attempts'][call_id]={'phase':'evaluation','scope':question_id,'upper_bound_usd':float(upper),
                   'accounted_usd':float(upper),'status':'reserved','pid':os.getpid(),'owner_start':owner(os.getpid())}
                return float(upper)
            if any(a['status']=='reserved' for a in items):waiting=True
            else:raise BudgetExceeded(f'Evaluation budget reached: ${evaluation:.6f} accounted/reserved; $7 limit; $8 retained for judge/reserve')
        if waiting:time.sleep(.1)

def settle(call):
    response=call.get('response') or {}
    cost=(response.get('usage') or {}).get('cost')
    with ledger() as data:
        item=data['attempts'][call['call_id']]
        item.update(http_status=call['http_status'],generation_id=response.get('id'))
        if isinstance(cost,(int,float)) and cost>=0:
            item.update(accounted_usd=cost,reported_cost_usd=cost,status='reported')
            if cost>item['upper_bound_usd']:data['halted']='Reported charge exceeded conservative reservation; stop admissions'
        elif call['http_status'] in (400,401,402,403,404,422,429) and not response.get('id'):
            item.update(accounted_usd=0,status='rejected_before_generation')
        else:item['status']='remote_cost_unknown_reserved'
        if call['http_status'] in (401,402,403):data['halted']='Authentication, credit or access rejection; stop admissions'
        return copy.deepcopy(item)
