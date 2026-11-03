"""Foundry-only HTTP stages with response checkpoints and resumable successful calls."""
from __future__ import annotations
import base64, copy, math, struct, time
import common as c
from runtime import digest

class StageLog:
    def __init__(self,log,stage,persist):self.log,self.stage,self.persist=log,stage,persist;self.run_id=log.run_id
    def write(self,event,model,**details):
        if event=='api_request':self.stage['in_flight']={'call_id':details['call_id'],'request':details['request'],'started_at':c.utc_now()}
        if event in ('api_response','api_error'):
            if self.stage.get('api_calls'):
                self.stage['api_calls'][-1]['stage']=self.stage.get('category','answer')
            self.stage.pop('in_flight',None);self.persist()
        self.log.write(event,model,**details)
        if event=='api_request':self.persist()

class Client:
    def __init__(self,base,key,log,persist):self.base,self.key,self.log,self.persist=base,key,log,persist
    def call(self,stage,payload,model,qid,category,path='/openrouter/v1/chat/completions'):
        signature=digest([path,payload,self.base])
        if stage and stage.get('request_hash')!=signature:raise ValueError('Saved API stage uses a different request/configuration')
        stage.setdefault('request_hash',signature);stage.setdefault('api_calls',[]);stage['category']=category;stage['model_requested']=model
        if stage.pop('needs_retry',False):
            stage['replay_after_index']=len(stage['api_calls'])
            self.persist()
        # A received response is durable before parsing/selection; resume reuses it.
        for call in reversed(stage['api_calls'][stage.get('replay_after_index',0):]):
            if call.get('error') is None and call.get('kind')=='generation' and call.get('response'):
                return call['response']
        if stage.get('in_flight'):
            stage.setdefault('ambiguous_attempts',[]).append({**stage.pop('in_flight'),'status':'remote_acceptance_unknown_after_interruption'})
        stage['status']='running';self.persist()
        wrapped=StageLog(self.log,stage,self.persist)
        data=c.http_call(self.base,self.key,path,payload,model,wrapped,qid,stage['api_calls'])
        stage['status']='received' if data else 'error';self.persist()
        if data is None:raise RuntimeError('Foundry request failed; saved stage audit contains attempts')
        return data


def content(data):
    choice=(data.get('choices') or [{}])[0]
    if choice.get('finish_reason')=='length':raise ValueError('Truncated query generation; refusing incomplete retrieval plan')
    text=(choice.get('message') or {}).get('content')
    if not isinstance(text,str) or not text.strip():raise ValueError('Missing query generation text')
    return text.strip()


def embedding(data,dimensions):
    if data.get('model') not in ('openai/text-embedding-3-small','text-embedding-3-small'):raise ValueError('Query embedding model mismatch')
    rows=data.get('data') or []
    if len(rows)!=1 or rows[0].get('index',0)!=0:raise ValueError('Query embedding count/index mismatch')
    vector=rows[0].get('embedding')
    if isinstance(vector,str):
        raw=base64.b64decode(vector,validate=True)
        if len(raw)!=dimensions*4:raise ValueError('Query embedding byte count mismatch')
        vector=list(struct.unpack('<'+'f'*dimensions,raw))
    if not isinstance(vector,list) or len(vector)!=dimensions or any(not isinstance(v,(float,int)) or not math.isfinite(v) for v in vector) or sum(v*v for v in vector)<=0:raise ValueError('Invalid query vector')
    # Match stored corpus float32 precision.
    return list(struct.unpack('<'+'f'*dimensions,struct.pack('<'+'f'*dimensions,*vector)))


def metrics(stages):
    """Every HTTP attempt counts; unknown failed/ambiguous usage remains unknown."""
    total={name:0 for name in ('input_tokens','output_tokens','reasoning_tokens','visible_output_tokens','cached_input_tokens')}
    cost=0.;usage_complete=True;reasoning_complete=True;cache_complete=True;cost_complete=True;llm=0;embedding_calls=0;embedding_tokens=0;embedding_usage_complete=True;query_ms=0.;meta=0;http=0;retry=0;wait=0.;http_ms=0.;metadata_ms=0.;tools=0
    for stage in stages:
        calls=stage.get('api_calls',[]);gen=[x for x in calls if x['kind']=='generation'];retry+=max(0,len(gen)-1)
        if stage.get('ambiguous_attempts') or stage.get('in_flight'):
            usage_complete=False;cost_complete=False
            reasoning_complete=False;cache_complete=False
            if stage.get('category')=='embedding':embedding_usage_complete=False
        for call in calls:
            http+=1
            if call['kind']=='metadata':meta+=1;metadata_ms+=call['latency_ms'];continue
            if stage.get('category')=='embedding':embedding_calls+=1
            else:llm+=1;http_ms+=call['latency_ms']
            wait+=call.get('retry_wait_ms',0)
            if stage.get('category')=='query_generation':query_ms+=call['latency_ms']+call.get('retry_wait_ms',0)
            data=call.get('response') or {};usage=data.get('usage') or {}
            tools+=sum(len((choice.get('message') or {}).get('tool_calls') or []) for choice in data.get('choices',[]))
            if stage.get('category')=='embedding':
                inp=usage.get('prompt_tokens',usage.get('input_tokens',usage.get('total_tokens')))
                counts={'input_tokens':inp,'output_tokens':0,'reasoning_tokens':0,'visible_output_tokens':0,'cached_input_tokens':0} if isinstance(inp,int) else None
                if counts is not None:embedding_tokens+=inp
                else:embedding_usage_complete=False
            else:
                counts=c.token_usage(data)
                if (usage.get('completion_tokens_details') or {}).get('reasoning_tokens') is None:reasoning_complete=False
                if (usage.get('prompt_tokens_details') or {}).get('cached_tokens') is None:cache_complete=False
            if counts is None:usage_complete=False;reasoning_complete=False;cache_complete=False
            else:
                for name in total:total[name]+=counts.get(name,0)
            amount,_=c.reported_cost(data,call.get('generation_metadata'))
            if amount is None:cost_complete=False
            else:cost+=amount
    return {**{k:v if usage_complete else None for k,v in total.items()},
        'reasoning_tokens':total['reasoning_tokens'] if usage_complete and reasoning_complete else None,
        'visible_output_tokens':total['visible_output_tokens'] if usage_complete and reasoning_complete else None,
        'cached_input_tokens':total['cached_input_tokens'] if usage_complete and cache_complete else None,
        'reasoning_tokens_complete':reasoning_complete,'cached_input_tokens_complete':cache_complete,
        'total_tokens':total['input_tokens']+total['output_tokens'] if usage_complete else None,
        'observed_input_tokens':total['input_tokens'],'observed_output_tokens':total['output_tokens'],
        'api_cost_usd':cost if cost_complete else None,'observed_api_cost_usd':cost,'cost_complete':cost_complete,'usage_complete':usage_complete,
        'cost_kind':['reported_provider_cost'] if cost else [],'llm_api_calls':llm,'query_embedding_api_calls':embedding_calls,
        'metadata_api_calls':meta,'api_http_calls':http,'retry_count':retry,'llm_http_time_ms':http_ms,'retry_wait_ms':wait,'metadata_lookup_time_ms':metadata_ms,
        'query_embedding_input_tokens':embedding_tokens if embedding_usage_complete else None,'query_generation_time_ms':query_ms,
        'model_tool_calls_requested':tools,'model_tool_calls_executed':0}
