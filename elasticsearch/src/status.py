"""Read local ingestion progress without starting jobs or making model calls."""
import json
import subprocess
from common import Client, DB, INDEX, resources

if __name__ == '__main__':
    path = DB/'ingestion-state.json'
    state = json.loads(path.read_text()) if path.exists() else {'status':'not_started'}
    print(json.dumps({k:v for k,v in state.items() if k not in ('identity','shards')}, indent=2))
    print('Current host resources:', json.dumps(resources()))
    result = subprocess.run(['docker','stats','sec-rag-elasticsearch','--no-stream','--format', '{{json .}}'], capture_output=True, text=True, timeout=15)
    print('Elasticsearch container:', result.stdout.strip() or result.stderr.strip())
    try:
        stats = Client().request('GET', f'/{INDEX}/_stats/docs,store,segments', retries=0)
        print('Index measurements:', json.dumps(stats['_all']['primaries']))
    except Exception as error:
        print('Index not yet available:', str(error))
