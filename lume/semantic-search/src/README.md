# Lume semantic and hybrid SEC experiments

`semantic-search` ranks the prepared SEC chunks by **native Lume exact cosine similarity only**. `hybrid` uses native Lume's default multiplicative fusion: `BM25 * (1 + 0.5 * cosine)` for lexical matches, or cosine for semantic-only candidates. Graph boost is disabled. Neither method is agentic, graph retrieval, a reranker or an approximate vector index. Setting Lume's ordinary `alpha=1` does not make its default hybrid formula pure semantic search; the adapter explicitly omits the lexical input for the semantic experiment.

Both methods share one embedding database under `lume/semantic-search/db/`. Hybrid has its own configuration, runtime, lock, log and `q-a.jsonl`; its immutable index/metadata paths reference that shared database. There is one embedding pass, rather than paying for two copies of the same vectors. The two experiments must stay together when moving the workspace.

## Corpus and storage

The input is only the prepared `data/financial_sections.parquet`: 10,469 filings, 640,745 existing 800-token body chunks, 100-token overlap, 33 shards. Semantic refers to embedding retrieval; this experiment deliberately preserves the baseline chunk boundaries. Short company/form/date/document prefixes accompany retained text. Original source hashes, filing dates and character offsets remain in `chunks.sqlite` and all retrieved benchmark records. Original Parquets and existing BM25/agentic outputs are not changed.

To save local CPU, setup takes independent filesystem copies (reflinks where supported; never writable hard links) of the pinned baseline lexical index and chunk map. It checks the prepared Parquet SHA-256 and **every one of the 640,745 original text slices** before embedding. This is a validated ingestion snapshot, not using another method's answers, retrieval results or gold evidence. The existing complete BM25 database is a prerequisite for this fast setup path. Native searches use stored sections and do not walk the original corpus directory.

Embeddings use **`openai/text-embedding-3-small`, 1,536 float32 dimensions**, exclusively at `LLMFOUNDRY_BASE_URL/openrouter/v1/embeddings`. Credentials use root `.env`/environment and are never logged. Shivvr normally provides embeddings for Lume; here Foundry supplies the vectors, and the adapter opens Lume's native `LocalVectors` binary format (`LUMEVEC1`) as a checked sidecar beside each copied immutable shard. No Shivvr container, local model download or running embedding server is required. The pinned Lume model profile uses `text-embedding-3-small` without its OpenRouter provider prefix because that profile disallows slashes; API receipts preserve the full routed model ID.

Question-only texts are embedded separately into a **query cache**, never into document vectors or lexical postings. Query-cache setup costs are recorded with ingestion; evaluation performs zero embedding HTTP calls on a cache hit. Actual evaluation serving costs therefore cover generation requests. The one-time corpus/query-cache costs are available separately, not silently included as repeated per-answer charges.

The uncompressed document vectors require approximately 3.94 GB (decimal), plus small native IDs/headers/query caches. Ingestion streams only a bounded number of text batches into RAM. Binary batch caches can span shards and are deleted only after native coverage validation. If RAM pressure delays native sealing, up to approximately another corpus-vector pass (about 4 GB) may remain temporarily on disk. Small identity/usage receipts remain. `embedding-audit.jsonl` records sanitized request hashes, returned model/provider/IDs, usage/cost, retries and errors; it does not duplicate the multi-gigabyte response vectors as JSON.

## Run and resume

From the repository root:

```bash
uv venv lume/semantic-search/src/.venv
uv pip install --python lume/semantic-search/src/.venv/bin/python -r lume/semantic-search/src/requirements.txt

# All stages: shared ingestion, both 50-question runs, then both judges.
PYTHONDONTWRITEBYTECODE=1 nice -n 10 ionice -c 2 -n 7 lume/semantic-search/src/.venv/bin/python -u lume/semantic-search/src/run_all.py --embedding-concurrency 64 --adaptive-embeddings

# Or run individual stages. Keep batch size 256 when resuming this cache.
PYTHONDONTWRITEBYTECODE=1 lume/semantic-search/src/.venv/bin/python lume/semantic-search/src/setup.py --concurrency 6 --batch-size 256
PYTHONDONTWRITEBYTECODE=1 lume/semantic-search/src/.venv/bin/python lume/semantic-search/src/eval.py --batch-size 5
PYTHONDONTWRITEBYTECODE=1 lume/semantic-search/src/.venv/bin/python lume/hybrid/src/eval.py --batch-size 5
PYTHONDONTWRITEBYTECODE=1 lume/semantic-search/src/.venv/bin/python judge/eval.py semantic-search --mode concurrent --concurrency 5
PYTHONDONTWRITEBYTECODE=1 lume/semantic-search/src/.venv/bin/python judge/eval.py hybrid --mode concurrent --concurrency 5
```

The current workspace includes an independent Rust toolchain/cache, pinned Lume source and release binary copied from the baseline for this adapter. Builds use one job and an offline Cargo dependency cache. No dependencies are installed into an existing experiment's environment. On a clean machine, restore that pinned source/toolchain or provision Rust and the dependency cache before building the adapter.

Setup defaults to six requests; the accelerated supervisor command uses an adaptive ceiling of 64 requests with 256 inputs per request (below 300,000 aggregate tokens for these chunks), with durable per-batch receipts and validated finite, nonzero, 1,536-dimensional vectors. Failed or ambiguous HTTP attempts remain in the audit. Resume skips validated batches/shards; an interruption between an accepted remote response and the local checkpoint can still require repeating that batch. This is not an exactly-once billing guarantee. `--prepare-only` copies/validates data and builds the adapter without embedding API calls. Do not change the embedding batch size mid-ingestion: batch identities deliberately reject mismatches.

The bounded cross-shard queue removes the old request barrier: later shards can embed while an earlier shard waits for its final API response. SQLite reads stream at batch granularity; full shard text lists are not retained. Native index opens are serialized across setup and both methods and limited to a 2 GiB virtual address space. Queries are batched across all selected questions into one sequential shard pass. Cutoffs filter the complete semantic candidate set **before** top-k selection. Global corpus statistics keep BM25 scores comparable across shards. Missing vectors/query caches fail closed, with no lexical fallback.

The accelerated pool starts at 16 requests and ramps by eight every ten healthy seconds, up to 64. A machine-wide memory-stall reading around 2% no longer collapses this network-bound pool when several GiB remain available. It halves new admissions at five-second intervals below 2,048 MiB available RAM, above 1,024 MiB process RSS, or when stall pressure reaches 5% with less than 3,072 MiB available. It stops new admissions below 1,536 MiB available RAM, above 1,536 MiB process RSS, or at 15% stall pressure with less than 2,560 MiB available. Recovery ramps require at least 2,560 MiB available and process RSS below 768 MiB. Active responses still checkpoint. HTTP 429, or three transient failures within 30 seconds (including 502/503/504 and transport truncation/timeouts), caps new admissions at four for 60 seconds. A shared HTTP gate also limits already-queued retries, waits at least 15 seconds after a burst of errors, honors numeric Retry-After up to 120 seconds, and gradually restores HTTP concurrency. Outstanding batch futures and actual in-flight HTTP requests are shown separately. These guards aim to preserve responsiveness but cannot control memory/CPU used by other applications. The provided command lowers CPU and I/O priority.

`db/embedding-control.json` can set `{"concurrency_limit": 32}` (an integer from 1 through the configured maximum) to change the live ceiling without restarting or cancelling in-flight requests; use an atomic file replacement. The current live ceiling is 32 after the 64-request trial produced many gateway 502 and truncated-response errors. A ceiling is not a throughput guarantee; keep the live guard enabled. Invalid control updates retain the previous valid ceiling and appear as `control_error` in the runtime report. Request receipts include sanitized upload/wait-to-headers, download, decode and validation timings plus byte counts, without headers or vector duplication.

The current run also uses `resource_lease.py` to temporarily pause a measured, heavily contending KDE `baloo_file_extr` process. It uses SIGSTOP/SIGCONT without changing desktop settings or files. The detached watcher restores that exact process (checking its name and process start time) when ingestion completes, pauses, fails, its supervisor exits, or after at most 90 minutes. SIGTERM/SIGINT to the watcher also restores it. A process already paused before the lease is left untouched. `db/resource-lease.json` records its watcher/indexer IDs and lifecycle; the live monitor shows an active lease. This is an optional machine-specific resource measure, not a prerequisite for ingestion on other machines.

Before a native process starts, the runner requires 2,304 MiB of available system RAM. If memory is below that threshold, it now waits and rechecks every 15 seconds, keeping all saved embeddings and the existing native cap. The monitor displays the RAM wait and withholds ETA until memory recovers; no other applications are stopped. A previous fail-fast memory check stopped this run on November 3; its state was preserved in `db/pipeline-before-memory-recovery.json`, and ingestion resumed using the cached batches.

The answer pool continuously dispatches up to `--batch-size` HTTP requests per method after the shared retrieval pass. The supervisor runs both methods with five workers each (ten answering requests total), using `google/gemini-3.8-flash`, HIGH reasoning, top 10 chunks, 12,000 context tokens and 8,192 output tokens. Answer-ready timings include the shared retrieval pass and actual pool queue time. Retrieval batching and concurrency are saved measurements, not a guarantee of lower per-question latency. The supervisor defers optional metadata collection until both methods finish generation, then serializes lookups across the methods. Standalone runs can use `--defer-metadata` followed later by `--refresh-metadata`. Changing answer concurrency does not change the retrieval configuration hash.

Both `q-a.jsonl` files use the byte-identical `rag-benchmark/1.0` schema and preserve all retrieved text, scores, offsets, citation maps, supplied context, sanitized generation requests/responses, attempts, usage/cost and timings. Completed answers resume; `--fresh` resets only that method's answer file and raw log. It does not erase vectors. `--sample-size`, `--seed`, `--refresh-metadata`, `--check-retrieval` and `--check-endpoints` follow the baseline runner's semantics. A retrieval check uses the already-embedded question cache and makes no new generation calls.

The supervisor waits for **50 successful, nontruncated answers in each method** before judging. For faster wall-clock completion it explicitly selects the existing judge's concurrent mode, five requests per method, Claude Sonnet 5.5 low/temperature 0. Its accepted native batch state and other experiments are left alone. Compact exports go to:

- `judge/final-results/q-a-eval-lume-semantic-search.jsonl`
- `judge/final-results/q-a-eval-lume-hybrid.jsonl`

The existing website discovers both exports automatically at its next build. No website edits, Git operations or publication are part of this pipeline.

## Status and verification

Truncated HTTP/JSON/gzip responses and retryable network failures retain their attempt/error audit and retry up to six times through the shared gate. Unknown remote acceptance/usage stays unknown. Exhausted transient failures exit with code 76 after workers drain; the supervisor waits 60 seconds and resumes cached work up to three times. Permanent errors do not trigger this recovery loop. Authentication, model, vector-dimension and validity checks remain strict.

The supervisor now supports graceful SIGINT/SIGTERM: it stops admitting batches, lets active requests checkpoint, and records `paused` without launching later stages. Resume with the accelerated command above.

For a readable live monitor, run this from the repository root (Ctrl+C exits only the monitor):

```bash
watch -n 10 'lume/semantic-search/src/.venv/bin/python lume/semantic-search/src/status.py'
```

For a single snapshot, omit `watch -n 10` and the quotes. Add `--json` for machine-readable output. The monitor reads existing files only; it makes no API calls and does not control the running jobs. It shows embedding-response progress separately from verified native storage, current/target/maximum request concurrency and pressure backoff, answer/judgment counts, reported costs, resource samples, and a live ingestion ETA in IST. Cost projection extrapolates observed embedding cost per vector and uses the existing completed BM25 model/judge averages for the additional 100 answers and 100 judgments. ETA compares recent two-minute and ten-minute current-session rates after warmup; historical throughput includes earlier settings and pauses and does not drive the live forecast. It excludes later answering, metadata and judging and is not a confidence interval or completion guarantee.

`db/pipeline-state.json` is the live supervisor status: stage, process IDs, exit codes, resource samples and final counts. Progress logs live in the method folders; `db/source-validation.json`, per-shard `vectors-ready.json`, `db/embedding-report.json` and `db/readiness.json` contain measured checks. A pending stage is not a completed benchmark. Inspect status before starting another supervisor. `run_all.py --wait-for-ingestion-pid PID` adopts an already-running ingestion rather than issuing duplicate work.

```bash
PYTHONDONTWRITEBYTECODE=1 lume/semantic-search/src/.venv/bin/python -m unittest discover -s lume/semantic-search/src -p 'test_*.py' -v
```

Offline tests cover native cosine and hybrid formula/cutoff behavior, missing-query failure, batch-cache resume/corruption, and a 50-question simulated driver run with bounded parallelism, atomic schema-validated outputs, citation/score preservation, zero-generation resume and fresh reset. These tests are separate from a full paid embedding, answering or judging run. See `VALIDATION.md` for the recorded implementation review.


Sources: [pinned Lume native vectors](https://github.com/DeepBlueDynamics/lume/blob/f031390f0f4afdeeb14d609775ce51617d1a3f2c/src/local_vectors.rs), [pinned hybrid fusion](https://github.com/DeepBlueDynamics/lume/blob/f031390f0f4afdeeb14d609775ce51617d1a3f2c/src/hybrid.rs), [OpenRouter embeddings request](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request), and [official OpenAI embedding documentation](https://developers.openai.com/api/docs/guides/embeddings).
