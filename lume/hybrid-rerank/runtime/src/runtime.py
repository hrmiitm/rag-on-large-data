"""Isolated paths and atomic writes for the five read-only-index experiments."""
from __future__ import annotations
import contextlib, fcntl, hashlib, json, os, time, uuid
from pathlib import Path
SRC=Path(__file__).resolve().parent
REPO=SRC.parents[3]
METHOD=os.environ.get('LUME_VARIANT','hybrid-rerank')
METHODS=('hybrid-rerank','semantic-rerank','rrf','rrf-rerank','hyde')
if METHOD not in METHODS: raise ValueError('Unknown retrieval variant')
HOME=REPO/'lume'/METHOD
DB=HOME/'db'
SHARED=REPO/'lume/semantic-search/db'
HELPER=SRC/'native/target/release/lume-variants-bounded'
BIN=HELPER

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8<<20),b''):h.update(block)
    return h.hexdigest()

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp.'+uuid.uuid4().hex)
    try:
        with tmp.open('w') as stream:
            json.dump(value,stream,ensure_ascii=False,allow_nan=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        tmp.replace(path)
    finally:tmp.unlink(missing_ok=True)

@contextlib.contextmanager
def file_lock(path,readonly=False,blocking=True):
    path=Path(path)
    if not readonly:path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('rb' if readonly else 'a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)

def database_lock():return file_lock(DB/'.lock',blocking=False)

def runtime_env():
    env={k:v for k,v in os.environ.items() if not k.startswith(('LUME_','BM25_','SHIVVR_','NUTS_','OLLAMA_','LLMFOUNDRY_'))}
    temp=DB/'runtime';temp.mkdir(parents=True,exist_ok=True)
    env.update(XDG_CACHE_HOME=str(temp),TMPDIR=str(temp),LUME_STEM='1',LUME_TITLE_FALLBACK='0')
    return env

def limited_command(command,megabytes=2048):
    return ['prlimit',f'--as={megabytes<<20}','--',*map(str,command)]

def wait_for_memory(stop=None):
    while Path('/proc/meminfo').exists():
        available=next(int(l.split()[1]) for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
        if available>=2304*1024:return
        if stop is not None and stop.is_set():raise InterruptedError('Stopped while waiting for memory')
        print('Waiting for 2304 MiB available RAM before native search',flush=True)
        time.sleep(5)
