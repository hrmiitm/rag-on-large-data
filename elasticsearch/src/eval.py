#!/usr/bin/env python3
"""Run the Elasticsearch agent through Foundry/OpenRouter; no answer scoring.

Run: python elasticsearch/src/eval.py --model google/gemini-3.8-flash
Offline corpus check: python elasticsearch/src/eval.py --check-retrieval
"""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import random
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

from runtime import SRC, HOME, REPO, DB, database_lock, save, sha256
from search import RetrievalBatcher, TOOLS, SYSTEM
import budget
from jsonschema import Draft202012Validator

SCHEMA_VERSION = "rag-benchmark/1.0"
OPENROUTER_PATH = "/openrouter/v1"
METHOD = "elasticsearch-agentic"
ACTIVE_LOG = None
RECORD_VALIDATOR = Draft202012Validator(json.loads(Path(__file__).with_name("benchmark.schema.json").read_text()))


def environment(require_key=True):
    values = {}
    for file in (REPO / ".env.example", REPO / ".env"):
        if file.exists():
            for line in file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    name, value = line.removeprefix("export ").split("=", 1)
                    values[name.strip()] = value.strip().strip("\"'")
    values.update(os.environ)
    if values.get("LLM_PROVIDER", "llmfoundry") != "llmfoundry":
        raise ValueError("This evaluator uses LLM_PROVIDER=llmfoundry")
    base, key = values.get("LLMFOUNDRY_BASE_URL", "").rstrip("/"), values.get("LLMFOUNDRY_API_KEY", "")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Configure a credential-free HTTPS LLMFOUNDRY_BASE_URL")
    if not key and require_key:
        raise ValueError("Set LLMFOUNDRY_API_KEY in the repository .env or environment")
    return base, key, values


class RawLog:
    def __init__(self, key, run_id):
        self.key, self.run_id, self.lock = key, run_id, threading.Lock()
        self.file = (HOME / "raw-eval.log").open("a", buffering=1)

    def write(self, event, model, **details):
        record = {"time_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "run_id": self.run_id, "event": event, "model": model, **details}
        line = json.dumps(record, ensure_ascii=False)
        if self.key:
            line = line.replace(self.key, "[REDACTED]")
        with self.lock:
            self.file.write(line + "\n")
            self.file.flush()


def start_log(key,models,args,base):
    global ACTIVE_LOG
    log=RawLog(key,uuid.uuid4().hex)
    ACTIVE_LOG=log
    log.write("run_started",",".join(models),models=models,settings={**vars(args),"pricing_file":str(args.pricing_file)},base_url=base,scoring=False)
    return log



def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def safe_headers(headers):
    return {k.lower(): v for k, v in headers.items() if k.lower() in
            {"content-type", "date", "x-request-id", "request-id", "server-timing", "retry-after"}
            or k.lower().startswith(("x-ratelimit-", "x-openrouter-"))}


def clean_json(value, key):
    text = json.dumps(value, ensure_ascii=False)
    return json.loads(text.replace(key, "[REDACTED]")) if key else value


def token_usage(data, model=None):
    usage = data.get("usage") or {}
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if prompt is None or completion is None:
        return None
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
    return {"input_tokens": prompt, "output_tokens": completion,
            "visible_output_tokens": max(0, completion-reasoning), "reasoning_tokens": reasoning,
            "cached_input_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0}


def http_call(base, key, path, payload, model, logger, question_id, calls, kind="generation", attempts=3, stage=None):
    if not path.startswith(OPENROUTER_PATH + "/"):
        raise ValueError("Only the LLM Foundry OpenRouter route is allowed")
    # Requests are immutable audit snapshots; the conversation grows after each turn.
    payload=copy.deepcopy(payload)
    if kind=="generation": payload=budget.constrain(payload)
    for attempt in range(1, attempts+1):
        call = {"call_id": uuid.uuid4().hex, "run_id":logger.run_id, "kind": kind, "stage": stage or ("agent_step" if kind=="generation" else "generation_metadata"),
                "model_requested": model, "question_id": question_id, "attempt": attempt,
                "started_at": utc_now(), "request": {"method": "POST" if payload is not None else "GET", "url": base+path, "body": payload},
                "http_status": None, "response_headers": {}, "response": None, "raw_response": None, "error": None}
        started = time.perf_counter()
        if kind=="generation":
            try:
                call['budget_reservation_usd']=budget.reserve(call['call_id'],payload,question_id)
            except budget.BudgetExceeded as error:
                call.update(error={'type':'budget_admission_denied','message':str(error)},ended_at=utc_now(),latency_ms=0)
                calls.append(call)
                logger.write('budget_admission_denied',model,question_id=question_id,call=call)
                return None
        logger.write("api_request", model, question_id=question_id, call_id=call["call_id"], request=call["request"])
        retryable = False
        try:
            request = urllib.request.Request(base+path, data=json.dumps(payload).encode() if payload is not None else None,
                        headers={"Authorization": "Bearer "+key, "Content-Type": "application/json", "Cache-Control":"no-cache"})
            with urllib.request.urlopen(request, timeout=240 if kind=="generation" else 20) as response:
                raw = response.read().decode("utf-8")
                call.update(http_status=response.status, response_headers=safe_headers(response.headers), raw_response=raw)
                call["response"] = json.loads(raw)
                if call["response"].get("error"):
                    call["error"] = {"type": "provider_error", "details": call["response"]["error"]}
                    retryable = int(call["response"]["error"].get("code", 0) or 0) in (429,500,502,503,504)
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            call.update(http_status=error.code, response_headers=safe_headers(error.headers or {}), raw_response=raw,
                        error={"type":"http_error", "message": str(error)})
            try: call["response"] = json.loads(raw)
            except ValueError: pass
            # Generation statistics are eventually consistent. Repeating 404s
            # can trip the gateway's too_many_errors circuit breaker. Metadata
            # 404/429 is deferred rather than retried alongside model calls.
            retryable = error.code in ((500,502,503,504) if kind=="metadata" else (429,500,502,503,504))
        except Exception as error:
            call["error"] = {"type":type(error).__name__, "message":str(error)}
            retryable = isinstance(error, (TimeoutError,urllib.error.URLError))
        call.update(ended_at=utc_now(), latency_ms=(time.perf_counter()-started)*1000)
        if kind=="generation": call["budget_receipt"]=budget.settle(call)
        call = clean_json(call, key)
        calls.append(call)
        logger.write("api_response" if call["error"] is None else "api_error", model, question_id=question_id, call=call)
        if call["error"] is None:
            return call["response"]
        if not retryable or attempt==attempts:
            return None
        delay = min(30, 2**attempt) if kind=="generation" else attempt
        try: delay=min(60,max(delay,float(call["response_headers"].get("retry-after",0))))
        except (ValueError,TypeError): pass
        call["retry_wait_ms"] = delay*1000
        logger.write("retry_wait", model, question_id=question_id, call_id=call["call_id"], seconds=delay)
        time.sleep(delay)


def reported_cost(data, metadata=None):
    usage = data.get("usage") or {}
    value = usage.get("cost")
    if isinstance(value,(int,float)) and value>=0:
        return value, "openrouter_usage_cost_usd"
    value = ((metadata or {}).get("data") or {}).get("total_cost")
    if isinstance(value,(int,float)) and value>=0:
        return value, "openrouter_generation_total_cost_usd"
    return None, None


def call_metrics(calls, price):
    generation = [c for c in calls if c["kind"]=="generation" and (c.get('error') or {}).get('type')!='budget_admission_denied']
    metadata = [c for c in calls if c["kind"]=="metadata"]
    totals = {k:0 for k in ("input_tokens","output_tokens","visible_output_tokens","reasoning_tokens","cached_input_tokens")}
    tokens_complete = True; cost_complete = True; cost = 0.; cost_kinds=set()
    for call in generation:
        data = call.get("response") or {}
        counts = token_usage(data)
        if counts is None:
            tokens_complete = False
        else:
            for k,v in counts.items(): totals[k]+=v
        value, kind = reported_cost(data, call.get("generation_metadata"))
        if value is None and counts and price and datetime.date.today().isoformat()<=price.get("valid_through","9999"):
            cached=counts["cached_input_tokens"]
            value=((counts["input_tokens"]-cached)*price["input_usd_per_million"]+cached*price.get("cached_input_usd_per_million",price["input_usd_per_million"])+counts["output_tokens"]*price["output_usd_per_million"])/1_000_000
            kind=price["cost_kind"]
        if value is None:
            cost_complete=False
        else:
            cost+=value; cost_kinds.add(kind)
    return {**{k:v if tokens_complete else None for k,v in totals.items()},
            "observed_input_tokens":totals["input_tokens"], "observed_output_tokens":totals["output_tokens"],
            "api_cost_usd":cost if cost_complete else None, "observed_api_cost_usd":cost,
            "cost_kind":sorted(cost_kinds), "usage_complete":tokens_complete,"cost_complete":cost_complete,
            "llm_api_calls":len(generation), "metadata_api_calls":len(metadata), "api_http_calls":len(generation)+len(metadata),
            "budget_admissions_denied":sum((c.get('error') or {}).get('type')=='budget_admission_denied' for c in calls),
            "retry_count":sum(c.get("attempt",1)>1 for c in generation), "llm_http_time_ms":sum(c["latency_ms"] for c in generation),
            "retry_wait_ms":sum(c.get("retry_wait_ms",0) for c in generation),
            "metadata_lookup_time_ms":sum(c["latency_ms"]+c.get("retry_wait_ms",0) for c in metadata),
            "usage_observed_calls":sum(token_usage(c.get("response") or {}) is not None for c in generation),
            "model_tool_calls_requested":sum(len(choice.get("message",{}).get("tool_calls") or []) for c in generation for choice in (c.get("response") or {}).get("choices",[])),
            "model_tool_calls_executed":0}


SERIALIZED = {}

def write_answers(records, questions):
    target = HOME / "q-a.jsonl"
    tmp = target.with_suffix(".tmp")
    with tmp.open("w") as output:
        for q in questions:
            if q["id"] in records:
                row=records[q["id"]]
                version=row.get('updated_at')
                cached=SERIALIZED.get(q['id'])
                if cached is None or cached[0]!=version:
                    RECORD_VALIDATOR.validate(row)
                    cached=(version,json.dumps(row,ensure_ascii=False)+'\n')
                    SERIALIZED[q['id']]=cached
                output.write(cached[1])
        output.flush()
        os.fsync(output.fileno())
    tmp.replace(target)


def chunk_id(hit):
    identity = [hit["document_id"], hit["source_hash"], hit["start_char"], hit["end_char"]]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def recorded_chunk(hit, rank):
    return {"chunk_id":chunk_id(hit), "document_id":hit["document_id"], "rank":rank,
            "text":hit["body"], "scores":hit.get("scores", {}),
            "source":{"file":hit["file"], "line":hit["line"], "hash":hit["source_hash"],
                "archive_shard":hit["shard"], "section":hit["section"], "section_start_char":hit["section_start"],
                "section_end_char":hit["section_end"], "start_char":hit["start_char"], "end_char":hit["end_char"],
                "filing_date":hit["filing_date"]}, "metadata":{"title":hit["title"], "elasticsearch_id":hit.get("elasticsearch_id"), "company":hit.get("company"), "form":hit.get("form")}}


def parse_citations(text,citation_map):
    markers=set()
    for group in re.findall(r"\[([\d\s,;–-]+)\]",text):
        for item in re.split(r"[,;]",group):
            item=item.strip()
            span=re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)",item)
            if span:
                first,last=map(int,span.groups())
                if 0<=last-first<=1000:markers.update(range(first,last+1))
            elif item.isdigit():markers.add(int(item))
    return [{"marker":n,"chunk_id":citation_map.get(str(n))} for n in sorted(markers)]


def empty_retrieval():
    return {"queries":[],"chunks":[],"metrics":{}}


def empty_context():
    return {"text":"","chunk_ids":[],"citation_map":{}}


def new_question(q, models, signature, config, log, selection):
    return {"schema_version":SCHEMA_VERSION,"method":METHOD,"run_id":log.run_id,
        "question_id":q["id"],"question":q["question"],"as_of":q["as_of"],"status":"pending",
        "configuration_hash":signature,"requested_models":models,"retrieval":empty_retrieval(),
        "context":empty_context(),"answers":{},"metrics":{},"errors":[],"trace":[],
        "provenance":{"corpus_sha256":config["source_sha256"],"index_config":config,
            "index_config_sha256":hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),
            "questions_sha256":config["questions_sha256"],"eval_code_sha256":sha256(Path(__file__)),
            "gateway":"llmfoundry","router":"openrouter","selection":selection,
            "agent_implementation":"Bounded Elasticsearch tool agent; checkpoint/writer adapted from local Lume agent evaluator",
            "retriever":"elasticsearch_bm25_cached_question_cosine_application_rrf","retrieval_isolated":True},
        "created_at":utc_now(),"updated_at":utc_now()}


def initial_answer(q, model, args, base, log, previous=None):
    result={"model_requested":model,"model_returned":None,"provider":None,
        "gateway":"llmfoundry","router":"openrouter","base_url":base,"run_id":log.run_id,
        "generation_id":None,"generation_ids":[],"final_answer":None,"status":"pending",
        "api_calls":[],"errors":[],"metrics":{},"metadata_status":"pending",
        "thinking_level":args.thinking_level,"max_output_tokens":args.max_output_tokens,
        "retrieval":empty_retrieval(),"context":empty_context(),"tool_executions":[],"trace":[],
        "agent_state":{"messages":[{"role":"system","content":SYSTEM},
            {"role":"user","content":f"As of: {q['as_of']}\nQuestion: {q['question']}"}],
            "steps":0,"search_attempts":0,"pending_tools":[],"elapsed_seconds":0.,
            "next_action":"model","context_tokens":0,"contexts":[]}}
    if previous:
        result["attempt_history"]=[*previous.get("attempt_history",[]),
            {k:v for k,v in previous.items() if k!="attempt_history"}]
    return result


def recompute_answer(result, args):
    """Aggregate every model turn/retry without confusing turns with retries."""
    tools=result["tool_executions"]
    queries=result["retrieval"]["queries"]
    prior=result.get("metrics",{})
    calls=call_metrics(result["api_calls"],args.prices.get(result["model_requested"]))
    state=result["agent_state"]
    searches=[t for t in tools if t["name"] in ("search_filings", "read_passages") and t["status"]!="rejected"]
    def database_count(field):
        counts=[t.get("metrics",{}).get(field) for t in searches]
        return sum(counts) if all(c is not None for c in counts) else None
    result["metrics"]={**prior,**calls,
        "total_time_seconds":state["elapsed_seconds"],
        "answer_ready_time_seconds":state["elapsed_seconds"],
        "llm_generation_time_ms":calls["llm_http_time_ms"]+calls["retry_wait_ms"],
        "query_embedding_api_calls":0,"elasticsearch_search_concurrency":args.batch_size,
        "retrieval_time_ms":sum(t.get("metrics",{}).get("retrieval_time_ms",0) for t in tools),
        "retrieval_queue_time_ms":sum(t.get("queue_time_ms",0) for t in tools),
        "tool_calls":len(tools),"retrieval_tool_calls":sum(t["name"] in ("search_filings", "read_passages") for t in tools),
        "model_tool_calls_executed":sum(t["status"]!="rejected" for t in tools),
        "tool_calls_succeeded":sum(t["status"]=="ok" for t in tools),
        "tool_calls_failed":sum(t["status"]=="error" for t in tools),
        "tool_calls_rejected":sum(t["status"]=="rejected" for t in tools),
        "db_queries":database_count("db_queries"),
        "retrieval_db_queries":database_count("retrieval_db_queries"),
        "metadata_db_queries":database_count("metadata_db_queries"),
        "db_queries_complete":database_count("db_queries") is not None,
        "documents_retrieved":sum(q["returned_k"] for q in queries),
        "unique_chunks_retrieved":len(result["retrieval"]["chunks"]),
        "unique_filings_retrieved":len({c["document_id"] for c in result["retrieval"]["chunks"]}),
        "chunks_provided_to_llm":len(result["context"]["chunk_ids"]),
        "context_tokens":state["context_tokens"],"agent_steps":state["steps"],
        "retrieval_peak_rss_mb":None,
        "elasticsearch_peak_rss_mb":None,
        "time_to_first_token_ms":None,"time_to_first_token_status":"not_measured_non_streaming"}
    result["retrieval"]["metrics"]={k:result["metrics"][k] for k in (
        "retrieval_time_ms","retrieval_queue_time_ms","tool_calls","retrieval_tool_calls","db_queries",
        "retrieval_db_queries","metadata_db_queries","documents_retrieved","unique_chunks_retrieved",
        "unique_filings_retrieved","chunks_provided_to_llm","retrieval_peak_rss_mb")}
    result["citations"]=parse_citations(result.get("final_answer") or "",result["context"]["citation_map"])


def update_record(record, models):
    record["requested_models"]=list(dict.fromkeys([*record["requested_models"],*models]))
    values=[record["answers"].get(m) for m in record["requested_models"]]
    states=[v.get("status","pending") if v else "pending" for v in values]
    record["status"]=("pending" if "pending" in states else "error" if all(s=="error" for s in states)
        else "partial" if "error" in states else "truncated" if "truncated" in states else "completed")
    active=[v for v in values if v]
    chunks={}; queries=[]
    for result in active:
        queries.extend(result["retrieval"]["queries"])
        for c in result["retrieval"]["chunks"]:
            if c["chunk_id"] not in chunks: chunks[c["chunk_id"]]=json.loads(json.dumps(c))
            else: chunks[c["chunk_id"]]["occurrences"].extend(c["occurrences"])
    record["retrieval"]={"queries":queries,"chunks":list(chunks.values()),"metrics":{}}
    # Context/citation numbering belongs to each model's independent conversation.
    # For one model this is identical to the BM25 top-level contract.
    record["context"]=json.loads(json.dumps(active[0]["context"])) if active else empty_context()
    record["context"]["by_model"]={r["model_requested"]:r["context"] for r in active}
    metrics={}
    sum_fields=("retrieval_time_ms","retrieval_queue_time_ms","llm_generation_time_ms","api_cost_usd",
        "input_tokens","output_tokens","visible_output_tokens","reasoning_tokens","cached_input_tokens",
        "llm_api_calls","tool_calls","db_queries","documents_retrieved","metadata_api_calls","api_http_calls",
        "retry_count","llm_http_time_ms","retry_wait_ms","metadata_lookup_time_ms","observed_api_cost_usd",
        "observed_input_tokens","observed_output_tokens","usage_observed_calls","model_tool_calls_requested",
        "model_tool_calls_executed","tool_calls_succeeded","tool_calls_failed","tool_calls_rejected",
        "retrieval_tool_calls","retrieval_db_queries","metadata_db_queries","agent_steps")
    for key in sum_fields:
        counts=[v.get("metrics",{}).get(key) for v in values if v]
        metrics[key]=sum(counts) if counts and all(c is not None for c in counts) else None
    # Independent models for one question execute sequentially; their active times add.
    metrics.update(total_time_seconds=sum(v["metrics"].get("total_time_seconds",0) for v in active),
        unique_chunks_retrieved=len(chunks),unique_filings_retrieved=len({c["document_id"] for c in chunks.values()}),
        chunks_provided_to_llm=sum(len(v["context"]["chunk_ids"]) for v in active),
        retrieval_peak_rss_mb=None,
        cost_complete=all(v["metrics"].get("cost_complete",False) for v in active),
        usage_complete=all(v["metrics"].get("usage_complete",False) for v in active),
        cost_kind=sorted({k for v in active for k in v["metrics"].get("cost_kind",[])}))
    record["metrics"]=metrics
    record["retrieval"]["metrics"]={k:metrics[k] for k in (
        "retrieval_time_ms","tool_calls","db_queries","documents_retrieved","unique_chunks_retrieved",
        "unique_filings_retrieved","chunks_provided_to_llm","retrieval_peak_rss_mb")}
    record["errors"]=[{"model":r["model_requested"],**e} for r in active for e in r["errors"]]
    record["trace"]=[{"model":r["model_requested"],**event} for r in active for event in r["trace"]]
    record["provenance"]["record_writer_code_sha256"]=sha256(Path(__file__))
    record["updated_at"]=utc_now()


def tool_result(q, result, tc, args, config, log, retrieval_dispatcher=None):
    """Execute a bounded read-only tool. Model input never selects paths or filters."""
    state=result["agent_state"]; model=result["model_requested"]
    name=(tc.get("function") or {}).get("name")
    event={"tool_call_id":tc.get("id"),"name":name,"started_at":utc_now(),
        "arguments":(tc.get("function") or {}).get("arguments"),"status":"rejected","metrics":{}}
    started=time.perf_counter()
    try:
        spec=next((t["function"]["parameters"] for t in TOOLS if t["function"]["name"]==name),None)
        if spec is None: raise ValueError("Unknown tool; only search_filings, read_passages and report_missing_evidence are allowed")
        raw=event["arguments"]
        values=json.loads(raw) if isinstance(raw,str) else raw
        Draft202012Validator(spec).validate(values)
        event["arguments_parsed"]=values
        if name=="report_missing_evidence":
            event["status"]="ok"
            response={"guidance":"Check the company, period, synonyms and exact financial labels. Try a different concise query if the search budget allows; otherwise state the missing evidence.","reason":values["reason"]}
        else:
            if retrieval_dispatcher is None: raise ValueError('Elasticsearch dispatcher required')
            event['status']='error'
            query_id=f"{model}:{result['run_id']}:query-{len(result['retrieval']['queries'])+1}"
            if name=='search_filings':
                if not values['query'].strip():raise ValueError('Query must contain text')
                if state['search_attempts']>=args.max_searches:raise ValueError('Search budget exhausted')
                state['search_attempts']+=1
                text=values['query']
                query={'query_id':query_id,'text':text,'filters':{'filing_date_lte':q['as_of'],
                    **{k:values[k] for k in ('company','form') if k in values}},'stage':'agent_search',
                    'model':model,'tool_call_id':tc.get('id'),'top_k':args.k,'returned_k':0,'mode':values.get('mode','hybrid')}
                result['retrieval']['queries'].append(query)
                hits,metrics=retrieval_dispatcher.search(q,text,model,event,values)
            elif name=='read_passages':
                known={c['metadata']['elasticsearch_id']:c for c in result['retrieval']['chunks']}
                anchors=[]
                for cid in values['passage_ids']:
                    if cid not in known:raise ValueError('Read only previously retrieved passage IDs')
                    c=known[cid];anchors.append({'document_id':c['document_id'],'line':c['source']['line']})
                text='Read neighbouring passages: '+', '.join(values['passage_ids'])
                query={'query_id':query_id,'text':text,'filters':{'filing_date_lte':q['as_of']},'stage':'passage_expansion',
                    'model':model,'tool_call_id':tc.get('id'),'top_k':6,'returned_k':0}
                result['retrieval']['queries'].append(query)
                hits,metrics=retrieval_dispatcher.read(q,anchors,model,event)
            else: raise ValueError('Unknown tool')
            query.update(returned_k=len(hits),executed_text=text)
            if 'candidate_rankings' in metrics:query['candidate_rankings']=metrics.pop('candidate_rankings')
            event["metrics"]=metrics
            existing={c["chunk_id"]:c for c in result["retrieval"]["chunks"]}
            selected=[]; used=0
            import tiktoken
            enc=tiktoken.get_encoding("cl100k_base")
            for rank, hit in enumerate(hits,1):
                cid=chunk_id(hit)
                occurrence={"query_id":query_id,"rank":rank,"score":hit["retrieval_score"],"scores":hit.get("scores",{}),"model":model}
                if cid in existing: existing[cid]["occurrences"].append(occurrence)
                else:
                    c=recorded_chunk(hit,rank); c["occurrences"]=[occurrence]
                    result["retrieval"]["chunks"].append(c); existing[cid]=c
                if cid in result["context"]["chunk_ids"]:
                    selected.append({"chunk_id":cid,"already_provided":True,
                        "citation":result["context"]["chunk_ids"].index(cid)+1,"passage_id":hit["elasticsearch_id"]})
                    continue
                marker=len(result["context"]["chunk_ids"])+1
                block=f"[{marker}] {hit['title']} | offsets={hit['start_char']}:{hit['end_char']}\n{hit['body']}"
                size=len(enc.encode_ordinary(block))
                if state["context_tokens"]+size>args.context_tokens: continue
                state["context_tokens"]+=size; used+=size
                result["context"]["chunk_ids"].append(cid)
                result["context"]["citation_map"][str(marker)]=cid
                result["context"]["text"]+=("\n\n" if result["context"]["text"] else "")+block
                selected.append({"chunk_id":cid,"citation":marker,"passage_id":hit["elasticsearch_id"],"passage":block})
            response={"query_id":query_id,"retrieved_count":len(hits),"passages":selected,
                "context_tokens_remaining":args.context_tokens-state["context_tokens"],
                "searches_remaining":args.max_searches-state["search_attempts"]}
            event.update(status="ok",query_id=query_id,chunk_ids=[chunk_id(h) for h in hits],context_tokens_added=used)
    except Exception as error:
        if name in ("search_filings","read_passages") and event["status"]=="error":
            event["metrics"]["retrieval_time_ms"]=(time.perf_counter()-started)*1000-event.get("queue_time_ms",0)
        response={"error":{"type":type(error).__name__,"message":str(error)},
            "guidance":"Correct tool arguments or answer from evidence already provided; do not invent facts."}
        event["error"]=response["error"]
        result["errors"].append({"stage":"tool","tool_call_id":tc.get("id"),**response["error"]})
    event.update(ended_at=utc_now(),latency_ms=(time.perf_counter()-started)*1000,response=response)
    result["tool_executions"].append(event)
    result["trace"].append({"event":"tool_executed","stage":"retrieve","tool_call_id":tc.get("id"),"status":event["status"]})
    log.write("tool_result",model,question_id=q["id"],tool=event)
    return {"role":"tool","tool_call_id":tc.get("id"),"content":json.dumps(response,ensure_ascii=False)}


def run_agent(q, result, args, config, base, key, log, checkpoint, stop_event=None,
              retrieval_dispatcher=None):
    state=result["agent_state"]; started=time.perf_counter(); carried=state["elapsed_seconds"]
    model=result["model_requested"]
    os.environ["TIKTOKEN_CACHE_DIR"]=str(SRC/".cache"/"tiktoken")
    def persist():
        state["elapsed_seconds"]=carried+time.perf_counter()-started
        recompute_answer(result,args)
        checkpoint()
    try:
        while state["steps"]<args.max_steps or state["pending_tools"]:
            if stop_event is not None and stop_event.is_set():
                persist()
                return
            if state["pending_tools"]:
                # Checkpoint after EACH tool so a later tool failure cannot lose previous results.
                tc=state["pending_tools"][0]
                already=next((t for t in result["tool_executions"] if t["tool_call_id"]==tc.get("id")),None)
                if already:
                    msg={"role":"tool","tool_call_id":tc.get("id"),"content":json.dumps(already["response"])}
                elif len(result["tool_executions"])>=args.max_tool_calls:
                    event={"tool_call_id":tc.get("id"),"name":(tc.get("function") or {}).get("name"),
                        "status":"rejected","metrics":{},"response":{"error":"Total tool budget exhausted; provide your final answer."}}
                    result["tool_executions"].append(event)
                    msg={"role":"tool","tool_call_id":tc.get("id"),"content":json.dumps(event["response"])}
                    log.write("tool_rejected",model,question_id=q["id"],tool=event)
                else: msg=tool_result(q,result,tc,args,config,log,retrieval_dispatcher=retrieval_dispatcher)
                state["messages"].append(msg); state["pending_tools"].pop(0)
                persist(); continue
            last=state["steps"]==args.max_steps-1
            no_more=(last or state["search_attempts"]>=args.max_searches or
                len(result["tool_executions"])>=args.max_tool_calls or state["context_tokens"]>=args.context_tokens-1000)
            if last:
                state["messages"].append({"role":"user","content":"Final turn: answer from the evidence already retrieved. State any missing evidence. Do not request tools."})
            choice="none" if no_more else {"type":"function","function":{"name":"search_filings"}} if state["search_attempts"]==0 else "auto"
            payload={"model":model,"messages":state["messages"],"tools":TOOLS,"tool_choice":choice,
                "reasoning":{"effort":args.thinking_level.lower()},"max_tokens":args.max_output_tokens,
                "usage":{"include":True},"stream":False}
            before=len(result["api_calls"])
            data=http_call(base,key,OPENROUTER_PATH+"/chat/completions",payload,model,log,q["id"],
                result["api_calls"],stage=f"agent_step_{state['steps']+1}")
            state["steps"]+=1
            for call in result["api_calls"][before:]:
                call["context_chunk_ids"]=list(result["context"]["chunk_ids"])
                if call["error"]: result["errors"].append({"call_id":call["call_id"],"stage":call["stage"],**call["error"]})
            result["trace"].append({"event":"agent_step_completed","stage":"agent","step":state["steps"],
                "api_call_ids":[c["call_id"] for c in result["api_calls"][before:]],"tool_choice":choice})
            if not data:
                result["status"]="error"; persist(); return
            selected=(data.get("choices") or [{}])[0]; message=selected.get("message") or {}
            result.update(model_returned=data.get("model"),provider=data.get("provider"),
                generation_id=data.get("id"),usage=data.get("usage"),message=message,
                finish_reason=selected.get("finish_reason"),native_finish_reason=selected.get("native_finish_reason"))
            if data.get("id"): result["generation_ids"].append(data["id"])
            tool_calls=message.get("tool_calls") or []
            # Preserve opaque reasoning_details (including Gemini thought signatures) exactly.
            state["messages"].append({"role":"assistant",**{k:v for k,v in message.items()
                if k in ("content","tool_calls","reasoning","reasoning_details") and v is not None}})
            if tool_calls:
                if len(tool_calls)>32 or any(not t.get("id") for t in tool_calls):
                    raise ValueError("Malformed or excessive model tool calls")
                state["pending_tools"]=copy.deepcopy(tool_calls)
                persist(); continue
            text=message.get("content")
            if isinstance(text,list): text="\n".join(p.get("text","") for p in text if isinstance(p,dict))
            if not isinstance(text,str) or not text.strip():
                result["status"]="error"
                result["errors"].append({"stage":"agent","type":"missing_final_answer","message":"Model returned neither tools nor a final answer"})
            elif state["search_attempts"]==0:
                result["status"]="error"
                result["errors"].append({"stage":"agent","type":"missing_search","message":"Model answered without the required search"})
            else:
                result["final_answer"]=text
                result["status"]="truncated" if selected.get("finish_reason")=="length" else "ok"
            persist(); return
        result["status"]="error"
        result["errors"].append({"stage":"agent","type":"step_budget_exhausted","message":"No final answer within the bounded turn budget"})
    except Exception as error:
        result["status"]="error"
        result["errors"].append({"stage":"agent","type":type(error).__name__,"message":str(error).replace(key,"[REDACTED]")})
        log.write("agent_error",model,question_id=q["id"],error=str(error),traceback=traceback.format_exc())
    persist()


def run_questions(questions, all_questions, records, models, signature, config,
                  log, selection, args, base, key):
    """Keep question workers full; only immutable snapshots enter the shared writer."""
    write_lock=threading.Lock()
    stop_event=threading.Event()
    jobs=[]
    for q in questions:
        row=copy.deepcopy(records.get(q["id"]) or new_question(q,models,signature,config,log,selection))
        if row["question"]!=q["question"] or row["as_of"]!=q["as_of"]:
            raise RuntimeError("Saved question differs from the input")
        pending=[]
        for model in models:
            prior=row["answers"].get(model)
            if prior and prior["base_url"]!=base:
                raise RuntimeError("Saved answer gateway differs")
            if prior and prior["status"] in ("ok","truncated"):
                continue
            if not prior or prior["status"]!="pending":
                row["answers"][model]=initial_answer(q,model,args,base,log,prior)
            pending.append(model)
        if pending:
            row["provenance"]["execution"]={"run_id":log.run_id,
                "configured_question_concurrency":args.batch_size,
                "elasticsearch_search_concurrency":args.batch_size,"scheduling":"continuous_thread_pool",
                "retrieval_batch_max_queries":1,
                "retrieval_batch_wait_ms":getattr(args,"search_batch_wait_ms",250),
                "models_scheduled":pending}
            update_record(row,models)
            records[q["id"]]=copy.deepcopy(row)
            jobs.append((q,row,pending))
    # Publish every scheduled question before any worker begins mutating its own row.
    write_answers(records,all_questions)
    log.write("questions_scheduled",",".join(models),question_ids=[q["id"] for q,_,_ in jobs],
              configured_question_concurrency=args.batch_size,elasticsearch_search_concurrency=args.batch_size,
              scheduling="continuous_thread_pool",retrieval_batch_max_queries=1)
    print(f"Running {len(jobs)} questions with up to {args.batch_size} concurrent agents; "
          "Elasticsearch tools execute concurrently",flush=True)
    dispatcher=RetrievalBatcher(config,args.k,log,args.batch_size,getattr(args,"search_batch_wait_ms",250))
    def checkpoint(row):
        with write_lock:
            update_record(row,models)
            records[row["question_id"]]=copy.deepcopy(row)
            write_answers(records,all_questions)
    def work(q,row,pending):
        # Each question owns its row. Its models are sequential; other questions overlap.
        for model in pending:
            if stop_event.is_set():
                return
            try:
                row["answers"][model]["execution"]={"run_id":log.run_id,
                    "configured_question_concurrency":args.batch_size,"elasticsearch_search_concurrency":args.batch_size,
                    "retrieval_batch_max_queries":1,
                    "retrieval_batch_wait_ms":getattr(args,"search_batch_wait_ms",250)}
                log.write("question_model_started",model,question_id=q["id"],
                          configured_question_concurrency=args.batch_size)
                run_agent(q,row["answers"][model],args,config,base,key,log,
                          lambda:checkpoint(row),stop_event=stop_event,retrieval_dispatcher=dispatcher)
                if any(c.get('http_status') in (401,402,403) or (c.get('error') or {}).get('type')=='budget_admission_denied'
                       for c in row['answers'][model]['api_calls']):
                    stop_event.set()
                log.write("question_model_finished",model,question_id=q["id"],
                          status=row["answers"][model]["status"])
                print(f"{q['id']} {model}: {row['answers'][model]['status']}",flush=True)
            except BaseException:
                stop_event.set()
                raise
    pool=ThreadPoolExecutor(max_workers=args.batch_size)
    futures=[]
    try:
        futures=[pool.submit(work,q,row,pending) for q,row,pending in jobs]
        for future in as_completed(futures):
            future.result()
    except BaseException:
        # Do not start paid work for queued questions after interruption/fatal write errors.
        stop_event.set()
        for future in futures:
            future.cancel()
        pool.shutdown(wait=True,cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
    finally:
        dispatcher.close()


def collect_metadata(records, questions, models, args, base, key, log, all_questions):
    refreshed=0
    for q in questions:
        row=records.get(q["id"])
        if not row: continue
        for model in models:
            result=row["answers"].get(model)
            if not result: continue
            # Every paid turn has its OWN generation metadata, not just the last answer turn.
            generations=[c for c in result["api_calls"] if c["kind"]=="generation" and
                (c.get("response") or {}).get("id") and not c.get("generation_metadata")]
            for generation in generations:
                gid=generation["response"]["id"]
                data=http_call(base,key,OPENROUTER_PATH+"/generation?"+urllib.parse.urlencode({"id":gid}),
                    None,model,log,q["id"],result["api_calls"],kind="metadata",attempts=args.metadata_attempts)
                latest=result["api_calls"][-1]
                if data:
                    generation["generation_metadata"]=data; refreshed+=1
                    if gid==result.get("generation_id"):
                        result["generation_metadata"]=data
                        result["provider"]=result.get("provider") or (data.get("data") or {}).get("provider_name")
                elif latest.get("error"):
                    result["errors"].append({"call_id":latest["call_id"],"stage":"generation_metadata",**latest["error"]})
                all_gen=[c for c in result["api_calls"] if c["kind"]=="generation" and (c.get("response") or {}).get("id")]
                result["metadata_status"]="available" if all(c.get("generation_metadata") for c in all_gen) else "pending"
                result["metadata_last_checked_at"]=utc_now()
                recompute_answer(result,args); update_record(row,models); write_answers(records,all_questions)
                if latest.get("http_status")==429:
                    log.write("metadata_collection_deferred",model,reason="rate_limited",llm_api_calls=0)
                    return refreshed
                time.sleep(1)
    return refreshed


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model",action="append")
    parser.add_argument("--thinking-level",choices=("LOW","MEDIUM","HIGH"),default="HIGH")
    parser.add_argument("--batch-size","--concurrency",type=int,default=5,
        help="Concurrent question agents, 1..10 (default 5)")
    parser.add_argument("--search-batch-wait-ms",type=int,default=0,
        help="Compatibility setting; Elasticsearch uses direct concurrent searches")
    parser.add_argument("--k",type=int,default=5,help="Chunks per model-issued search")
    parser.add_argument("--context-tokens",type=int,default=16000,help="Cumulative evidence-token budget per question/model")
    parser.add_argument("--max-output-tokens",type=int,default=8192,help="Completion budget per model turn, includes reasoning")
    parser.add_argument("--max-steps",type=int,default=6,help="Max logical model turns including the final answer")
    parser.add_argument("--max-searches",type=int,default=6)
    parser.add_argument("--max-tool-calls",type=int,default=8)
    parser.add_argument("--sample-size",type=int)
    parser.add_argument("--seed",type=int)
    parser.add_argument("--fresh",action="store_true")
    parser.add_argument("--check-retrieval",action="store_true")
    parser.add_argument("--check-endpoints",action="store_true",help="Tiny forced tool-call and tool-result continuation probe")
    parser.add_argument("--refresh-metadata",action="store_true")
    parser.add_argument("--metadata-attempts",type=int,default=2)
    parser.add_argument("--pricing-file",type=Path,default=SRC/"pricing.json")
    parser.add_argument("--defer-metadata",action="store_true")
    parser.add_argument("--resume-after-access-restored",action="store_true",help="Clear only a saved access halt after the user restores the configured route")
    args=parser.parse_args(argv)
    if not 1<=args.batch_size<=10 or not 1<=args.k<=20 or not 2<=args.max_steps<=10 or not 1<=args.max_searches<=10 or not 1<=args.max_tool_calls<=16:
        parser.error("Require concurrency 1..10, k 1..20, steps 2..10, searches 1..10 and tools 1..16")
    if not 1000<=args.context_tokens<=24000 or not 128<=args.max_output_tokens<=8192 or not 1<=args.metadata_attempts<=5:
        parser.error("Require context 1000..24000, output 128..8192 and metadata attempts 1..5")
    if not 0<=args.search_batch_wait_ms<=1000:
        parser.error("Require search batch wait 0..1000 ms")
    if args.sample_size is not None and not 1<=args.sample_size<=50: parser.error("Sample size must be 1..50")
    modes=sum((args.check_retrieval,args.check_endpoints,args.refresh_metadata))
    if modes>1 or (args.fresh and modes): parser.error("Choose one validation mode; --fresh is only for evaluation")
    args.prices=json.loads(args.pricing_file.read_text()) if args.pricing_file.exists() else {}
    base,key,env=environment(require_key=not args.check_retrieval)
    models=list(dict.fromkeys(m.strip() for m in (args.model or env.get("RAG_MODELS","google/gemini-3.8-flash").split(",")) if m.strip()))
    if not models or any(not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.:-]+",m) for m in models):
        parser.error("Use exact OpenRouter owner/model IDs")
    if models!=[budget.MODEL]:parser.error('This $15 campaign admits only '+budget.MODEL)
    DB.mkdir(exist_ok=True)
    with database_lock():
        if args.fresh:
            (HOME/"q-a.jsonl").write_text(""); (HOME/"raw-eval.log").write_text("")
        log=start_log(key,models,args,base)
        if args.check_endpoints:
            raise ValueError("Use offline tests and --check-retrieval; no extra paid probes")
        from runtime import evaluation_config
        config=evaluation_config()
        qpath=SRC/"questions.jsonl"
        if sha256(qpath)!=config["questions_sha256"]: raise RuntimeError("Question copy changed since ingestion")
        all_questions=[json.loads(s) for s in qpath.read_text().splitlines() if s.strip()]
        if len(all_questions)!=50 or len({q["id"] for q in all_questions})!=50 or any(set(q)!={"id","question","as_of"} for q in all_questions):
            raise RuntimeError("Expected 50 question-only records; reference fields are forbidden")
        questions=all_questions
        if args.sample_size:
            args.seed=args.seed if args.seed is not None else random.SystemRandom().getrandbits(32)
            chosen={q["id"] for q in random.Random(args.seed).sample(questions,args.sample_size)}
            questions=[q for q in questions if q["id"] in chosen]
        selection={"pool_size":50,"sample_size":len(questions),"seed":args.seed,"question_ids":[q["id"] for q in questions]}
        log.write("questions_selected",",".join(models),selection=selection)
        print(f"Selected {len(questions)}/50 questions; seed={args.seed}",flush=True)
        if args.check_retrieval:
            dispatcher=RetrievalBatcher(config,args.k,log,args.batch_size,0)
            def check(q):
                return dispatcher.search(q,q['question'],models[0],{}, {'mode':'hybrid'})
            with ThreadPoolExecutor(max_workers=args.batch_size) as pool:
                found=list(pool.map(check,questions))
            dispatcher.close()
            checks=[]
            for q,(hits,metrics) in zip(questions,found):
                checks.append({"id":q["id"],**metrics})
                print(f"{q['id']}: {len(hits)} chunks; Elasticsearch {metrics['retrieval_engine_time_ms']} ms",flush=True)
            save(DB/"readiness.json",{"questions_checked":len(checks),"llm_api_calls":0,"checks":checks})
            return
        settings=[SCHEMA_VERSION,METHOD,SYSTEM,TOOLS,OPENROUTER_PATH,config,args.k,args.context_tokens,
            args.max_steps,args.max_searches,args.max_tool_calls,args.max_output_tokens,args.thinking_level]
        budget.initialize(args.resume_after_access_restored)
        signature=hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()
        path=HOME/"q-a.jsonl"; records={}
        for line in path.read_text().splitlines() if path.exists() else []:
            row=json.loads(line); RECORD_VALIDATOR.validate(row)
            if row["method"]!=METHOD or row["configuration_hash"]!=signature:
                raise RuntimeError("Saved evaluation settings differ; use --fresh or archive the output first")
            records[row["question_id"]]=row
        if args.refresh_metadata:
            n=collect_metadata(records,questions,models,args,base,key,log,all_questions)
            print(f"Enriched {n} model turns; no generation calls")
            return
        run_questions(questions,all_questions,records,models,signature,config,log,selection,args,base,key)
        enriched=0 if args.defer_metadata else collect_metadata(records,questions,models,args,base,key,log,all_questions)
        failed=sum(records[q["id"]]["answers"].get(m,{}).get("status") not in ("ok","truncated") for q in questions for m in models)
        log.write("run_completed",",".join(models),questions=len(questions),failed_answers=failed,metadata_enriched=enriched,scoring=False)
        print(f"Saved {HOME/'q-a.jsonl'}; failed answers: {failed}")
        if failed: raise SystemExit(1)


def endpoint_probe(models,args,base,key,log):
    for model in models:
        messages=[{"role":"user","content":"Call lume_search with query 'probe'. After receiving the tool result reply only OK."}]
        payload={"model":model,"messages":messages,"tools":TOOLS,
            "tool_choice":{"type":"function","function":{"name":"search_filings"}},
            "reasoning":{"effort":args.thinking_level.lower()},"max_tokens":1024,"stream":False,"usage":{"include":True}}
        calls=[]
        data=http_call(base,key,OPENROUTER_PATH+"/chat/completions",payload,model,log,"endpoint-test",calls,stage="tool_probe")
        msg=((data or {}).get("choices") or [{}])[0].get("message") or {}
        tools=msg.get("tool_calls") or []
        if not tools: raise RuntimeError("Configured model did not return a tool call; inspect raw-eval.log")
        messages.append({"role":"assistant",**{k:v for k,v in msg.items() if k in ("content","tool_calls","reasoning","reasoning_details") and v is not None}})
        messages.extend({"role":"tool","tool_call_id":t["id"],"content":"Probe succeeded. Reply OK."} for t in tools)
        payload={**payload,"messages":messages,"tool_choice":"none"}
        data=http_call(base,key,OPENROUTER_PATH+"/chat/completions",payload,model,log,"endpoint-test",calls,stage="tool_continuation_probe")
        content=(((data or {}).get("choices") or [{}])[0].get("message") or {}).get("content")
        if not content: raise RuntimeError("Tool-result continuation failed; inspect raw-eval.log")
        report={"model":model,"tool_call_received":True,"continuation":content,"api_calls":calls,"checked_at":utc_now()}
        save(DB/"endpoint-readiness.json",report)
        print(f"{model}: tool call and continuation OK",flush=True)


if __name__=="__main__":
    try:
        main()
    except KeyboardInterrupt:
        if ACTIVE_LOG: ACTIVE_LOG.write("run_interrupted","agentic",message="Resume saved checkpoints with the same command")
        print("Interrupted. Saved checkpoints can be resumed with the same command.",file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        if ACTIVE_LOG:
            ACTIVE_LOG.write("run_failed","agentic",error=str(error),traceback=traceback.format_exc())
        safe=str(error).replace(ACTIVE_LOG.key,"[REDACTED]") if ACTIVE_LOG and ACTIVE_LOG.key else str(error)
        print(f"Evaluation failed: {safe}. See raw-eval.log; saved checkpoints are retained.",file=sys.stderr)
        raise SystemExit(1)

