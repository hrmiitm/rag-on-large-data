# BM25 RAG benchmark

From the repository root:

```bash
# The full database is already built; this resumes/verifies setup.
lume/bm25/src/.venv/bin/python lume/bm25/src/setup.py

# Local validation of all 50 questions: no generation calls, no answer writes.
lume/bm25/src/.venv/bin/python lume/bm25/src/eval.py --check-retrieval

# Tiny live API check, through Foundry's OpenRouter route only.
lume/bm25/src/.venv/bin/python lume/bm25/src/eval.py --check-endpoints

# Full evaluation: 50 questions, no judge or answer-quality scoring.
lume/bm25/src/.venv/bin/python lume/bm25/src/eval.py \
  --model google/gemini-3.8-flash --thinking-level HIGH --batch-size 5

# Random pilot (the effective seed and selected IDs are saved).
lume/bm25/src/.venv/bin/python lume/bm25/src/eval.py --sample-size 5 --seed 2715824471

# Fresh full evaluation: clears only the two output files, never the database.
lume/bm25/src/.venv/bin/python lume/bm25/src/eval.py --fresh

# Fill eventually available generation metadata without regenerating answers.
lume/bm25/src/.venv/bin/python lume/bm25/src/eval.py --refresh-metadata
```

Configure models with repeatable `--model` or comma-separated `RAG_MODELS`.
Use namespaced OpenRouter IDs. Credentials come from the repository `.env`
and environment using `.env.example`. The only generation URL is
`LLMFOUNDRY_BASE_URL + /openrouter/v1/chat/completions`; generation statistics
use `/openrouter/v1/generation?id=...`. There are no direct Gemini/OpenAI or
direct OpenRouter-host calls. HIGH maps to `reasoning.effort=high`; usage
accounting is requested with `usage.include=true`.

## Data and RAM

Only the prepared `financial_sections.parquet` is copied and indexed. The six
source archives remain untouched. The database contains 10,469 filings and
640,745 retained-text chunks, using 800-token windows with 100-token overlap.
`questions.jsonl` contains only `id`, `question`, and `as_of`; references and
expected answers are excluded from prompts and indexes.

The original monolithic build was OOM-killed. The replacement streams Parquet
with Arrow and builds 33 Lume indexes sequentially. Native processes have a
2 GB address-space cap and a free-RAM preflight. Indexes are never loaded
concurrently. The small `native/` adapter uses unmodified, pinned Lume source,
applies full-corpus BM25 statistics, and merges scores at full precision.
Regression checks match an unsharded native index. Retrieval is batched to
share index loading; model HTTP requests are separate concurrent calls.

Runtime dependencies are in `requirements.txt`. The local Rust toolchain,
Lume binary, dependency source, caches and virtual environment stay in `src/`.
`db/` contains copies, indexes, offsets, global statistics and readiness reports.

## Common JSONL contract

`../q-a.jsonl` is validated against `benchmark.schema.json` before atomic writes.
Its `schema_version` is `rag-benchmark/1.0`. Use the same field names and schema
for future hybrid, dense, graph-assisted, hierarchical and agentic experiments;
change `method`, named scores, queries and trace stages as appropriate.

One question record contains:

- `question_id`, `question`, `as_of`, `method`, `run_id`, configuration hash,
  timestamps and provenance, including corpus/index/code fingerprints.
- `retrieval.queries`: actual search text, cutoff filters, query ID, stage and k.
- `retrieval.chunks`: **all** retrieved chunk IDs, full text, rank, named scores,
  document IDs, source hashes, archive filenames, sections and original offsets.
  Chunk IDs are deterministic from filing ID, hash and original boundaries.
- `context`: exact passage block sent, selected chunk IDs and citation-marker
  map. Chunks excluded by the context budget remain in `retrieval.chunks`.
- `answers[model]`: requested and returned model, provider, final answer, status,
  finish reasons, citation markers mapped to chunk IDs, full usage, generation
  ID and generation metadata. Unresolved citation markers are recorded without
  grading them.
- `answers[model].api_calls`: every generation retry and metadata request,
  sanitized exact request body, raw and parsed response, allowed response
  headers, HTTP status, error, call/run IDs, stage, timestamps and duration.
- `metrics`, `errors` and extensible `trace`. No correctness score is computed.

Requests/responses are journaled immediately in `../raw-eval.log`; context is
saved before inference and each completed answer is written atomically.
Completed calls resume without repeating inference. Re-executed results keep
older calls/results in `attempt_history`. Measurements describe the latest
execution including its automatic retries; history and raw logs retain prior
executions for lifetime-cost analysis. In-flight requests interrupted before
answer persistence remain in raw logs. No reference answer is sent.
Deleting both `q-a.jsonl` and `raw-eval.log` is also supported: they are recreated
automatically. Deleting just the log does not discard completed answers. An
ordinary full run after a five-question pilot resumes the remaining questions;
use `--fresh` for a consistent new 50-question benchmark.

## Recorded measurements

P0 fields are `total_time_seconds`, `retrieval_time_ms`,
`llm_generation_time_ms`, `api_cost_usd`, `input_tokens`, `output_tokens`,
`llm_api_calls`, `tool_calls`, `db_queries`, and `documents_retrieved`.
Each answer carries measurements; the question aggregate counts shared
retrieval once and combines requested models.

Additional data includes reasoning/cache/visible tokens, retries and wait,
metadata/total HTTP-call counts, backend/scoring time, retrieval batch size,
unique filings, context chunk count, peak retrieval RAM, provider timing,
request/generation IDs, native finish reason and all returned usage/routing,
cache, billing and generation fields. OpenRouter completion tokens already
include reasoning: do not add reasoning twice. Cached tokens remain part of
input totals. Reported `usage.cost` takes precedence over generation
`total_cost`, which takes precedence over explicitly labelled fallback prices.

`retrieval_time_ms` is the full batch wall latency experienced by that question;
queries share index loading, so do not sum it as CPU time. Per-query computation
is separate in `query_scoring_time_ms`. Tool calls count a question's logical
retrieval; raw logs identify shared physical batch calls. DB counts distinguish
native shard searches from source-metadata lookups. LLM duration includes HTTP
retries and excludes metadata lookup.
Parallel model durations can sum to more than total wall time. End-to-end
answer latency stops when final answer text is available. Optional statistics
collection is measured separately and does not inflate answer latency.

Generation statistics are collected sequentially **after** generation for the
selected questions finishes. Immediate concurrent 404 polling caused the proxy's
`too_many_errors` rate limiter during the live pilot. Metadata 404s are now
deferred without immediate retries; a metadata 429 pauses the collector.
Generation statistics may arrive after inference. Missing values remain null
with availability/completeness flags, and metadata failure does not discard an
answer. `--refresh-metadata` only issues GET requests for missing statistics.
True client TTFT is not measured for non-streaming requests and stays null.
`pricing.json` is only a configurable estimate fallback; it is never presented
as a reported OpenRouter charge. API limits, outages, truncation and delayed
metadata remain possible; errors are recorded, retried where appropriate,
and preserved for later review.
