"""Independent evaluation paths and read-only index identity checks."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
from common import Client, DB, HOME, INDEX, REPO, save

SRC=Path(__file__).resolve().parent

def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(4<<20),b''):digest.update(block)
    return digest.hexdigest()

@contextmanager
def database_lock():
    with (DB/'evaluation.lock').open('a') as lock, (DB/'ingestion.lock').open('a') as index_lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(index_lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
        yield

def evaluation_config():
    ingestion=json.loads((DB/'config.json').read_text())
    ready=json.loads((DB/'validation-report.json').read_text())
    if not ready['passed'] or ready['status']!='ready':raise ValueError('Validated complete index required')
    c=Client()
    count=c.request('GET',f'/{INDEX}/_count')['count']
    actual=c.request('GET',f'/{INDEX}/_mapping')[INDEX]['mappings']['_meta']
    if count!=640745 or actual!=ingestion['identity']:raise ValueError('Index identity/coverage mismatch')
    return {'source_sha256':ingestion['identity']['corpus_sha256'],
            'questions_sha256':sha256(SRC/'questions.jsonl'),
            'index':INDEX,'index_uuid':c.request('GET',f'/{INDEX}/_settings')[INDEX]['settings']['index']['uuid'],
            'ingestion_identity':ingestion['identity'],'engine_version':ingestion['elasticsearch']['version']['number'],
            'candidate_depth':50,'knn_num_candidates':200,'rrf_rank_constant':60,
            'query_vector_policy':'fixed cached original-question embedding; refinements lexical and metadata only',
            'query_cache_sha256':sha256(DB/'query-vectors.f32'),
            'tools_code_sha256':sha256(SRC/'search.py'),'gold_in_index':False}
