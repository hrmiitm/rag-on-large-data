#!/usr/bin/env python3
"""Prepare reflection-based RAG without retrieval or any API calls."""
import argparse,json,shutil
from bootstrap import SRC,rt,base

def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    source=json.loads((rt.SHARED/'config.json').read_text())
    original=json.loads((rt.REPO/'lume/hybrid-rerank/db/config.json').read_text())
    config={**original,'method':rt.METHOD,'candidate_k':10,'context_k':10,'context_tokens':12000,
        'retrieval_technique':'hybrid','reflection_rounds':1,'additional_searches_per_model':1,
        'reflection_model_policy':'same_as_answer_model','reflection_reasoning':'LOW','reflection_max_tokens':2048,
        'reflection_temperature':0,'final_context_policy':'alternate original and additional ranks, deduplicate, select top 10',
        'method_label':'Prompt-based reflection RAG; not the trained Self-RAG paper implementation',
        'reranker_used':False}
    questions=rt.REPO/'lume/semantic-search/src/questions.jsonl'
    rows=[json.loads(line) for line in questions.read_text().splitlines() if line.strip()]
    if len(rows)!=50 or len({q['id'] for q in rows})!=50 or any(set(q)!={'id','question','as_of'} for q in rows):raise ValueError('Expected 50 question-only records')
    if rt.sha256(questions)!=source['questions_sha256']:raise ValueError('Source questions changed')
    native={**source,'technique':'per-query','global_stats':str(rt.SHARED/'global-stats.json'),
        'shards':[{**shard,'index':str(rt.SHARED/shard['index'])} for shard in source['shards']]}
    rt.DB.mkdir(parents=True,exist_ok=True)
    with rt.database_lock():
        existing=rt.DB/'config.json'
        if existing.exists() and json.loads(existing.read_text())!=config and (rt.HOME/'q-a.jsonl').exists() and (rt.HOME/'q-a.jsonl').stat().st_size:
            raise ValueError('Refusing to replace configuration with saved results')
        rt.save(existing,config);rt.save(rt.DB/'native-config.json',native)
        shutil.copytree(rt.SRC/'.cache/tiktoken',SRC/'.cache/tiktoken',dirs_exist_ok=True)
        shutil.copyfile(questions,SRC/'questions.jsonl')
        shutil.copyfile(rt.SHARED/'filing-dates.json',rt.DB/'filing-dates.json')
        base.validate_setup(config,full=True)
        rt.save(rt.DB/'setup-report.json',{'prepared':True,'method':rt.METHOD,'chunks_verified':source['chunks'],
            'shards_verified':len(source['shards']),'document_embedding_calls':0,'query_embedding_calls':0,'llm_calls':0,
            'real_retrieval_runs':0,'dependencies':'read-only existing hybrid-rerank/runtime environment and native adapter'})
    print('self-reflective-rag: prepared; zero retrievals or API calls')
if __name__=='__main__':main()
