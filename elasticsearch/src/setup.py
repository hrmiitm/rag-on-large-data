"""Stream validated existing SEC chunks/vectors into an independent ES index.

Only connects to 127.0.0.1:19200. No credentials, questions or embedding APIs.
"""
import argparse
import array
import base64
import fcntl
import hashlib
import json
import math
import mmap
import os
import shutil
import signal
import sqlite3
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from common import Client, DB, HOME, INDEX, REPO, SOURCE, resources, save

STOP = False


def stop(*_):
    global STOP
    STOP = True


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4 << 20), b''):
            h.update(block)
    return h.hexdigest()


def mapping(identity):
    props = {k: {'type': 'keyword'} for k in ('chunk_id', 'vector_id', 'document_id', 'source_hash', 'source_shard', 'native_shard', 'file', 'section', 'form', 'body_sha256', 'vector_sha256')}
    props.update({k: {'type': 'integer'} for k in ('line', 'section_start', 'section_end', 'start_char', 'end_char')})
    props.update({
        'body': {'type': 'text', 'analyzer': 'standard', 'index_options': 'positions'},
        'title': {'type': 'text', 'analyzer': 'standard'},
        'company': {'type': 'text', 'analyzer': 'standard', 'fields': {'exact': {'type': 'keyword', 'ignore_above': 1024}}},
        'filing_date': {'type': 'date', 'format': 'strict_date'},
        'embedding': {'type': 'dense_vector', 'dims': 1536, 'similarity': 'cosine', 'index': True,
                      'index_options': {'type': 'int8_hnsw', 'm': 16, 'ef_construction': 100}},
    })
    return {'settings': {'number_of_shards': 1, 'number_of_replicas': 0, 'refresh_interval': '-1'},
            'mappings': {'dynamic': 'strict', '_meta': identity, '_source': {'excludes': ['embedding']}, 'properties': props}}


class Vectors:
    def __init__(self, path):
        self.file = open(path, 'rb')
        self.raw = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            self._parse()
        except Exception:
            self.close()
            raise

    def _parse(self):
        magic, version, reserved, endian, length, dims, count, queries, flags = struct.unpack_from('<8sHHIQIIII', self.raw)
        if (magic, version, endian, length, dims, reserved, flags) != (b'LUMEVEC1', 1, 0x01020304, len(self.raw), 1536, 0, 0):
            raise ValueError('Unsupported/corrupt native vector header')
        self.dims, self.count, self.queries = dims, count, queries
        pos = 40
        metadata = []
        for _ in range(3):
            size, = struct.unpack_from('<H', self.raw, pos)
            pos += 2
            metadata.append(self.raw[pos:pos+size].decode())
            pos += size
        if metadata != ['text-embedding-3-small', 'document', 'query']:
            raise ValueError('Unexpected vector model/tasks')
        self.locations = {}
        for i in range(count):
            size, = struct.unpack_from('<I', self.raw, pos)
            pos += 4
            identity = self.raw[pos:pos+size].decode()
            pos += size
            if identity in self.locations:
                raise ValueError('Duplicate vector ID')
            self.locations[identity] = i
        self.offset = pos
        pos += count * dims * 4
        self.query_ids = []
        for _ in range(queries):
            size, = struct.unpack_from('<I', self.raw, pos)
            pos += 4
            self.query_ids.append(self.raw[pos:pos+size].decode())
            pos += size
        self.query_offset = pos
        if pos + queries * dims * 4 != len(self.raw):
            raise ValueError('Vector length mismatch')

    def get(self, identity):
        offset = self.offset + self.locations[identity] * self.dims * 4
        return self.raw[offset:offset+self.dims*4]

    def close(self):
        self.raw.close()
        self.file.close()


def vector_wire(blob):
    values = array.array('f')
    values.frombytes(blob)
    if sys.byteorder != 'little':
        values.byteswap()
    if len(values) != 1536 or not all(math.isfinite(v) for v in values):
        raise ValueError('Invalid vector')
    norm = sum(v*v for v in values)
    if not 0.9 < norm < 1.1:
        raise ValueError(f'Unexpected embedding norm squared {norm}')
    # Elasticsearch base64 float vectors use big-endian IEEE754 bytes.
    if sys.byteorder == 'little':
        values.byteswap()
    return base64.b64encode(values.tobytes()).decode()


def metadata(row, native, blob):
    row = dict(row)
    company, rest = row['title'].removeprefix('Company: ').rsplit(' | Form: ', 1)
    form = rest.split(' | Filed: ', 1)[0]
    date = str(row['filing_date'])
    out = {k: row[k] for k in ('file', 'line', 'document_id', 'source_hash', 'section', 'section_start', 'section_end', 'start_char', 'end_char', 'title', 'body')}
    if len(row['body']) != row['end_char'] - row['start_char']:
        raise ValueError('Invalid source text offsets')
    out.update(chunk_id=f"{row['document_id']}:{row['line']}", vector_id=native['id'],
               source_shard=row['shard'], native_shard=native['native_shard'], company=company, form=form,
               filing_date=f'{date[:4]}-{date[4:6]}-{date[6:]}',
               body_sha256=hashlib.sha256(row['body'].encode()).hexdigest(),
               vector_sha256=hashlib.sha256(blob).hexdigest())
    return out


def document(row, native, blob):
    return {**metadata(row, native, blob), 'embedding': vector_wire(blob)}


def bulk(client, docs):
    payload = b''.join((json.dumps({'index': {'_index': INDEX, '_id': d['chunk_id']}}, separators=(',', ':')) + '\n' +
                        json.dumps(d, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode() for d in docs)
    for attempt in range(6):
        result = client.request('POST', '/_bulk', payload, ndjson=True)
        items = result.get('items', [])
        if len(items) != len(docs):
            raise ValueError('Incomplete bulk response')
        failed = []
        for doc, item in zip(docs, items):
            status = item['index']
            if status.get('_id') != doc['chunk_id']:
                raise ValueError('Bulk response ID mismatch')
            if status['status'] >= 300:
                if status['status'] not in (429, 502, 503, 504):
                    raise RuntimeError(f'Permanent bulk item failure: {status}')
                failed.append(doc)
        if not failed:
            return len(payload)
        if attempt == 5:
            raise RuntimeError('Transient bulk item failures exhausted retries; checkpoint preserved')
        docs = failed
        payload = b''.join((json.dumps({'index': {'_index': INDEX, '_id': d['chunk_id']}})+'\n'+json.dumps(d, allow_nan=False)+'\n').encode() for d in docs)
        time.sleep(min(2**attempt, 20))


def run(args):
    DB.mkdir(parents=True, exist_ok=True)
    lock = (DB/'ingestion.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    started = time.monotonic()
    config = json.loads((SOURCE/'config.json').read_text())
    verification = json.loads((SOURCE/'final-vector-verification.json').read_text())
    if not config['complete'] or not verification['passed'] or config['chunks'] != verification['chunks']:
        raise ValueError('Source ingestion/vector validation incomplete')
    identity = {'schema': 'sec-elasticsearch-ingestion/1.0', 'source_config_sha256': sha256(SOURCE/'config.json'),
                'source_sqlite_sha256': sha256(SOURCE/'chunks.sqlite'), 'corpus_sha256': config['source_sha256'],
                'chunks': config['chunks'], 'documents': config['documents'], 'dimensions': 1536,
                'embedding_model': config['embedding_model'], 'index_type': 'int8_hnsw', 'm': 16, 'ef_construction': 100}
    client = Client()
    info = client.request('GET', '/')
    exists = client.request('GET', '/_cat/indices?format=json&h=index,uuid')
    if INDEX not in [x['index'] for x in exists]:
        client.request('PUT', '/'+INDEX, mapping(identity))
    actual = client.request('GET', f'/{INDEX}/_mapping')[INDEX]['mappings']['_meta']
    if actual != identity:
        raise ValueError('Existing index input/config mismatch')
    index_uuid = client.request('GET', f'/{INDEX}/_settings')[INDEX]['settings']['index']['uuid']
    state_path = DB/'ingestion-state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'identity': identity, 'index_uuid': index_uuid, 'shards': {}, 'api_cost_usd': 0, 'embedding_api_calls': 0, 'active_seconds': 0}
    if state['identity'] != identity or state['index_uuid'] != index_uuid:
        raise ValueError('Checkpoint does not belong to current source/index')
    conn = sqlite3.connect(f'file:{SOURCE}/chunks.sqlite?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('PRAGMA cache_size=-16384')
    total = conn.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
    filings = conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
    if (total, filings) != (config['chunks'], config['documents']):
        raise ValueError('Source count mismatch')
    if state.get('status') in ('ready','indexed_pending_validation') and state.get('completed_chunks')==total:
        actual_count=client.request('GET',f'/{INDEX}/_count')['count']
        embedded=client.request('POST',f'/{INDEX}/_count',{'query':{'exists':{'field':'embedding'}}})['count']
        if actual_count!=total or embedded!=total:
            raise ValueError('Completed index coverage changed')
        conn.close()
        print(json.dumps({'status':state['status'],'resume':'already indexed; zero indexing writes',
                          'chunks':total,'vectors':embedded,'api_cost_usd':0}),flush=True)
        return
    save(DB/'config.json', {'identity': identity, 'index': INDEX, 'endpoint': 'http://127.0.0.1:19200', 'elasticsearch': info, 'source': str(SOURCE.relative_to(REPO)), 'gold_in_index': False})
    initial = sum(x['completed'] for x in state['shards'].values())
    session_completed = 0
    initial_active = state['active_seconds']

    def checkpoint(status):
        elapsed = time.monotonic()-started
        state.update(status=status, updated_at=datetime.now(timezone.utc).isoformat(), pid=os.getpid(),
                     completed_chunks=sum(x['completed'] for x in state['shards'].values()), total_chunks=total,
                     active_seconds=initial_active+elapsed, session_seconds=elapsed, session_chunks=session_completed,
                     chunks_per_second=session_completed/elapsed if elapsed else None,
                     eta_seconds=(total-initial-session_completed)*elapsed/session_completed if session_completed else None,
                     resources=resources())
        save(state_path, state)
        print(json.dumps({k:state[k] for k in ('status','completed_chunks','total_chunks','session_seconds','chunks_per_second','eta_seconds','resources')}), flush=True)

    checkpoint('ingesting')
    try:
        for shard in config['shards']:
            name = shard['name']
            saved = state['shards'].get(name)
            if saved and saved['completed'] == shard['chunks']:
                continue
            path = SOURCE/shard['index']/'local-vectors.bin'
            digest = sha256(path)
            if digest != config['vector_hashes'][name]:
                raise ValueError('Native vector checksum mismatch')
            desc = SOURCE/'embedding-batches'/f'{name}.jsonl'
            desc_hash = sha256(desc)
            if saved and (saved['vector_sha256'] != digest or saved['descriptor_sha256'] != desc_hash):
                raise ValueError('Source shard changed since checkpoint')
            saved = saved or {'completed':0, 'vector_sha256':digest, 'descriptor_sha256':desc_hash}
            state['shards'][name] = saved
            vectors = Vectors(path)
            try:
                if vectors.count != shard['chunks']:
                    raise ValueError('Vector/chunk coverage mismatch')
                docs = []
                seen = set()
                count = 0
                with desc.open() as f:
                    for number, line in enumerate(f):
                        native = json.loads(line)
                        key = (Path(native['file']).name, native['line'])
                        if key in seen:
                            raise ValueError('Duplicate descriptor source identity')
                        seen.add(key)
                        count += 1
                        if number < saved['completed']:
                            continue
                        if STOP:
                            checkpoint('paused')
                            return
                        while resources()['MemAvailable_mib'] < 1024:
                            checkpoint('waiting_for_ram')
                            time.sleep(5)
                            if STOP:
                                checkpoint('paused')
                                return
                        if shutil.disk_usage(DB).free < 10 << 30:
                            raise RuntimeError('Less than 10 GiB free; checkpoint retained')
                        row = conn.execute('SELECT * FROM chunks WHERE file=? AND line=?', key).fetchone()
                        if row is None:
                            raise ValueError('Unmapped descriptor')
                        native['native_shard'] = name
                        docs.append(document(row, native, vectors.get(native['id'])))
                        if len(docs) == args.batch_size:
                            bulk(client, docs)
                            saved['completed'] += len(docs)
                            session_completed += len(docs)
                            docs = []
                            checkpoint('ingesting')
                            if args.limit and initial+session_completed >= args.limit:
                                checkpoint('paused_at_limit')
                                return
                    if docs:
                        bulk(client, docs)
                        saved['completed'] += len(docs)
                        session_completed += len(docs)
                        checkpoint('ingesting')
                if count != shard['chunks'] or saved['completed'] != count:
                    raise ValueError('Shard descriptor count mismatch')
            finally:
                vectors.close()
        checkpoint('validating')
        client.request('PUT', f'/{INDEX}/_settings', {'index': {'refresh_interval': '5s'}})
        client.request('POST', f'/{INDEX}/_refresh')
        client.request('POST', f'/{INDEX}/_flush')
        actual_count = client.request('GET', f'/{INDEX}/_count')['count']
        embedded = client.request('POST', f'/{INDEX}/_count', {'query':{'exists':{'field':'embedding'}}})['count']
        if actual_count != total or embedded != total:
            raise ValueError(f'Final index coverage mismatch: {actual_count}, {embedded}, expected {total}')
        checkpoint('indexed_pending_validation')
        save(DB/'ingestion-report.json', {'status':'indexed_pending_validation','chunks':actual_count,'vectors':embedded,
             'identity':identity,'active_seconds':state['active_seconds'],'api_cost_usd':0,'embedding_api_calls':0,
             'stats':client.request('GET',f'/{INDEX}/_stats/docs,store,segments'), 'source_files_modified':False})
    except Exception as error:
        state['error'] = str(error)
        checkpoint('error')
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-size', type=int, default=256)
    parser.add_argument('--limit', type=int, help='Pause at a batch boundary for an ingestion trial; same index resumes')
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1024:
        parser.error('batch-size must be 1..1024')
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    run(args)
