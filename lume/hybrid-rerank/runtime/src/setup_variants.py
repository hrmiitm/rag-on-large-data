#!/usr/bin/env python3
"""Prepare only: verify existing assets and create isolated configurations. No LLM calls."""
from __future__ import annotations
import argparse, json, re, shutil, struct, sys, urllib.request
from pathlib import Path
import runtime as rt
from reranker import MODEL
REVISION='233902d25c440f23af6f7d6e94d2946bac0bee0a'
DEFAULTS={'candidate_k':50,'context_k':10,'context_tokens':12000,'rrf_constant':60,'mmr_weight':.7,
          'max_subquestions':3,'query_model':'google/gemini-3.8-flash','query_reasoning':'HIGH','query_max_tokens':4096,
          'embedding_model':'openai/text-embedding-3-small','embedding_dimensions':1536,
          'reranker_model':MODEL,'reranker_revision':REVISION,'reranker_window_tokens':512,'reranker_overlap':64,
          'reranker_aggregation':'max_logit','reranker_model_dir':'../hybrid-rerank/runtime/db/reranker',
          'decomposition_policy':'original plus up to three subquestions; hybrid per query; subquestion-first round-robin deduplication',
          'hyde_policy':'one hypothetical passage; semantic retrieval only; hypothetical text excluded from answer context'}

def original_queries(path):
    with path.open('rb') as stream:
        header=stream.read(40)
        magic,version,flags,endian,size,dims,docs,queries,reserved=struct.unpack('<8sHHIQIIII',header)
        if magic!=b'LUMEVEC1' or version!=1 or endian!=0x01020304 or dims!=1536 or path.stat().st_size!=size:raise ValueError('Invalid native vector header')
        fields=[]
        for _ in range(3):fields.append(stream.read(struct.unpack('<H',stream.read(2))[0]).decode())
        if fields!=['text-embedding-3-small','document','query']:raise ValueError('Embedding profile mismatch')
        for _ in range(docs):stream.seek(struct.unpack('<I',stream.read(4))[0],1)
        stream.seek(docs*dims*4,1)
        ids=[stream.read(struct.unpack('<I',stream.read(4))[0]).decode() for _ in range(queries)]
        return dict(zip(ids,[list(struct.unpack('<'+'f'*dims,stream.read(dims*4))) for _ in ids]))

def download_reranker():
    model_dir=rt.SRC.parent/'db/reranker';model_dir.mkdir(parents=True,exist_ok=True)
    for remote,name in [('tokenizer.json','tokenizer.json'),('config.json','config.json'),('onnx/model.onnx','model.onnx')]:
        target=model_dir/name
        if not target.exists():
            temp=target.with_suffix('.download')
            try:
                with urllib.request.urlopen(f'https://huggingface.co/{MODEL}/resolve/{REVISION}/{remote}',timeout=180) as response,temp.open('wb') as output:shutil.copyfileobj(response,output)
                temp.replace(target)
            finally:temp.unlink(missing_ok=True)
    manifest={'model':MODEL,'revision':REVISION,'backend':'onnxruntime CPU','files':{name:rt.sha256(model_dir/name) for name in ['tokenizer.json','config.json','model.onnx']}}
    rt.save(model_dir/'manifest.json',manifest)
    # Load assets and validate ONNX/tokenizer interfaces, without running inference.
    from reranker import CrossEncoder
    model=CrossEncoder(model_dir)
    if not {'input_ids','attention_mask'}<=model.inputs:raise ValueError('Unexpected ONNX model inputs')
    return manifest

def setup(methods,download=False,verify_vectors=True):
    source=json.loads((rt.SHARED/'config.json').read_text())
    qfile=rt.REPO/'lume/semantic-search/src/questions.jsonl'
    questions=[json.loads(line) for line in qfile.read_text().splitlines() if line.strip()]
    if len(questions)!=50 or len({q['id'] for q in questions})!=50 or any(set(q)!={'id','question','as_of'} for q in questions):raise ValueError('Expected 50 question-only inputs')
    if rt.sha256(qfile)!=source['questions_sha256']:raise ValueError('Question snapshot hash mismatch')
    if not source.get('complete') or source['chunks']!=640745 or len(source['shards'])!=33 or source['embedding_dimensions']!=1536:raise ValueError('Expected complete existing embedding database')
    if rt.sha256(rt.SHARED/'global-stats.json')!=source['global_stats_sha256']:raise ValueError('Global BM25 statistics hash mismatch')
    if not rt.HELPER.exists():raise ValueError('Build the new native adapter first; see README')
    for shard in source['shards']:
        path=rt.SHARED/shard['index']/'local-vectors.bin'
        if not path.exists() or (verify_vectors and rt.sha256(path)!=source['vector_hashes'][shard['name']]):raise ValueError('Shared vector hash mismatch: '+shard['name'])
    queries=original_queries(rt.SHARED/source['shards'][0]['index']/'local-vectors.bin')
    expected={' '.join(re.findall(r'[^\W_]+',q['question'],re.UNICODE)) for q in questions}
    if not expected<=queries.keys():raise ValueError('Missing original question vectors')
    rt.save(rt.SRC.parent/'db/original-queries.json',{'source_vector_sha256':source['vector_hashes'][source['shards'][0]['name']],'vectors':queries})
    if download:download_reranker()
    for method in methods:
        home=rt.REPO/'lume'/method;db=home/'db';db.mkdir(parents=True,exist_ok=True);(db/'runtime').mkdir(exist_ok=True)
        with rt.file_lock(db/'.lock',blocking=False):
            config={**DEFAULTS,'method':method,'source_sha256':source['source_sha256'],'questions_sha256':source['questions_sha256'],
                    'shared_config_sha256':rt.sha256(rt.SHARED/'config.json'),'global_stats_sha256':source['global_stats_sha256'],
                    'vector_hashes':source['vector_hashes'],'helper_sha256':rt.sha256(rt.HELPER),
                    'original_query_cache_sha256':rt.sha256(rt.SRC.parent/'db/original-queries.json'),
                    'source_commit':source['source_commit'],'shared_embedding_database':'lume/semantic-search/db','graph':0}
            if (db/'config.json').exists() and json.loads((db/'config.json').read_text())!=config:
                if (home/'q-a.jsonl').exists() and (home/'q-a.jsonl').stat().st_size:raise ValueError('Refusing to change configuration with saved results: '+method)
            rt.save(db/'config.json',config)
            native={**source,'technique':'per-query','global_stats':str(rt.SHARED/'global-stats.json'),
                    'shards':[{**shard,'index':str(rt.SHARED/shard['index'])} for shard in source['shards']]}
            rt.save(db/'native-config.json',native)
            shutil.copyfile(rt.SHARED/'filing-dates.json',db/'filing-dates.json')
            shutil.copyfile(qfile,home/'src/questions.jsonl')
            rt.save(db/'setup-report.json',{'status':'prepared','full_vector_hash_verification':verify_vectors,'chunks':source['chunks'],'shards':33,
                    'document_embedding_calls':0,'evaluation_calls':0,'native_retrieval_runs':0,'new_method':method,
                    'reranker_assets_present':(rt.SRC.parent/'db/reranker/manifest.json').exists()})
            print(method+': prepared; no evaluation run')

def main(default=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-reranker',action='store_true',help='Download pinned public model files; no paid API calls')
    parser.add_argument('--method',choices=rt.METHODS,action='append')
    args=parser.parse_args();setup(args.method or ([default] if default else rt.METHODS),download=args.download_reranker)
if __name__=='__main__':main()
