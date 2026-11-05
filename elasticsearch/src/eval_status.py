"""Read-only progress and budget summary for the Elasticsearch agent run."""
from collections import Counter
import json
from common import DB, HOME

def summary():
    path=HOME/'q-a.jsonl'
    records=[json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    answers=[a for r in records for a in r['answers'].values()]
    ledger=json.loads((DB/'budget-ledger.json').read_text()) if (DB/'budget-ledger.json').exists() else {'attempts':{}}
    attempts=list(ledger['attempts'].values())
    return {'questions_saved':len(records),'answer_status':dict(Counter(a['status'] for a in answers)),
            'metadata_status':dict(Counter(a['metadata_status'] for a in answers)),
            'generation_calls_checkpointed':sum(a.get('metrics',{}).get('llm_api_calls',0) for a in answers),
            'reported_api_cost_usd':sum(a.get('reported_cost_usd',0) for a in attempts),
            'accounted_or_reserved_usd':sum(a['accounted_usd'] for a in attempts),
            'budget_limit_usd':15,'evaluation_limit_usd':7,
            'active_reserved_requests':sum(a['status']=='reserved' for a in attempts),
            'halted':ledger.get('halted'),'new_embedding_api_calls':0}

if __name__=='__main__':print(json.dumps(summary(),indent=2))
