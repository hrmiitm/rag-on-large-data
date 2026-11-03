# Repository guide

This project evaluates RAG techniques on SEC filings. Use the prepared financial sections as the retrieval corpus and keep evaluation answers outside the index.

## Files

| File | Purpose |
| --- | --- |
| `AGENTS.md` | Brief instructions and file map for agents working here. |
| `.gitignore` | Keeps reference questions, source/docs and compact results; excludes credentials, corpus/indexes, runtime downloads and raw audit files. |
| `README.md` | Project entry point and original-data download commands. |
| `data/README.md` | Exact corpus rule, embedding instructions, measured sizes, cost assumptions and validation command. |
| `data/sfd-v1-2025-01.parquet` | Original January 2025 filings, containing multiple filing types. |
| `data/sfd-v1-2025-02.parquet` | Original February 2025 filings. |
| `data/sfd-v1-2025-03.parquet` | Original March 2025 filings. |
| `data/sfd-v1-2025-04.parquet` | Original April 2025 filings. |
| `data/sfd-v1-2025-05.parquet` | Original May 2025 filings. |
| `data/sfd-v1-2025-06.parquet` | Original June 2025 filings. |
| `data/financial_sections.parquet` | Prepared, deduplicated 10-K/10-Q corpus: 10,469 filing rows containing actual retained text and source metadata. |
| `data/questions.jsonl` | 50 reference questions, answers and supporting evidence; five categories, including 10 multi-document questions. |
| `scripts/prepare_sec_sections.py` | Canonical local extraction, token-counting, cost simulation and question-evidence validation helper. It makes no embedding API calls. |
| `lume/bm25/src/setup.py` | Builds/resumes the complete BM25 corpus as memory-bounded Lume shards. |
| `lume/bm25/src/eval.py` | Runs all 50 questions through configurable OpenRouter models via LLM Foundry; records measurements without answer scoring. |
| `lume/bm25/src/benchmark.schema.json` | Common `rag-benchmark/1.0` JSONL contract for BM25 and future RAG methods. |
| `lume/bm25/src/README.md` | Commands, field definitions, memory strategy and logging details. |
| `lume/bm25/db/` | Copied corpus, source offsets, 33 native indexes, global BM25 statistics and readiness reports. |
| `lume/bm25/q-a.jsonl` | Schema-validated question records, retrieved chunks, exact context, model answers, API attempts, metadata and operational metrics. |
| `lume/bm25/raw-eval.log` | Append-only model-labelled request/response, retrieval, retry and error audit log. |
| `lume/bm25/db/pilot-report.json` | Audit of the five-question live pilot, measured sizes/cost/latency, logging checks and known retrieval limitations. |
| `lume/agentic-search/src/setup.py` | Independently copies/ingests the prepared corpus into the agentic experiment's own bounded Lume indexes. |
| `lume/agentic-search/src/eval.py` | Model-directed search/refinement through Foundry/OpenRouter; uses the common benchmark schema and no judge. |
| `lume/agentic-search/src/README.md` | Agentic commands, limits, method, metric semantics and resume details. |
| `lume/agentic-search/src/test_eval_concurrency.py` | Offline isolated tests for 5/10 question workers, serialized retrieval, atomic checkpoints, resume and fresh runs. |
| `lume/agentic-search/db/validation-report.json` | Actual ingestion/isolation/resource measurements and verification results. |
| `judge/eval.py` | Separate gold-reference judge: accepts a method folder, defaults to Claude Sonnet 5.5 low/temperature 0 via Foundry's OpenRouter Batch API, writes `judge/final-results/q-a-eval-lume-<folder>.jsonl`. |
| `judge/README.md` | Judge commands, four score rubrics, enriched output fields, batch/concurrent modes and resume/error handling. |
| `judge/evaluation.schema.json` | Compact `rag-presentation/1.0` output schema; original method inputs still use the common benchmark schema. |
| `judge/final-results/` | Final enriched benchmark JSONL files; the discovery source for GitHub Pages. Keep audit logs, batch state and locks outside this directory. |
| `judge/sample_test.py` | Read-only BM25/agentic snapshots and isolated live judge calibration samples; writes only under `judge/validation/`. |
| `judge/PAGES_HANDOFF.md` | Minimal Pages data/code handoff, automatic method discovery, metric semantics and size analysis. |
| `website/README.md` | Website setup, presentation rules, data flow and GitHub Pages deployment instructions. |
| `website/src/App.tsx` | Shared filters, simple top navigation and the overview/question/judge/methodology views. |
| `website/src/ComparisonMatrix.tsx` | First overview table: retrieval strategies as columns; quality, cost, latency and other metrics as rows. |
| `website/src/Charts.tsx` | One selected interactive chart at a time: quality/cost, latency, categories, heatmap or resources. |
| `website/src/Explorer.tsx` | Question tables and lazy answer, citation, evidence, execution and provenance inspection. |
| `website/src/style.css` | Centered layout, readable system typography, light/dark themes and responsive presentation. |
| `website/scripts/build-data.mjs` | Discovers and validates final exports, normalizes model evaluations and writes versioned static data assets. |
| `website/scripts/local-evidence.mjs` | Optional read-only passage enrichment, matched to original snapshot identifiers, source hashes and offsets. |
| `website/scripts/watch-data.mjs` | Development watcher for automatic result-data regeneration and page reloads. |
| `website/tests/` | Isolated data/watcher, DOM interaction and Plotly adapter checks; fixtures never become benchmark results. |
| `website/VALIDATION.md` | Recorded verification and explicit browser/visual-review limitations. |
| `.github/workflows/benchmark-pages.yml` | Tests, rebuilds discovered result files and deploys static assets through GitHub Pages. |

## GitHub Pages results discovery

- `judge/` is a top-level shared evaluation component, separate from the method implementations under `lume/`. Keep its runner, schemas, validation artifacts and `final-results/` together there.
- GitHub Pages must iterate through **all `.jsonl` files present in `judge/final-results/`**. Do not hard-code individual filenames, index methods by a fixed filename list, or maintain a manual results registry. Newly added result files must appear automatically on the next site build.
- Derive each displayed method name from the entire filename portion **after `eval-`**, removing the final `.jsonl` extension. For example, `q-a-eval-lume-bm25.jsonl` becomes **`lume-bm25`**, and `q-a-eval-lume-agentic-search.jsonl` becomes **`lume-agentic-search`**. Preserve all hyphens in that suffix; do not take only the last hyphen-separated word. Use this derived name for Pages comparisons rather than the record's original `method` field.
- Discover files at build time (for example, a sorted `judge/final-results/*.jsonl` glob). If the browser needs a manifest, generate it automatically from that discovery; do not rely on HTTP directory listings or hand-written filename arrays.
- Presentation exports use **`rag-presentation/1.0`**. Retain full gold evidence passages and metadata once in `gold_evidence`, gold calculations/reasoning/answer points in `gold_details`, all recorded record/answer/retrieval/tool/judge metrics, usage/cost, answers, evaluation scores/explanations, identifiers and compact error/retry history. Keep retrieval IDs/ranks/scores/source offsets and citation maps. Omit raw API requests/responses, raw JSON strings, model reasoning/messages, traces, repeated retrieved/context text and the full repeated index configuration. Never compact or overwrite original method `q-a.jsonl` files; these remain complete `rag-benchmark/1.0` audit records. `python judge/eval.py <folder> --export-only` regenerates the compact export without API calls, preserving valid saved judge results; missing scores stay null/pending.
- Store only final result JSONL files in `final-results/`. Judge `.audit.jsonl`, `.state.json` and `.lock` artifacts belong directly under `judge/` and must not be included as result datasets.

## Benchmark website presentation and maintenance

- Preserve the user's simple reference-inspired presentation: a centered page, standard system fonts (16px body/answers and 17px main table on desktop), clear headings and restrained borders. Keep the main page concise: shared filters, the first comparison table and one selected chart. Secondary statistics, findings and detailed comparisons start collapsed; question exploration and methodology have separate navigation views. Extra metadata columns remain available through table controls.
- The **first overview table must have retrieval strategies as columns and metrics/perspectives as rows**. Its default rows are answer correctness, faithfulness, context relevance, answer relevance, average serving API cost, average answer-ready latency, average total tokens and judged-answer coverage. `More metrics` exposes additional recorded operational measurements. Do not revert to model settings as the rows or combine cost and correctness into a single value.
- Discover strategy columns from all valid final-result JSONL files, using the complete filename suffix after `eval-`. The table follows the same global category, method, model, status, search and numeric-range filters as the charts and explorer.
- Keep models, reasoning/output settings, corpus/question-set hashes and retrieval configurations distinct. Show separately labeled tables for different model/settings groups; if a method has multiple retrieval configurations within a group, show labeled values within that method's cell. Never silently pool these configurations or average model-level means.
- Recompute every metric from individual filtered evaluations. Quality uses valid completed judgments; cost, latency and token averages use their own measured denominators. Show sample counts on hover and coverage explicitly. Missing values stay N/A/Not Evaluated; pending, skipped, error and missing judgments never become zero quality scores. Clicking a value opens that method/model/configuration's questions.
- Serving cost excludes judge overhead. Answer latency prefers per-model `answer_ready_time_seconds`; metadata enrichment stays separate. Total tokens equal input plus output because reasoning tokens are already included in output. No arbitrary composite quality score or unmatched-question winner claims.
- The React/TypeScript/Vite frontend uses Plotly and TanStack Table. Keep static deployment, query-string filter links, hashed data assets, automatic file discovery and the development watcher. Optional original method files may supply only exactly matched retrieved passages through read-only snapshots; final exports remain authoritative for answers, scores and metrics. Do not rerun retrieval, generation or judging for website edits.
- From the repository root, use `npm --prefix website run dev` for local development, `npm --prefix website test` for data/watcher checks and `npm --prefix website run test:ui` for DOM/Plotly adapter checks. Build the repository-path artifact with `PAGES_BASE_PATH=/rag-on-large-data/ npm --prefix website run build`; use the same variable with `run preview` when inspecting that artifact. The GitHub workflow derives the actual Pages base path at deployment time.
- Keep generated `website/public/data/`, `website/dist/` and dependencies out of Git. Update `website/README.md` and `website/VALIDATION.md` when behavior or verification changes. DOM/adapter tests do not establish browser visual or touch-device correctness; report any unavailable browser review explicitly.
- Website work must leave active method/judge jobs and their source, outputs, environments, databases and locks alone. Do not initialize Git, use the `gh` CLI, commit, push or publish unless the user explicitly requests the relevant action.

## Corpus and embedding rules

- Embed only `sections[].text` from the prepared Parquet. Preserve filing IDs, hashes, dates and original character offsets as metadata.
- One filing row is one logical document: exporting one text file per row produces **10,469 files**. There are **16,141 section spans**, not 16,141 independent filings. Separate spans within a filing can be chunked independently.
- Retained text per filing totals at least **10,000 tokens**; the measured minimum is 10,020 and median is 34,293. Individual spans can be shorter.
- The rule selects annual/quarterly filings and retains recognized MD&A and financial statements/notes. It does not retain every complete 10-K/10-Q. See `data/README.md` and the helper for exact thresholds and boundaries.
- The baseline uses `text-embedding-3-small`, 800-token body chunks, 100-token overlap, short filing prefixes and 1536-dimensional float32 vectors. Its simulated embedding cost is about **$10.59 per pass**; database storage is an **estimate of 9–15 GB**, not a measured built index.
- Keep the six original Parquets unchanged. Keep questions, reference answers and documentation outside the retrieval index. Revalidate evidence after changing extraction rules or questions; recount costs after changing chunking or models.

## Rebuild and validate

Dependencies: `duckdb` and `tiktoken`. From the repository root:

```bash
python scripts/prepare_sec_sections.py \
  --output data/financial_sections.parquet \
  --validate-questions data/questions.jsonl
```

Preparation is local. The helper verifies that every reference evidence passage is inside the retained corpus and checks recorded arithmetic; it does not independently prove all narrative answers or run a judge model.

## Lume BM25 benchmark

- The full prepared corpus is built: **10,469 filings / 640,745 chunks / 33 indexes**. The original monolithic build was killed at about 8 GB RSS. Keep the sequential shard design and 2 GB per-native-process address-space cap; do not restore a monolithic build or load indexes concurrently. The adapter uses global corpus statistics to preserve comparable native BM25 scores.
- Original `data/` files remain unchanged. Setup makes an independent prepared-Parquet copy under `db/`. `src/questions.jsonl` contains only `id`, `question`, and `as_of`; reference answers/evidence must never enter prompts or indexes.
- **Use only LLM Foundry's OpenRouter route**: `LLMFOUNDRY_BASE_URL + /openrouter/v1/chat/completions`. No direct Gemini/OpenAI routes or direct OpenRouter host calls. Read credentials from repository `.env`/environment using `.env.example`; never print/store authentication headers.
- The separate judge in `judge/` also uses Foundry's `/openrouter/v1/batches` and `/openrouter/v1/batches/<id>` for native batch submission/polling (or the chat-completions route in explicit concurrent mode). Only the judge receives gold answers/evidence from root `data/questions.jsonl`; preserve their exclusion from retrieval and answer-generation prompts. Keep accepted batch state to prevent duplicate paid jobs after interruption. Its default model is `anthropic/claude-sonnet-5.5`, low reasoning effort, temperature 0.
- Default model: **`google/gemini-3.8-flash`**, HIGH reasoning effort. Configure with `--model` (repeatable) or `RAG_MODELS`. Question and selected SEC passages are sent; no judge or answer-quality scoring runs.
- All methods must use the same `rag-benchmark/1.0` output naming/schema: `method`, `question_id`, `retrieval`, `context`, `answers`, `metrics`, `errors`, `trace`, `provenance`. Preserve **all** retrieved chunk texts, stable IDs, ranks, named retrieval scores, source hashes and original offsets; distinguish them from context actually sent and map citation markers to chunk IDs.
- Save full sanitized API requests/responses and attempt history in `q-a.jsonl`, not only raw logs. Save returned usage/cost, generation/request IDs, actual model/provider, finish reasons and available generation metadata. Metadata may arrive late; `--refresh-metadata` performs GET lookups without new generation calls. Missing values remain null, with availability/completeness flags. Do not invent TTFT for non-streaming requests or call price estimates actual billed cost.
- Record end-to-end, retrieval and generation times; cost; input/output/reasoning/cache tokens; LLM/metadata HTTP calls; retries; tool/DB operations; returned/context chunk counts; and RAM. OpenRouter completion tokens already include reasoning—never add reasoning twice. Reported `usage.cost` takes precedence over configured fallback prices.
- Retrieval is batched while indexes remain sequential; model calls are separate concurrent requests (default batch size 5). Writes are atomic and schema-validated. Completed answers resume; failed executions remain in `attempt_history` and raw logs. Do not promise zero external API errors.
- Use `--sample-size 5` for a uniform random pilot; `--seed` reproduces the sample. Selection IDs/seed are logged and saved in provenance. Without sampling flags, all 50 questions are selected. Sampling never drops other saved question records.
- `--fresh` resets only `q-a.jsonl` and `raw-eval.log` under the database lock. Deleting both files manually also works; missing output files are recreated. Keep `db/` and `src/` to avoid re-ingestion.
- Collect OpenRouter generation metadata sequentially after all selected generation calls finish, not concurrently inside each answer. Defer metadata 404 and pause on metadata 429 to avoid the proxy's `too_many_errors` circuit breaker. End-to-end answer latency excludes metadata enrichment; provider and metadata timings remain separate.
- `tool_calls=1` is the local retrieval wrapper for a question, not an LLM-issued function call. Plain BM25 RAG uses no model tools; requested/executed model-tool counts are separate. Normally each question searches 33 shards and performs ten source lookups (43 DB operations).

```bash
lume/bm25/src/.venv/bin/python lume/bm25/src/setup.py
lume/bm25/src/.venv/bin/python lume/bm25/src/eval.py --check-retrieval
lume/bm25/src/.venv/bin/python lume/bm25/src/eval.py --check-endpoints
lume/bm25/src/.venv/bin/python lume/bm25/src/eval.py --model google/gemini-3.8-flash --thinking-level HIGH --batch-size 5
lume/bm25/src/.venv/bin/python lume/bm25/src/eval.py --refresh-metadata
```

Local checks have covered all 50 retrievals, native global-BM25 equivalence, and a 50-question fixture run with retries/errors/resume and metric validation. Endpoint smoke tests are separate from the **full live 50-question LLM evaluation**, which must not be claimed complete until actually run. See `db/readiness.json` for current checks.

The live five-question pilot used seed **2715824471** and IDs **q032, q037, q065, q070, q085**. All five generation calls completed without generation retries; reported total model cost was **$0.06383325**. Two answers reported insufficient retrieved evidence; their reference filings are present in the corpus, so this is a retrieval limitation, not missing ingestion or an API failure. No judge/accuracy score was run. Initial concurrent statistics polling caused metadata 404/429 errors; all five statistics records were later collected, and the deferred sequential collector prevents those lookups from interrupting generation. Grouped/range citation parsing, missing-output recreation, fresh-run reset and resume were tested. A normal full run now resumes the remaining 45 questions; use `--fresh` for a consistent new 50-question benchmark with the corrected collection/timing policy.

## Lume agentic-search benchmark

- `lume/agentic-search/` contains exactly `db/`, `src/`, `raw-eval.log`, `q-a.jsonl`. Its data, indexes, statistics, Python dependencies and executable copies are independent of BM25. Setup reads the original prepared Parquet and original questions only; never source data from another experiment.
- The agent loop adapts pinned Lume `agent.rs::run_agent_loop` (Ollama upstream) to the required Foundry/OpenRouter protocol. Actual LLM-issued `lume_search` calls use native lexical retrieval; models can refine/decompose queries and request `lume_not_found` guidance. This is agentic orchestration over BM25, with no dense/graph/reranking component. The distinction must remain clear in comparisons.
- The corpus/chunking and memory-safe shard strategy match the BM25 baseline. Hard date cutoffs apply to every search. Tools are read-only; models cannot choose filesystem paths, databases or cutoff overrides. Preserve opaque reasoning details/signatures during tool continuations.
- Defaults: five concurrent questions, six model turns including the final answer, six searches, eight total tool calls, five chunks per search, 16,000 cumulative evidence tokens, 8,192 output tokens per turn. The final turn disables tools. `--batch-size` (alias `--concurrency`) may be 1..10. The continuous worker pool fills free slots immediately. A shared retrieval dispatcher coalesces up to that many queries into one native pass, with `--search-batch-wait-ms` default 250 (0..1000); shards are still loaded/dropped sequentially under one native-process lock. Models for the same question execute sequentially with independent contexts.
- Use the byte-identical `rag-benchmark/1.0` schema (`method: agentic`). Save every search's chunk texts, stable IDs, scores, source offsets, query occurrences, exact supplied contexts/citation maps, tool arguments/results and every model turn's raw API request/response/usage/metadata. Each answer contains its own `retrieval` and `context`; `context.by_model` disambiguates independent citation numbering.
- Costs/tokens aggregate all turns/retries without double-counting reasoning. Model turns are not retries. Requested/executed/succeeded/failed/rejected tool counts are separate. Failed DB operations with unknown counts remain null. Active answer time excludes metadata enrichment and downtime between resumed sessions; model times add for sequential models.
- Checkpoint after every model response and tool execution. Resume pending conversations without repeating saved turns; retain failed attempts when restarting them. `--fresh`, or deleting only the two output files, starts a new evaluation without ingestion. Deferred sequential metadata lookup covers EVERY model generation ID.
- Read `src/README.md` and `db/validation-report.json` for actual validation status. Do not claim a full live 50-question evaluation or zero-error guarantee from fixture/retrieval checks. Leave a user's running BM25 evaluation alone.

```bash
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/setup.py
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --check-retrieval
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --check-endpoints
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --fresh
lume/agentic-search/src/.venv/bin/python lume/agentic-search/src/eval.py --refresh-metadata
```

Agentic validation completed: 10,469 filings / 640,745 chunks / 33 indexes; approximately 8.51 GB database and 0.31 GB source/runtime. All 50 local retrievals passed at a peak native RSS of 792 MiB; all chunk lengths/offset boundaries and 128 exact source slices were checked. The one live random pilot (`q012`, seed `20261103`) used Google Gemini 3.8 Flash HIGH: three model turns, two searches, 31.08 seconds, $0.01466775 reported cost, no errors, all generation metadata available. Resume made zero new HTTP calls. The full live 50-question agentic evaluation is still unrun; start it with `--fresh` to replace this pilot output.

## Judge validation and small GitHub Pages handoff

- While the user has a benchmark running, treat `lume/bm25/` and `lume/agentic-search/` as **read-only** during judge work. Do not modify source, outputs, logs, environments, databases or locks in either method directory; do not stop or restart active jobs. Read an atomic JSONL snapshot and place tests/reports only under `judge/`. Active outputs may legitimately change due to their own writer, so record snapshot counts/hashes rather than claiming they stayed fixed.
- `judge/sample_test.py` validates read-only source snapshots; `--live` runs isolated judging samples through Foundry/OpenRouter, with the normal Claude Sonnet 5.5 low/temperature 0 settings. The live sample comprises one completed answer per method plus four calibration cases using root gold references: supported correct answer, contradicted wrong answer, gold-correct answer with unrelated context, and justified abstention. These check correctness/faithfulness separation and JSON validity; they do not establish full-benchmark accuracy or guarantee model judgement correctness. Sample outputs must stay outside `final-results/` so Pages does not list them as a method.
- Run offline judge tests with `PYTHONDONTWRITEBYTECODE=1 lume/bm25/src/.venv/bin/python -m unittest discover -s judge -p 'test_*.py'`. Reuse the existing interpreter read-only or install judge dependencies in a separate environment; never install packages into an active method's environment. `sample_test.py --live --mode batch` verifies native batching and `--mode concurrent` verifies the synchronous parallel path. Keep accepted native sample state to resume rather than creating duplicate jobs.
- Keep only small source/docs/config/reference data and compact final exports in Git. Root `.gitignore` excludes credentials, corpus Parquets, databases, runtimes, vendor downloads, compiled binaries, full generation JSONL, raw logs and judge operational artifacts; it keeps `data/questions.jsonl`, `.env.example`, `final-results/*.jsonl` and small sanitized reports. Do not initialize Git unless the user later requests it.
- A Pages agent can build the intended comparison dashboard from `data/questions.jsonl` and **all** final-result JSONL files; no original Parquets, retrieval indexes, binaries or raw `q-a.jsonl` are required. Also provide `judge/evaluation.schema.json`, this file and `judge/PAGES_HANDOFF.md` as interpretation/build instructions. The agent must create the static frontend, automatic file-discovery manifest/build and deployment configuration; data files alone are not a deployable site. The small presentation repository cannot rerun retrieval or rejudge faithfulness without separately supplied originals/runtime.
- Pages must show missing/pending/skipped/error judgements distinctly, not as zero scores. Aggregate only completed valid scores and display coverage/denominators; keep method metrics separate from judging overhead. Gold evidence is retained; retrieved passage text and exact prompt/API replay are intentionally unavailable in compact exports.

Judge sample verification (2026-11-03): the 25 offline tests passed. All 50 BM25 records and the then-current active agentic snapshot passed compact JSON schema, full gold evidence, metric preservation and per-model context checks. The six live concurrent samples completed with all four calibration cases passing; reported total usage cost was $0.126956, with no generation retries. Both actual source samples also produced valid compact JSONL and resumed with zero new calls. Native batch sample acceptance/completion is tracked separately; do not claim completion until `judge/validation/sample-batch-report.json` says `passed`. See the small reports under `validation/`; no full 50-question judge evaluation or human accuracy guarantee is implied.

Native sample collection status: the Foundry/OpenRouter batch was accepted with six requests and remains `validating` after the bounded local collection window; `judge/validation/sample-batch-report.json` is explicitly `pending`, not a passed native-generation test. Relocating the judge preserved this accepted ID and resumed polling with exactly one total submission. Resume with `PYTHONDONTWRITEBYTECODE=1 lume/bm25/src/.venv/bin/python judge/sample_test.py --live --mode batch`; do not resubmit or delete its state. Six concurrent live judgements and both real compact output samples passed independently.

Agentic concurrency update: the evaluator defaults to five question workers and supports ten via `--batch-size 10` / `--concurrency 10`. Every question owns its mutable state; models within a question stay sequential, and a writer lock saves immutable snapshots without dropping other questions. A shared retrieval dispatcher batches queued queries into one shard pass under the 2 GiB process cap, avoiding repeated index loads for each waiting question. Each query preserves its cutoff, scores, sources and context. Workers overlap generation waits and continuously take queued questions; metadata enrichment remains sequential after all workers finish. Concurrency is execution provenance, not an answer/retrieval configuration-hash change, so existing answers can resume at a different worker count. `--fresh` resets only agentic `q-a.jsonl` / `raw-eval.log` under the database lock; use `--fresh --batch-size 5` or `--fresh --batch-size 10` for a new run. Concurrency tests use temporary files and no paid model calls; never claim a new full live run or a particular speedup from those fixtures.

Agentic retrieval throughput correction: the ten-worker run did reach ten simultaneous model HTTP calls, but per-question native reloads caused search queues exceeding 200 seconds. `RetrievalBatcher` now collects queued searches into one multi-query pass (up to the configured question concurrency). It releases each result to its original question/model future, keeps only one native process, and never loads shards concurrently. Requests queued during a pass are grouped for the next pass. Batch errors wake every affected waiter. The 15 offline tests include the real agent loop with ten concurrent first-turn HTTP requests, one shared ten-query retrieval and ten concurrent continuation requests, plus exact mapping, failure, checkpoint and resume tests. Actual native equivalence/timing is recorded in `lume/agentic-search/src/retrieval-batching-validation.json`; no full paid rerun is implied.

Measured retrieval check (2026-11-03): ten real queries took 78.279 seconds in separate native passes versus 8.015 seconds in one ten-query pass (9.77x local retrieval speedup). Ordered chunk IDs/scores and all date cutoffs matched exactly. Shared-pass peak native RSS was 802.4 MiB, under the existing 2 GiB cap. Production `q-a.jsonl` and `raw-eval.log` hashes were unchanged; zero model API calls were made. Fifteen offline tests passed. This is retrieval timing/equivalence evidence, not a guaranteed end-to-end model speedup.


## Lume semantic and hybrid pipeline

- `lume/semantic-search/src/README.md` defines the shared ingestion and both methods. `setup.py` independently snapshots the pinned complete lexical ingestion, validates every chunk against the original prepared Parquet, then obtains 1,536-dimensional `openai/text-embedding-3-small` vectors only through Foundry `/openrouter/v1/embeddings`. Gold fields never enter document vectors or generation prompts. Question-only query vectors are a separate native query cache.
- `lume/semantic-search/db/` owns the one shared native Lume local-vector sidecar set. `lume/hybrid/db/` has its own config/runtime/lock and explicit links to those immutable indexes and metadata. Reuse the same embeddings; do not launch another paid embedding pass for hybrid.
- Semantic search is native exact cosine, explicitly without lexical input. Hybrid is native multiplicative `BM25*(1+0.5*cosine)` with cosine-only candidate fallback, global corpus statistics and graph zero. Both use all semantic candidates, apply hard cutoffs before top-k, and open one shard at a time under a shared native-process lock and 2 GiB address-space cap.
- `run_all.py` supervises ingestion, separate 50-question `q-a.jsonl` files, and both judges. Five question workers per method overlap HTTP work, with one all-question sequential native pass per method. Generation metadata is deferred and serialized across both methods. Judge concurrent mode is explicitly selected for faster completion, using the normal Sonnet 5.5 low/temperature-0 settings. No accepted existing batch jobs are altered.
- Keep embedding batch size 256 when resuming the current cache. Per-batch receipts/native seals prevent repeating completed work; ambiguous remote acceptance is recorded, not claimed exactly-once. `db/pipeline-state.json` and generated reports establish actual live status. Offline tests/fixture outputs do not establish a completed full corpus or 50-question live run.
- Native vectors, copied corpus, generated state and operational logs stay ignored under the existing database/log rules. Only compact final exports belong in `judge/final-results/`, named `q-a-eval-lume-semantic-search.jsonl` and `q-a-eval-lume-hybrid.jsonl`. No Git staging, commit or publication is authorized by this task.


Adaptive embedding execution: the accelerated supervisor command is `nice -n 10 ionice -c 2 -n 7 lume/semantic-search/src/.venv/bin/python -u lume/semantic-search/src/run_all.py --embedding-concurrency 64 --adaptive-embeddings`. The bounded cross-shard queue streams text by batch, preserves all existing 256-input cache identities, and serializes native index work. Admission ramps and backs off based on RAM, process RSS, Linux memory pressure and HTTP 429. The status monitor shows actual and target concurrency. SIGINT/SIGTERM now drain only admitted requests to checkpoints and pause the supervisor without starting later stages. Twenty offline tests cover these behaviors, including 64-worker dispatch, live concurrency ceilings and ignoring mild machine-wide PSI when RAM headroom is adequate; do not infer a full live completion or fixed speedup from them. The maximum is 64 requests, starts at 16 and ramps by eight per ten healthy seconds; the current live ceiling is 32 because the 64-request trial encountered gateway 502/truncated-response errors. A shared HTTP gate limits already-queued retries to four during recovery, backs off on 429 or repeated transient failures and ramps gradually. Transient exhaustion exits 76; the supervisor waits 60 seconds and performs at most three checkpoint-preserving resumes. Permanent failures are not auto-retried. The current pool was measured at 753 MiB RSS with about 3.3 GiB available RAM. `db/embedding-control.json` changes the live `concurrency_limit` within the configured maximum without cancelling paid requests. Exact memory thresholds and transport timing fields are documented in the method README. ETA now uses current-session two/ten-minute windows rather than older slow settings or paused time.


Temporary desktop resource lease: this run identified heavy KDE `baloo_file_extr` paging/disk contention. `lume/semantic-search/src/resource_lease.py` temporarily pauses only the verified extractor and automatically restores its prior running state when ingestion stops/finishes, the supervisor exits, the watcher receives SIGTERM/SIGINT, or the 90-minute maximum expires. It checks process start identity to avoid signalling a reused PID and leaves pre-paused processes alone. The active IDs/lifecycle are in `db/resource-lease.json`; do not SIGKILL its watcher. The current live ceiling remains 32, with all existing native/RAM/gateway guards. Twenty-three offline tests passed, including restoration on exceptions and PID-reuse/pre-paused safeguards. Observed full memory PSI fell from about 21% to 0.01% and HTTP concurrency recovered to 32; this does not prove a fixed whole-run ETA.
