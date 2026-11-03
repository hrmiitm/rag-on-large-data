# Budgeted answer-generation campaign

Six methods run sequentially, with five question workers per method: hybrid-rerank,
HyDE, RRF, RRF-rerank, self-reflective RAG, semantic-rerank. Each uses
`google/gemini-3.8-flash`, HIGH reasoning and 8192 maximum output tokens.
No judge is included. A five-question pilot (`--sample-size 5 --seed 77`) is part
of each method's normal 50-question selection; full runs resume those answers.
Do not use `--fresh` when continuing this campaign.

Set `RAG_SPEND_LEDGER` to the absolute path of `runtime/db/eval-budget.json`
for **every** campaign process, including metadata refresh. The durable ledger
reserves a conservative request maximum before every POST attempt and accounts
for all outstanding reservations. The admission ceiling is $9.50, with $0.50
reserved below the user's $10 cap. Chat requests constrain provider rates to
$1.50/M input and $7.50/M output and zero request surcharge; observed current
rates are $0.75/M input and $3.75/M output. Payload UTF-8 bytes plus 8192 bound
input tokens; `max_tokens` bounds output including reasoning. Query-only embedding
requests reserve at least $0.01 each, substantially above the expected charge.
Only the campaign answer model and single-query `text-embedding-3-small` requests
are admitted; the guard rejects judge models and document embedding batches.

Returned `usage.cost` replaces a reservation. Missing receipts and ambiguous
remote acceptance retain the full reservation, including after process restart.
An explicit pre-generation HTTP rejection without a generation ID releases it.
Retries each reserve separately. Free sequential generation-metadata lookups can
reconcile missing cost receipts. A receipt exceeding its reservation halts further
admission. This is conservative admission control, not a claim of exactly-once
remote billing. Do not delete or reset the ledger to continue a capped campaign.

The guard is opt-in through the environment and affects only these new runners.
Native retrieval still opens shared immutable indexes sequentially under the
existing shared lock and 2 GiB process cap. Cross-encoder inference is local and
serialized; model HTTP calls overlap. Only the small query vectors needed by
HyDE or reflection can incur new embedding calls.

Offline preflight: 23 shared-runtime tests (including five budget tests), 11
self-reflective tests and all six full setup checks passed. Live completion,
reported cost, HTTP concurrency and metadata availability must be taken from the
campaign report and saved outputs, not inferred from these preflight checks.

Live transport correction: a retried truncated response returned the same generation
ID. Requests now explicitly send `Cache-Control: no-cache` and log x-cache/age.
The one hybrid-rerank transport-only signature transition is recorded explicitly
in its db/resume-compatibility.json; original response/configuration hashes and
full attempt history are retained. The conservative budget counts both returned
cost receipts even where an identical generation ID might represent cache replay.

## Completed live results

All six methods completed 50/50 answers. Total recorded API cost was **$5.29044809**, including all retries and the conservatively counted cached replay. All 495 paid attempts have cost receipts: 424 chat attempts and 71 single-query embedding attempts. All 424 chat-attempt metadata lookups succeeded with HTTP 200 and matching generation IDs. No gold-reference judge was run; these completion checks do not establish answer accuracy.

| Method | Completed answers | Recorded API cost (USD) | Peak concurrent paid HTTP requests |
| --- | --- | --- | --- |
| hybrid-rerank | 50/50 | 0.74609250 | 4 |
| hyde | 50/50 | 0.94411691 | 5 |
| rrf | 50/50 | 0.75456525 | 5 |
| rrf-rerank | 50/50 | 0.67838850 | 3 |
| self-reflective-rag | 50/50 | 1.45740168 | 5 |
| semantic-rerank | 50/50 | 0.70988325 | 3 |

The 34 offline tests passed. All six final setup checks, all 300 schema/context/source audits, RRF/reranking/reflection/token/cost integrity checks, and 12 original-method output/configuration snapshot comparisons passed. Shared vector hashes remained identical. Native RSS stayed below 1.1 GiB; the native address-space cap remained 2 GiB. Model requests overlapped within each five-worker method; native retrieval and cross-encoder inference remained serialized.

See [LIVE-RESULTS.json](LIVE-RESULTS.json) for the small measured report, output hashes and attempt/metadata accounting. Full prompts, passages, responses and retries remain in each method’s `q-a.jsonl` and `raw-eval.log`; this report is not a compact judge export.
