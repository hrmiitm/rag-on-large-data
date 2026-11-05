# Elasticsearch SEC ingestion experiment

This is a separate, local Elasticsearch ingestion of the complete prepared SEC
corpus. It reuses the already-paid `openai/text-embedding-3-small` vectors from
`lume/semantic-search/db/`, opened read-only. It makes **zero embedding,
generation or judge API calls** during ingestion. Existing methods, databases
and jobs are not modified. Evaluation and judging are separate stages.

The agent evaluator is now implemented; see [EVALUATION.md](EVALUATION.md) for
tools, five/ten-worker execution, the $15 budget, verification and current live
gateway-access history. The full live evaluation and judging subsequently
completed: **50/50 answers, 50/50 judgments, $4.463595875 total**. See
[RESULTS.md](RESULTS.md). The completed index is saved; its container is stopped
to release RAM.

## Layout

- `compose.yaml`: official Elasticsearch 9.5.6 image pinned by digest; dedicated
  container, 4 GiB RAM limit, no container swap, four CPU limit and 2 GiB heap.
- `src/setup.py`: streaming bulk import with atomic checkpoints and deterministic
  IDs. Uses Python's standard library and the official Elasticsearch REST API.
- `src/validate.py`: full original-Parquet/text verification, original embedding
  receipt checks, every indexed passage/metadata/hash association, 99 actual
  stored-vector checks and lexical/vector cutoff smoke searches.
- `src/status.py`: current progress, resource use and index measurements.
- `src/test_ingestion.py`: offline parser, serialization, mapping and error checks.
- `db/`: ignored runtime index, state, logs, query cache and measured reports.

The benchmark corpus remains **10,469 filings / 640,745 chunks**. Indexing one
chunk per Elasticsearch document preserves the original 800-token bodies,
100-token overlap and exact Markdown/table text. Original source hashes, section
boundaries and character offsets remain attached. No gold question/answer/evidence
files are loaded. The question-only native vector cache is copied only after
validation for later tools that require zero new embeddings.

## Index design

One primary shard, zero replicas, standard BM25 text analysis with positions,
company name text and exact keyword fields, form/filing IDs as keywords, proper
dates and explicit cosine `dense_vector` mappings. ANN uses `int8_hnsw`, `m=16`,
`ef_construction=100`. Quantization saves search memory but introduces a recall
tradeoff; full ANN recall/gold-evidence benchmarking remains subsequent work.
Raw vectors remain in native source files and Elasticsearch's internal vector
storage, without another large JSON copy in `_source`.

The importer reads a single native shard at a time with a read-only mmap. It
validates native vector checksums, dimensions, finite values and near-unit norms.
It streams 256 chunks per request as compact base64 float vectors, verifies every
bulk item and retries transient failures. It never silently accepts partial or
permanent failures. RAM admission waits below 1 GiB available system memory;
ingestion fails safely below 10 GiB free disk. The 4 GiB container ceiling is a
hard limit; on OOM/error fix resources and resume, rather than claiming success.

Original text is restartable input, so replicas are zero for this single-node
experiment. Refresh is disabled during import and restored to 5 seconds before
the final refresh/flush. No expensive force merge is required. An interrupted
request can be replayed safely with stable IDs; completed batches are checkpointed.
Source/config hashes and index UUIDs must match when resuming.

## Commands (repository root)

```bash
docker compose -f elasticsearch/compose.yaml up -d
PYTHONDONTWRITEBYTECODE=1 python -u elasticsearch/src/setup.py
PYTHONDONTWRITEBYTECODE=1 python elasticsearch/src/status.py

# Reuse the installed pyarrow interpreter read-only; install nothing into it.
PYTHONDONTWRITEBYTECODE=1 lume/semantic-search/src/.venv/bin/python -u elasticsearch/src/validate.py

PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s elasticsearch/src -p 'test_*.py'

# Stop the dedicated service when not needed; retain the index.
docker compose -f elasticsearch/compose.yaml stop
```

`setup.py --limit 2048` pauses at a batch boundary for a trial; run without
`--limit` to resume the same index. SIGINT/SIGTERM preserve completed batches.
Never delete `db/` to resume. A full index is not ready for evaluation until
`db/validation-report.json` has `passed: true`. The importer reports ETA from
measured current-session progress; this excludes validation and can change as
vector structures merge. A `ready` state means validated ingestion and smoke
searches, not established answer quality.

The service binds only `127.0.0.1:19200`, with security disabled solely for this
isolated local benchmark. Port 9300 is not published; no Kibana, hosted service,
inference model downloads or API credentials are needed. Host port 9200 and
unrelated containers remain untouched.

Official references: [Docker setup](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/install-elasticsearch-docker-basic),
[bulk indexing guidance](https://www.elastic.co/docs/deploy-manage/production-guidance/optimize-performance/indexing-speed),
[vector mappings](https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/dense-vector).
