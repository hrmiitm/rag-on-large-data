# Isolated Lume agentic-search benchmark

This experiment builds its own full index from `data/financial_sections.parquet`.
It never reads a sibling experiment's corpus, index, question outputs or database.
Original data is read-only. The local Parquet is an ordinary independent copy.

The two entry points are `setup.py` and `eval.py`. Run from the repository root:

```bash
# Already installed and ingested; this resumes safely if interrupted.
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/setup.py

# Local retrieval validation; makes no LLM calls.
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --check-retrieval

# Tiny live model tool-call + continuation test, not a benchmark question.
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --check-endpoints

# Fresh 50-question evaluation: five concurrent questions by default, no judge/scoring.
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --fresh --batch-size 5

# Ten concurrent questions (native index searches still run one at a time).
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --fresh --batch-size 10

# Resume existing completed/pending answers with ten workers instead of restarting.
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --batch-size 10

# Optional five random questions; retain the printed seed to reproduce selection.
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --sample-size 5 --seed 123

# Metadata can be delayed. This only fetches statistics; it does not regenerate answers.
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --refresh-metadata
```

The default is `google/gemini-3.8-flash`, HIGH reasoning, using ONLY
`LLMFOUNDRY_BASE_URL/openrouter/v1/chat/completions`. Credentials come from the
repository `.env` or environment, with the names documented in `.env.example`.
Use `--model owner/model` (repeatable) or `RAG_MODELS` to configure models.
There is no model fallback. Each model runs its own independent searches/context.

## Method

The pinned upstream source is Lume v0.16.3, commit
`f031390f0f4afdeeb14d609775ce51617d1a3f2c`. Its
[`agent.rs::run_agent_loop`](https://github.com/DeepBlueDynamics/lume/blob/f031390f0f4afdeeb14d609775ce51617d1a3f2c/src/agent.rs)
uses Ollama for an iterative tool conversation. This implementation adapts that
loop to the required Foundry/OpenRouter protocol and benchmark logging. It uses
native Lume lexical retrieval, not the unmodified Ollama CLI agent. It does not
add embeddings, reranking or graph retrieval to this technique.

1. Send only the question/cutoff and general research instructions to the model.
2. Require a first `lume_search` call. Execute it against this experiment's index.
3. Return numbered passages. The model may refine/decompose queries and search again.
4. `lume_not_found` supplies guidance when evidence is insufficient.
5. The model produces a cited final answer or explains missing evidence.

Tools are read-only; models cannot select files, databases or dates. The server
always applies `filing_date <= as_of`, checks each returned filing, and validates
tool arguments. Upstream index-mutation and prose-generation tools are deliberately
excluded from this financial evaluation. Gemini's opaque reasoning details/thought
signatures are retained when continuing tool conversations.

## Corpus and resource bounds

Only prepared MD&A and financial statements/notes are ingested: **10,469 filings,
16,141 section spans, 640,745 chunks**, 800 body tokens / 100 overlap, reset per span.
Questions, answers, reference evidence and documentation are never indexed.
`src/questions.jsonl` has only `id`, `question`, `as_of` for the 50 questions.

Setup streams one Parquet row at a time. Native indexes hold at most 20,000 chunks
per shard (33 shards); whole filings remain together. Each native index/search
process has a 2 GiB address-space cap. Global corpus BM25 statistics make shard
scores comparable. Indexes are opened and dropped sequentially. The native helper
calls the pinned, unmodified Lume search library; its Rust source and vendored Lume
source are included. Executable copies are independent ordinary files, not links.
Compiled tools were reused as software artifacts; all experiment data was rebuilt
from the original prepared Parquet.

Defaults per question/model: 6 model turns including the final answer, 6 searches,
8 total tool invocations, 5 chunks per search, 16,000 cumulative evidence tokens,
8,192 completion tokens per model turn (reasoning included). The last turn disables
tools. Repeated passages refer to their existing citation marker. Every retrieved
chunk is recorded even if it does not fit the evidence budget.

Five question agents run concurrently by default. Set `--batch-size 5` or
`--batch-size 10` (alias `--concurrency`; allowed range 1..10). A continuously
filled thread pool starts the next question as soon as a worker becomes free;
it does not wait for the slowest question in a fixed batch. This overlaps model
network waits. A shared retrieval dispatcher coalesces up to that many queued
searches into **one native shard pass**, instead of making each question reload
all 33 indexes separately. It waits up to 250 ms for arrivals (configure with
`--search-batch-wait-ms 0..1000`), and searches accumulated during an active pass
join the next pass together. Each shard is still loaded/dropped sequentially in
a single bounded native process. Every query keeps its own date cutoff, hits,
scores, citation mapping and source lookups. A batch releases its question
workers together so their next model calls can overlap. Models on the same
question run sequentially. Provider response times and rate limits still affect
wall-clock speed. The memory-availability
check fails safely if other workloads leave insufficient headroom. Search timeouts
and model HTTP retries are bounded. These measures reduce OOM risk; external API
failures and other applications consuming RAM cannot be guaranteed away.

The full experiment needs approximately 8.5 GB for the database plus its source,
Python dependencies and executables. Setup requires at least 12 GiB free before a
new full export. Build progress is in `db/setup.log`; shard build logs are in
`db/stats/`. `db/validation-report.json` records measured sizes and checks.

Validated build: about **8.51 GB** allocated for `db/`, **0.31 GB** for `src/`.
All 50 local retrieval checks passed (peak native RSS **792 MiB**). One live random
pilot (`q012`, seed `20261103`) completed with Google Gemini 3.8 Flash HIGH through
Foundry/OpenRouter: **3 model turns, 2 searches, 31.08 seconds, $0.01466775** reported
cost, no errors, and metadata available for all turns. Resume made zero extra HTTP
calls. A 50-question simulated agent run and failure/budget tests passed; the full
live 50-question evaluation has not been run. Use `--fresh` for that official run.

## Output and resume

The root contains exactly `db/`, `src/`, `raw-eval.log`, `q-a.jsonl`.
`q-a.jsonl` uses the same `rag-benchmark/1.0` schema as BM25, with `method: agentic`.
The schema file is byte-identical across the two experiments.

Each row records question and final answer; model/provider/configuration; every
retrieved chunk's exact text, stable ID, source hash, original offsets, filing
date, BM25 score and per-query occurrences; each model's actual supplied context,
stable citation map and citations; all tool arguments/results/errors; the exact
sanitized API requests, raw/parsed responses, HTTP attempts, usage and available
OpenRouter generation metadata for EVERY model turn. Top-level `context` uses the
first model's numbering for compatibility; `context.by_model` and each answer's
`context` are authoritative for multiple models.

P0 metrics: end-to-end active answer time, retrieval time, LLM generation time,
reported/estimated USD cost, input/output tokens, LLM invocations, tool calls,
DB operations and chunks retrieved. Additional metrics include query occurrences
versus unique chunks/filings, supplied context count/tokens, per-tool and queue
timing, peak native RSS, agent rounds, retries/waits, reasoning/cache tokens,
metadata HTTP calls and completeness flags. Operational measurements are not
answer-quality scores. API cost covers every model turn and retry with available
usage. Unknown values remain null; estimates are labelled. OpenRouter completion
tokens already include reasoning tokens and are never double-counted. Full
provider statistics are retained per call rather than collapsed across providers.

`tool_calls` counts handled model-requested tool invocations (including rejected
ones); requested/executed/succeeded/failed/rejected counts are separate. DB queries
count native shard searches plus source SQLite lookups; a failed search with an
unknown operation count produces null, not a fabricated zero. End-to-end and LLM
timing exclude deferred metadata enrichment; retrieval queue time is separate.
A resumed partial conversation accumulates active elapsed time across sessions,
excluding downtime. Multiple models' active times add at question level.

Each question owns its mutable conversation and record; a shared writer lock
publishes deep-copied snapshots atomically, fsyncs them and validates the schema.
All scheduled pending questions are recorded before workers begin. Execution
provenance records question concurrency, retrieval batch size/window and the native search cap;
completion output includes each question/model status independently. Metadata
collection starts only after every question worker finishes. Changing concurrency
does not change the benchmark configuration hash, so a prior one-worker run can
resume with five or ten workers. Interrupted/fatal runs cancel queued questions;
active agents checkpoint before starting another model turn when signaled.
Per-tool metrics include the actual `retrieval_batch_size`, `retrieval_process_shared`
and `retrieval_batch_id`. Queue wait includes time awaiting a shared pass; retrieval
time records that query's observed batch wall time. Shared batch wall time/RSS
should not be summed as independent native-process resource use; the batch ID
allows deduplication. Logical shard searches and source-lookup counts remain
per query, as before.
A checkpoint follows every model response and every tool execution. A pending conversation resumes its saved turns
and pending tools; completed answers are skipped. Failed executions are preserved
in `attempt_history` when retried. A crash while a remote request is in flight may
require a new call because its response was never received/saved. Metadata GETs
are sequential after generation, deferred on 404, and paused on 429 to avoid the
Foundry circuit breaker.

To start again, use `--fresh`, or delete only `raw-eval.log` and `q-a.jsonl` and run
`eval.py`; both files are recreated. Keep `db/` and `src/`. To remove this experiment,
delete only `lume/agentic-search/`; no source data or BM25 experiment is needed by it.
Do not run setup and eval simultaneously for the same experiment; a database lock
enforces this. Do not run the full paid 50-question evaluation just to validate
installation. See `db/readiness.json`, `db/endpoint-readiness.json` and
`db/validation-report.json` for what has actually been checked.

## Concurrency validation

```bash
PYTHONDONTWRITEBYTECODE=1 lume/agentic-search/src/.venv/bin/python -m unittest discover -s lume/agentic-search/src -p 'test_eval_concurrency.py' -v
```

The offline suite uses temporary experiment directories and simulated model/retrieval
calls. It checks 50-question runs at five and ten workers, schema-valid checkpoints
without dropped/mixed records, continuous scheduling past a slow question, sequential
models within a question, one native search at a time even with ten workers, completed
resume without new calls, pending/error history, queued-work cancellation, default/CLI
limits, fresh-output reset with metadata deferred until all workers finish, shared
ten-query retrieval, batching arrivals during a pass, propagation of batch failures
to every waiter, and the actual agent loop with ten simultaneous HTTP requests
both before and after one shared retrieval pass. It
makes no paid model calls and does not reset the real benchmark outputs or indexes.

`src/retrieval-batching-validation.json` records a real local ten-query comparison:
ten separate passes versus a shared pass, exact chunk/rank/score equality, date
cutoffs, memory measurements and unchanged production-output hashes. That check
uses no model API calls; its retrieval speedup is not a claim of the same speedup
for a complete live generation run.

The measured ten-query check took **78.279 seconds** as ten separate passes versus
**8.015 seconds** as one shared pass (**9.77x faster retrieval**), with identical
ordered chunk IDs/scores and enforced date cutoffs. Shared-pass peak native RSS
was **802.4 MiB** under the unchanged 2 GiB cap. Production outputs were unchanged;
no model calls were made. All **15 offline tests passed**.
