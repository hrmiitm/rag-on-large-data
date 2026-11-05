"""Validate all imported text/metadata/vector associations and search readiness.

Requires pyarrow only for original-Parquet verification. Reads existing method
files read-only; writes results solely under elasticsearch/db.
"""
import hashlib
import json
import math
import sqlite3
import struct
import time
import argparse
import fcntl
from pathlib import Path

from common import Client, DB, INDEX, REPO, SOURCE, resources, save
from setup import Vectors, metadata, sha256


def run(source_only=False):
    import pyarrow.parquet as pq
    started = time.monotonic()
    if not source_only:
        lock=(DB/'ingestion.lock').open('a')
        fcntl.flock(lock,fcntl.LOCK_SH | fcntl.LOCK_NB)
        state=json.loads((DB/'ingestion-state.json').read_text())
        if state['status'] not in ('indexed_pending_validation','ready'):
            raise RuntimeError('Finish full ingestion before validating the Elasticsearch index')
    client = Client()
    config = json.loads((DB/'config.json').read_text())
    identity = config['identity']
    source_config = json.loads((SOURCE/'config.json').read_text())
    if sha256(SOURCE/'chunks.sqlite') != identity['source_sqlite_sha256']:
        raise ValueError('Source metadata changed')
    if sha256(REPO/'data/financial_sections.parquet') != identity['corpus_sha256']:
        raise ValueError('Original retained corpus checksum mismatch')
    conn = sqlite3.connect(f'file:{SOURCE}/chunks.sqlite?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('PRAGMA cache_size=-16384')
    report = {'status':'validating_original_source','passed':False,'original_source_slices':0,'filings':0,
              'indexed_chunks_verified':0,'stored_vectors_checked':0,'native_vector_shards_verified':0,
              'original_embedding_receipts_verified':0,
              'api_calls':0,'api_cost_usd':0,'source_files_modified':False,'gold_in_index':False}

    def progress():
        report.update(elapsed_seconds=time.monotonic()-started,resources=resources())
        save(DB/'validation-report.json',report)
        print(json.dumps(report),flush=True)

    progress()
    proof_path=DB/'source-validation.json'
    proof=json.loads(proof_path.read_text()) if proof_path.exists() else {}
    reuse_source_proof=proof.get('passed') is True and proof.get('identity')==identity
    if reuse_source_proof:
        report.update(original_source_slices=proof['original_source_slices'],filings=proof['filings'],
                      reused_source_proof=True,source_validation_seconds=proof['elapsed_seconds'])
    batches=() if reuse_source_proof else pq.ParquetFile(REPO/'data/financial_sections.parquet').iter_batches(batch_size=1,columns=['document_id','md5','sections','company','form','filing_date'],use_threads=False)
    for batch in batches:
        original = batch.to_pylist()[0]
        expected_title = f"Company: {original['company']} | Form: {original['form']} | Filed: {original['filing_date'].replace('-','')} | Document: {original['document_id']}"
        rows = conn.execute('SELECT * FROM chunks WHERE file=? ORDER BY line',(original['document_id']+'.txt',)).fetchall()
        if not rows:
            raise ValueError('Missing source filing')
        for row in rows:
            spans=[s for s in original['sections'] if s['start_char'] <= row['start_char'] < row['end_char'] <= s['end_char'] and s['section']==row['section']]
            if len(spans)!=1:
                raise ValueError('Source section boundaries mismatch')
            span=spans[0]
            if (row['source_hash'] != original['md5'] or row['title'] != expected_title or
                row['filing_date'] != int(original['filing_date'].replace('-','')) or
                row['body'] != span['text'][row['start_char']-span['start_char']:row['end_char']-span['start_char']]):
                raise ValueError('Source text/metadata does not match original retained Parquet')
            report['original_source_slices'] += 1
        report['filings'] += 1
        if report['filings'] % 1000 == 0: progress()
    if (report['original_source_slices'],report['filings']) != (identity['chunks'],identity['documents']):
        raise ValueError('Source coverage mismatch')
    report['status']='validating_elasticsearch'
    progress()
    if source_only:
        save(DB/'source-validation.json',{'passed':True,'identity':identity,
             'original_source_slices':report['original_source_slices'],'filings':report['filings'],
             'elapsed_seconds':report['elapsed_seconds'],'api_cost_usd':0})
        return
    pit = client.request('POST',f'/{INDEX}/_pit?keep_alive=5m')['id']
    try:
        for shard in source_config['shards']:
            name=shard['name']
            path=SOURCE/shard['index']/'local-vectors.bin'
            if sha256(path) != source_config['vector_hashes'][name]:
                raise ValueError('Source vectors changed')
            vectors=Vectors(path)
            try:
                native_rows={}
                for line in (SOURCE/'embedding-batches'/f'{name}.jsonl').read_text().splitlines():
                    d=json.loads(line)
                    d['native_shard']=name
                    key=f"{Path(d['file']).stem}:{d['line']}"
                    if key in native_rows: raise ValueError('Duplicate source descriptor')
                    native_rows[key]=d
                # Receipts bind exact original embedding inputs and vector bytes
                # to the descriptors. This catches swapped text/vector mappings.
                ordered=list(native_rows.values())
                for offset in range(0,len(ordered),256):
                    group=ordered[offset:offset+256]
                    receipt=json.loads((SOURCE/'embedding-batches'/f'{name}-{offset:06d}.json').read_text())
                    ids=[d['id'] for d in group]
                    texts=[]
                    digest=hashlib.sha256()
                    for d in group:
                        row=conn.execute('SELECT title,body FROM chunks WHERE file=? AND line=?',(Path(d['file']).name,d['line'])).fetchone()
                        texts.append(row['title']+'\n'+row['body'])
                        digest.update(vectors.get(d['id']))
                    input_identity=hashlib.sha256(json.dumps([ids,texts],ensure_ascii=False).encode()).hexdigest()
                    if receipt['ids']!=ids or receipt['identity']!=input_identity or receipt['vectors_sha256']!=digest.hexdigest():
                        raise ValueError('Original embedding receipt/text/vector association mismatch')
                    report['original_embedding_receipts_verified']+=1
                seen=set()
                after=None
                while True:
                    query={'size':512,'pit':{'id':pit,'keep_alive':'5m'},'sort':['_shard_doc'],
                           'query':{'term':{'native_shard':name}},'track_total_hits':False}
                    if after is not None: query['search_after']=after
                    result=client.request('POST','/_search',query)
                    pit=result.get('pit_id',pit)
                    hits=result['hits']['hits']
                    if not hits: break
                    for hit in hits:
                        key=hit['_id']
                        if key in seen or key not in native_rows: raise ValueError('Duplicate/unmapped indexed ID')
                        seen.add(key)
                        native=native_rows[key]
                        row=conn.execute('SELECT * FROM chunks WHERE file=? AND line=?',(Path(native['file']).name,native['line'])).fetchone()
                        expected=metadata(row,native,vectors.get(native['id']))
                        if hit['_source'] != expected:
                            mismatches=[k for k in set(expected)|set(hit['_source']) if expected.get(k)!=hit['_source'].get(k)]
                            raise ValueError(f'Indexed text/metadata mismatch {key}: {mismatches}')
                        report['indexed_chunks_verified'] += 1
                    after=hits[-1]['sort']
                if len(seen)!=shard['chunks'] or seen!=set(native_rows): raise ValueError('Indexed shard coverage mismatch')
                # Inspect actual indexed float values, beyond the stored checksum.
                sample_ids=sorted(seen)
                for key in (sample_ids[0],sample_ids[len(sample_ids)//2],sample_ids[-1]):
                    native=native_rows[key]
                    original=list(struct.unpack('<1536f',vectors.get(native['id'])))
                    found=client.request('POST',f'/{INDEX}/_search',{'size':1,'_source':False,'query':{'ids':{'values':[key]}},'fields':['embedding']})['hits']['hits'][0]['fields']['embedding']
                    # ES may normalize non-unit cosine vectors; compare directions.
                    a=math.sqrt(sum(v*v for v in original));b=math.sqrt(sum(v*v for v in found))
                    diff=max(abs(x/a-y/b) for x,y in zip(original,found))
                    if len(found)!=1536 or diff>1e-6: raise ValueError('Stored vector direction mismatch')
                    report['stored_vectors_checked']+=1
                report['native_vector_shards_verified']+=1
                progress()
            finally:
                vectors.close()
    finally:
        client.request('DELETE','/_pit',{'id':pit})
        conn.close()
    if report['indexed_chunks_verified']!=identity['chunks']: raise ValueError('Final imported coverage mismatch')
    # Preserve original question-only query cache for later zero-embedding-cost tools.
    v=Vectors(SOURCE/source_config['shards'][0]['index']/'local-vectors.bin')
    try:
        raw=v.raw[v.query_offset:]
        (DB/'query-vectors.f32').write_bytes(raw)
        save(DB/'query-vectors.json',{'model':identity['embedding_model'],'dimensions':1536,'encoding':'little-endian float32',
             'query_texts':v.query_ids,'sha256':hashlib.sha256(raw).hexdigest(),'source':'existing native question-only cache'})
    finally: v.close()
    smoke=[]
    for cutoff in ('2025-01-31','2025-03-31','2025-06-30'):
        query={'size':10,'_source':['chunk_id','filing_date'],'query':{'bool':{'must':{'match':{'body':'revenue net income'}},'filter':{'range':{'filing_date':{'lte':cutoff}}}}}}
        t=time.monotonic();result=client.request('POST',f'/{INDEX}/_search',query)
        if not result['hits']['hits']: raise ValueError('Lexical smoke returned no passages')
        if any(h['_source']['filing_date']>cutoff for h in result['hits']['hits']):raise ValueError('Lexical cutoff violated')
        vector=list(struct.unpack('<1536f',raw[:1536*4]))
        t2=time.monotonic();dense=client.request('POST',f'/{INDEX}/_search',{'size':10,'_source':['chunk_id','filing_date'],
             'knn':{'field':'embedding','query_vector':vector,'k':10,'num_candidates':200,'filter':{'range':{'filing_date':{'lte':cutoff}}}}})
        if len(dense['hits']['hits'])!=10 or any(h['_source']['filing_date']>cutoff for h in dense['hits']['hits']):raise ValueError('Dense cutoff/coverage violated')
        smoke.append({'cutoff':cutoff,'lexical_wall_seconds':t2-t,'dense_wall_seconds':time.monotonic()-t2,
                      'lexical_es_ms':result['took'],'dense_es_ms':dense['took']})
    report.update(passed=True,status='ready',search_smoke=smoke,
                  index_stats=client.request('GET',f'/{INDEX}/_stats/docs,store,segments')['_all']['primaries'],
                  source_sqlite_hash_unchanged=sha256(SOURCE/'chunks.sqlite')==identity['source_sqlite_sha256'],
                  limitations=['ANN recall and gold-evidence coverage not yet benchmarked','No generation or judging performed'])
    if not report['source_sqlite_hash_unchanged']:raise ValueError('Source SQLite changed during validation')
    progress()
    state=json.loads((DB/'ingestion-state.json').read_text())
    state['status']='ready'
    state['validation_seconds']=report['elapsed_seconds']
    save(DB/'ingestion-state.json',state)
    ingestion=json.loads((DB/'ingestion-report.json').read_text())
    ingestion.update(status='ready',validation_passed=True,validation_seconds=report['elapsed_seconds'])
    save(DB/'ingestion-report.json',ingestion)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only',action='store_true',help='Verify every original source slice while ingestion continues')
    run(parser.parse_args().source_only)
