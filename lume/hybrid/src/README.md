# Lume hybrid SEC experiment

This folder has independent answer outputs, logs, runtime, configuration and locks. It reuses the one paid native vector database under `lume/semantic-search/db/` through explicit read-only retrieval paths. Do not copy or rebuild a second embedding set.

The method uses Lume's native global-BM25 plus cosine multiplicative blend, `alpha=0.5`, graph boost `0`. It differs from pure cosine search and from agentic orchestration over lexical retrieval. Full method definitions, preparation/resume commands, metrics, storage/resource limits and verification are in [the shared pipeline guide](../../semantic-search/src/README.md).

```bash
# Build/finish the shared ingestion first.
PYTHONDONTWRITEBYTECODE=1 lume/semantic-search/src/.venv/bin/python lume/hybrid/src/setup.py --concurrency 6 --batch-size 256

# Generate all 50 answers, then judge them.
PYTHONDONTWRITEBYTECODE=1 lume/semantic-search/src/.venv/bin/python lume/hybrid/src/eval.py --batch-size 5
PYTHONDONTWRITEBYTECODE=1 lume/semantic-search/src/.venv/bin/python judge/eval.py hybrid --mode concurrent --concurrency 5
```

`run_all.py` in the shared guide already schedules both experiments and both judges; do not start competing runs while that supervisor is active. Check `lume/semantic-search/db/pipeline-state.json` for actual completion.
