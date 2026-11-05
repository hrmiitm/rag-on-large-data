"""Local-only Elasticsearch transport and atomic checkpoints; no model API support."""
import http.client
import json
import os
import time
from pathlib import Path

HOME = Path(__file__).resolve().parents[1]
REPO = HOME.parent
DB = HOME / 'db'
SOURCE = REPO / 'lume/semantic-search/db'
INDEX = 'sec-financial-chunks-v1'
PORT = 19200


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


class Client:
    def __init__(self):
        self.conn = None

    def request(self, method, path, body=None, ndjson=False, retries=5):
        payload = body if isinstance(body, bytes) else json.dumps(body, allow_nan=False).encode() if body is not None else None
        for attempt in range(retries + 1):
            try:
                if self.conn is None:
                    self.conn = http.client.HTTPConnection('127.0.0.1', PORT, timeout=300)
                self.conn.request(method, path, body=payload, headers={'Content-Type': 'application/x-ndjson' if ndjson else 'application/json'})
                response = self.conn.getresponse()
                raw = response.read()
                data = json.loads(raw) if raw else {}
                if response.status in (429, 502, 503, 504):
                    raise OSError(f'HTTP {response.status}: {str(data)[:1000]}')
                if response.status >= 400:
                    raise RuntimeError(f'{method} {path}: HTTP {response.status}: {str(data)[:2000]}')
                return data
            except (OSError, http.client.HTTPException):
                if self.conn:
                    self.conn.close()
                self.conn = None
                if attempt == retries:
                    raise
                time.sleep(min(2 ** attempt, 20))


def resources():
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemAvailable', 'SwapFree'):
            values[key + '_mib'] = int(value.split()[0]) / 1024
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(('VmRSS:', 'VmHWM:')):
            key, value = line.split(':', 1)
            values[key + '_mib'] = int(value.split()[0]) / 1024
    return values
