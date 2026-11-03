#!/usr/bin/env python3
"""Shared SEC dense ingestion; Foundry/OpenRouter only, resumable per batch."""
from __future__ import annotations
import argparse, base64, contextlib, datetime, fcntl, gzip, hashlib, http.client, json, math, os, ssl
from pathlib import Path
import re, shutil, signal, sqlite3, struct, subprocess, sys, threading, time, urllib.request, urllib.error, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from gateway import GatewayGuard

SRC=Path(__file__).resolve().parent
REPO=SRC.parents[2]
METHOD=os.environ.get('LUME_SEARCH_METHOD','semantic-search')
HOME=REPO/'lume'/METHOD
DB=HOME/'db'
SHARED=SRC.parent/'db'
BIN=SRC/'bin'/'lume'
HELPER=SRC/'native'/'target'/'release'/'lume-vector-bounded'
EMBED_MODEL='openai/text-embedding-3-small'
DIMS=1536
STOP=threading.Event()
class IngestionPaused(RuntimeError):pass
class TransientEmbeddingError(RuntimeError):pass

def check_stop():
    if STOP.is_set():raise IngestionPaused('Pause requested; saved batches retained')

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8<<20),b''): h.update(b)
    return h.hexdigest()

def save(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp.'+uuid.uuid4().hex)
    with tmp.open('w') as f:
        json.dump(value,f,ensure_ascii=False,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    tmp.replace(path)

@contextlib.contextmanager
def database_lock():
    DB.mkdir(parents=True,exist_ok=True)
    with (DB/'.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try: yield
        finally: fcntl.flock(f,fcntl.LOCK_UN)

def runtime_env():
    env=dict(os.environ)
    for k in list(env):
        if k.startswith(('LUME_','BM25_','SHIVVR_','NUTS_','OLLAMA_','LLMFOUNDRY_')) or k in ('ALPHA','GRAPH_ALPHA'): env.pop(k)
    runtime=DB/'runtime';runtime.mkdir(parents=True,exist_ok=True)
    env.update(XDG_CACHE_HOME=str(runtime),TMPDIR=str(runtime),LUME_STEM='1',LUME_TITLE_FALLBACK='0')
    return env

def resource_waits():
    result=[]
    for path in SHARED.glob('resource-wait-*.json'):
        try:entry=json.loads(path.read_text())
        except FileNotFoundError:continue
        if Path(f"/proc/{entry['pid']}").exists():result.append(entry)
    return result

def available_memory_kib():
    return next(int(l.split()[1]) for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))

def limited_command(command,megabytes=2048):
    required=(megabytes+256)*1024
    waiting=SHARED/f'resource-wait-{os.getpid()}.json'
    notice=0.
    try:
        while (available:=available_memory_kib())<required:
            check_stop()
            save(waiting,{'pid':os.getpid(),'reason':'insufficient_available_ram','available_ram_mb':available/1024,
                'required_available_ram_mb':required/1024,'native_address_space_limit_mb':megabytes,
                'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
            if time.monotonic()-notice>=60 or notice==0:
                print(f'Waiting for RAM: {available/1024:.0f} MiB available; {required/1024:.0f} MiB required. Saved embeddings retained.',flush=True)
                notice=time.monotonic()
            time.sleep(15)
    finally:
        waiting.unlink(missing_ok=True)
    check_stop()
    return ['prlimit',f'--as={megabytes<<20}','--',*map(str,command)]

def native(*args,timeout=900):
    r=subprocess.run(limited_command([HELPER,*args]),env=runtime_env(),capture_output=True,text=True,timeout=timeout)
    if r.returncode: raise RuntimeError(r.stderr[-3000:])
    return r.stdout

def credentials():
    values={}
    for p in (REPO/'.env.example',REPO/'.env'):
        if p.exists():
            for l in p.read_text().splitlines():
                if l.strip() and not l.lstrip().startswith('#') and '=' in l:
                    k,v=l.removeprefix('export ').split('=',1);values[k.strip()]=v.strip().strip('\"\'')
    values.update(os.environ)
    from urllib.parse import urlsplit
    base=values.get('LLMFOUNDRY_BASE_URL','').rstrip('/');key=values.get('LLMFOUNDRY_API_KEY','');u=urlsplit(base)
    if values.get('LLM_PROVIDER','llmfoundry')!='llmfoundry' or u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment or not key: raise ValueError('Configure credential-free HTTPS Foundry base and API key')
    return base,key

def clean_query(text): return ' '.join(re.findall(r'[^\W_]+',text,re.UNICODE))

class Embedder:
    def __init__(self,provider_order=None):
        self.provider_order=provider_order
        self.base,self.key=credentials();self.lock=threading.Lock();self.halt=threading.Event()
        self.gateway=GatewayGuard();self.transient_failure=False
        self.audit=(SHARED/'embedding-audit.jsonl').open('a',buffering=1)
    @property
    def rate_limited_at(self):return self.gateway.limited_at
    def allowed(self):
        check_stop()
        if self.halt.is_set():
            error=TransientEmbeddingError if self.transient_failure else RuntimeError
            raise error('Embedding requests stopped after another worker exhausted its retries')
    def log(self,entry):
        line=json.dumps(entry,ensure_ascii=False).replace(self.key,'[REDACTED]')
        with self.lock: self.audit.write(line+'\n');self.audit.flush();os.fsync(self.audit.fileno())
    def request(self,texts,batch_id):
        self.allowed()
        payload={'model':EMBED_MODEL,'input':texts,'dimensions':DIMS,'encoding_format':'base64'}
        if self.provider_order:payload['provider']={'order':self.provider_order,'allow_fallbacks':True}
        digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest()
        encoded_payload=json.dumps(payload).encode()
        for attempt in range(1,7):
            self.allowed()
            call_id=uuid.uuid4().hex;start=time.perf_counter()
            try:
                with self.gateway.slot(self.allowed):
                    start=time.perf_counter()
                    self.log({'event':'request','batch_id':batch_id,'call_id':call_id,'attempt':attempt,'url':self.base+'/openrouter/v1/embeddings','model':EMBED_MODEL,'dimensions':DIMS,'count':len(texts),'input_sha256':digest,'time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
                    req=urllib.request.Request(self.base+'/openrouter/v1/embeddings',data=encoded_payload,headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json','Accept-Encoding':'gzip'})
                    http_started=time.perf_counter()
                    with urllib.request.urlopen(req,timeout=180) as r:
                        headers_at=time.perf_counter();raw=r.read();read_at=time.perf_counter()
                        decoded=gzip.decompress(raw) if r.headers.get('Content-Encoding')=='gzip' else raw
                        data=json.loads(decoded);decoded_at=time.perf_counter()
                if data.get('error'): raise ValueError(str(data['error']))
                if data.get('model') not in ('text-embedding-3-small',EMBED_MODEL): raise ValueError('Returned embedding model mismatch')
                rows=sorted(data['data'],key=lambda v:v['index'])
                if [r['index'] for r in rows]!=list(range(len(texts))): raise ValueError('Embedding index/count mismatch')
                blobs=[]
                for row in rows:
                    v=row['embedding']
                    if isinstance(v,str): b=base64.b64decode(v,validate=True)
                    else: b=struct.pack('<'+'f'*DIMS,*v)
                    if len(b)!=DIMS*4: raise ValueError('Embedding dimension mismatch')
                    vals=struct.unpack('<'+'f'*DIMS,b)
                    if not all(math.isfinite(x) for x in vals) or sum(x*x for x in vals)==0: raise ValueError('Invalid vector')
                    blobs.append(b)
                info={k:v for k,v in data.items() if k!='data'}
                info.update(batch_id=batch_id,call_id=call_id,input_sha256=digest,attempt=attempt,count=len(texts),latency_seconds=time.perf_counter()-start,
                    transport={'request_bytes':len(encoded_payload),'response_wire_bytes':len(raw),'response_decoded_bytes':len(decoded),
                        'request_to_headers_seconds':headers_at-http_started,'response_read_seconds':read_at-headers_at,
                        'decode_seconds':decoded_at-read_at,'vector_validation_seconds':time.perf_counter()-decoded_at})
                # Cache writer saves vectors before marking a batch complete.
                self.log({'event':'response','http_status':200,**info})
                return blobs,info
            except Exception as e:
                if isinstance(e,(IngestionPaused,TransientEmbeddingError)):raise
                retry=isinstance(e,(TimeoutError,ConnectionError,urllib.error.URLError,http.client.HTTPException,ssl.SSLError,EOFError,json.JSONDecodeError)) and (not isinstance(e,urllib.error.HTTPError) or e.code in (429,500,502,503,504))
                if retry:
                    try:retry_after=float(e.headers.get('Retry-After','0')) if isinstance(e,urllib.error.HTTPError) else 0
                    except (TypeError,ValueError):retry_after=0
                    self.gateway.error(getattr(e,'code',None),retry_after)
                details=e.read().decode(errors='replace')[:2000] if isinstance(e,urllib.error.HTTPError) else str(e)
                self.log({'event':'error','batch_id':batch_id,'call_id':call_id,'attempt':attempt,'http_status':getattr(e,'code',None),'error':details,'latency_seconds':time.perf_counter()-start,
                    'remote_outcome':'unknown' if retry else 'error','usage_available':False})
                if STOP.is_set():raise IngestionPaused('Paused after failed in-flight request') from None
                if not retry or attempt==6:
                    self.transient_failure=retry;self.halt.set()
                    error=TransientEmbeddingError if retry else RuntimeError
                    raise error(details.replace(self.key,'[REDACTED]')) from None
                if STOP.wait(min(30,2**attempt)):check_stop()

def copy_file(src,dst):
    if dst.exists():
        if sha256(src)!=sha256(dst): raise RuntimeError(f'Snapshot differs: {dst}')
        return
    dst.parent.mkdir(parents=True,exist_ok=True);tmp=dst.with_suffix(dst.suffix+'.tmp')
    subprocess.run(['cp','--reflink=auto',str(src),str(tmp)],check=True);tmp.replace(dst)

def snapshot():
    """Reuse immutable lexical ingestion, with full prepared-source slice validation."""
    baseline=REPO/'lume'/'bm25';config=json.loads((baseline/'db/config.json').read_text())
    corpus=REPO/'data/financial_sections.parquet'
    if sha256(corpus)!=config['source_sha256'] or config['documents']!=10469 or config['chunks']!=640745: raise RuntimeError('Expected complete prepared corpus')
    SHARED.mkdir(parents=True,exist_ok=True)
    ready=SHARED/'snapshot.json'
    if ready.exists(): return json.loads(ready.read_text())
    # No baseline locks or outputs are opened for writing. All copies are independent.
    for name in ('chunks.sqlite','global-stats.json'):
        copy_file(baseline/'db'/name,SHARED/name)
    for shard in config['shards']:
        source=baseline/'db'/shard['index'];dest=SHARED/shard['index']
        dest.mkdir(parents=True,exist_ok=True)
        for f in source.rglob('*'):
            if f.is_file(): copy_file(f,dest/f.relative_to(source))
    copy_file(baseline/'src/bin/lume',BIN)
    copy_file(corpus,SHARED/corpus.name)
    questions=[json.loads(l) for l in (REPO/'data/questions.jsonl').read_text().splitlines() if l.strip()]
    (SRC/'questions.jsonl').write_text(''.join(json.dumps({k:q[k] for k in ('id','question','as_of')},ensure_ascii=False)+'\n' for q in questions))
    if len(questions)!=50: raise ValueError('Expected 50 questions')
    config['questions_sha256']=sha256(SRC/'questions.jsonl')
    config['snapshot_origin']='Read-only independent copy of pinned BM25 lexical index; all chunk bodies validated against original prepared Parquet'
    save(SHARED/'snapshot-unverified.json',config)
    verify_source(config)
    save(ready,config);return config

def verify_source(config):
    import pyarrow.parquet as pq
    conn=sqlite3.connect(f'file:{SHARED}/chunks.sqlite?mode=ro',uri=True);conn.row_factory=sqlite3.Row
    checked=0;docs=0
    for batch in pq.ParquetFile(REPO/'data/financial_sections.parquet').iter_batches(batch_size=1,columns=['document_id','md5','sections','company','form','filing_date'],use_threads=False):
        row=batch.to_pylist()[0];docs+=1
        chunks=conn.execute('SELECT * FROM chunks WHERE file=? ORDER BY line',(row['document_id']+'.txt',)).fetchall()
        if not chunks: raise ValueError('Missing filing')
        expected_date=int(row['filing_date'].replace('-',''))
        expected_title=f"Company: {row['company']} | Form: {row['form']} | Filed: {expected_date} | Document: {row['document_id']}"
        for c in chunks:
            if c['document_id']!=row['document_id'] or c['filing_date']!=expected_date or c['title']!=expected_title: raise ValueError('Filing metadata mismatch')
            spans=[s for s in row['sections'] if s['start_char']<=c['start_char']<c['end_char']<=s['end_char'] and s['section']==c['section']]
            if len(spans)!=1 or c['source_hash']!=row['md5']: raise ValueError('Source mismatch')
            s=spans[0]
            if s['text'][c['start_char']-s['start_char']:c['end_char']-s['start_char']]!=c['body']: raise ValueError('Chunk not an exact retained source slice')
            checked+=1
    if checked!=config['chunks'] or docs!=config['documents']: raise ValueError('Corpus count mismatch')
    dates=dict(conn.execute('SELECT file,MIN(filing_date) FROM chunks GROUP BY file'))
    save(SHARED/'filing-dates.json',dates)
    save(SHARED/'source-validation.json',{'documents':docs,'exact_source_slices':checked,'source_sha256':config['source_sha256'],'gold_in_index':False,'filing_metadata_checked':True})
    conn.close();print(f'Validated all {checked} chunks against retained Parquet text',flush=True)

def build_helper():
    env=dict(os.environ,RUSTUP_HOME=str(SRC/'.rustup'),CARGO_HOME=str(SRC/'.cargo'),CARGO_BUILD_JOBS='1')
    with (SHARED/'native-build.log').open('w') as f:
        subprocess.run([str(SRC/'.cargo/bin/cargo'),'build','--release','--offline','--jobs','1','--manifest-path',str(SRC/'native/Cargo.toml')],env=env,stdout=f,stderr=subprocess.STDOUT,check=True)

def batch_cache(embedder,texts,ids,path):
    info_path=path.with_suffix('.json');identity=hashlib.sha256(json.dumps([ids,texts],ensure_ascii=False).encode()).hexdigest()
    if path.exists() and info_path.exists():
        info=json.loads(info_path.read_text())
        if info.get('model') not in ('text-embedding-3-small',EMBED_MODEL) or info['identity']!=identity or path.stat().st_size!=len(texts)*DIMS*4 or sha256(path)!=info['vectors_sha256']: raise ValueError('Corrupt embedding batch cache')
        return info
    check_stop()
    blobs,info=embedder.request(texts,str(path.relative_to(SHARED)))
    tmp=path.with_suffix('.tmp')
    with tmp.open('wb') as f:
        for b in blobs: f.write(b)
        f.flush();os.fsync(f.fileno())
    tmp.replace(path);info.update(identity=identity,ids=ids,vectors_sha256=sha256(path));save(info_path,info);return info

def write_vectors(target,ids,batches,queries):
    ids=sorted(set(ids));dimensions=DIMS
    qids=sorted(queries)
    # Batch vectors are addressed by the stable Lume section hash.
    locations={}
    for path in batches:
        info=json.loads(path.with_suffix('.json').read_text())
        for i,identity in enumerate(info['ids']): locations[identity]=(path,i*dimensions*4)
    tmp=target.with_suffix('.tmp')
    with tmp.open('wb') as out:
        out.write(struct.pack('<8sHHIQIIII',b'LUMEVEC1',1,0,0x01020304,0,dimensions,len(ids),len(qids),0))
        for v in ('text-embedding-3-small','document','query'):
            b=v.encode();out.write(struct.pack('<H',len(b)));out.write(b)
        for identity in ids:
            b=identity.encode();out.write(struct.pack('<I',len(b)));out.write(b)
        for identity in ids:
            p,offset=locations[identity]
            with p.open('rb') as f:f.seek(offset);out.write(f.read(dimensions*4))
        for identity in qids:
            b=identity.encode();out.write(struct.pack('<I',len(b)));out.write(b)
        for identity in qids:out.write(queries[identity])
        size=out.tell();out.seek(16);out.write(struct.pack('<Q',size));out.flush();os.fsync(out.fileno())
    tmp.replace(target)

def finalize(config):
    vector_hashes={s['name']:json.loads((SHARED/s['index']/'vectors-ready.json').read_text())['sha256'] for s in config['shards']}
    for method in ('semantic-search','hybrid'):
        folder=REPO/'lume'/method;db=folder/'db';db.mkdir(parents=True,exist_ok=True)
        if method=='hybrid':
            for name in ('index','chunks.sqlite','global-stats.json','filing-dates.json'):
                p=db/name
                if not p.exists():p.symlink_to(os.path.relpath(SHARED/name,db),target_is_directory=name=='index')
        out={**config,'technique':method,'alpha':0.5 if method=='hybrid' else 0,'graph':0,'embedding_model':EMBED_MODEL,'embedding_dimensions':DIMS,'vector_hashes':vector_hashes,'helper_sha256':sha256(HELPER),'binary_sha256':sha256(BIN),'shared_embedding_database':'lume/semantic-search/db','candidate_depth':'all','fusion':'Lume native multiplicative: bm25*(1+0.5*cosine), cosine for semantic-only candidates' if method=='hybrid' else 'exact cosine only; no lexical score or graph boost'}
        save(db/'config.json',out)
        (folder/'q-a.jsonl').touch(exist_ok=True);(folder/'raw-eval.log').touch(exist_ok=True)
    print('Semantic and hybrid databases ready',flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--concurrency',type=int,default=6);parser.add_argument('--batch-size',type=int,default=256);parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--adaptive',action='store_true',help='Ramp request concurrency with memory and gateway backoff guards')
    args=parser.parse_args()
    if not 1<=args.concurrency<=64 or not 1<=args.batch_size<=256:parser.error('Concurrency 1..64; batch size 1..256')
    if METHOD!='semantic-search':raise RuntimeError('Run shared ingestion from semantic-search/src/setup.py')
    for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *_:STOP.set())
    try:
        with database_lock():
            config=snapshot();build_helper()
            if args.prepare_only:return
            from ingestion import ingest
            ingest(config,args,sys.modules[__name__]);check_stop();finalize(config)
    except IngestionPaused as error:
        save(SHARED/'ingestion-paused.json',{'status':'paused','time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reason':str(error)})
        print(str(error),flush=True)
        raise SystemExit(75)
    except TransientEmbeddingError as error:
        save(SHARED/'ingestion-retryable.json',{'status':'retryable_gateway_failure','time_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reason':str(error)})
        print('Transient gateway failure; all completed checkpoints retained: '+str(error),flush=True)
        raise SystemExit(76)

if __name__=='__main__':main()
