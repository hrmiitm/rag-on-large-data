# Six-method judge completion — 3 November 2026

All six methods completed 50/50 judgments (300 total), using `anthropic/claude-sonnet-5.5`, low reasoning, temperature 0 and 4096 maximum output tokens. Two method processes ran at once with five question workers each; the observed peak was ten simultaneous requests. The measured HTTP window was 199.337251 seconds. No generation/embedding/retrieval work was rerun.

Reported judging cost was **$12.268684**, within the separate **$14** cap. Earlier answer generation cost was $5.29044809; combined recorded cost is $17.55913209. All 300 judge requests returned HTTP 200 with valid complete scores/explanations; no retries were required.

| Method | Judged answers | Judge API cost (USD) |
| --- | --- | --- |
| hybrid-rerank | 50/50 | 2.022024 |
| hyde | 50/50 | 2.058224 |
| rrf | 50/50 | 2.062820 |
| rrf-rerank | 50/50 | 2.025912 |
| self-reflective-rag | 50/50 | 2.070848 |
| semantic-rerank | 50/50 | 2.028856 |

Thirty offline tests passed. Final validation checked all compact schemas, full gold evidence, exact source/final-answer/context matching, preserved serving metrics, judge settings and score ranges, source hashes, cost receipts and the shared ledger. All six source answer files and all four prior judge exports remained byte-identical. Read-only resume checks reported zero pending judgments for each method.

See [final-report.json](final-report.json) for per-method costs, separate metric means, source/export hashes and validation. The six compact result JSONL files are under `../../final-results/`. Audit JSONL and locks remain directly under `judge/`; budget/progress/test/report artifacts stay in this validation directory. No website deployment or Git operation was performed.

## Spending control

The campaign launcher `run.py` sets `RAG_JUDGE_BUDGET_LEDGER` to this directory’s existing `budget.json`, with a $14 shared cap. Never delete/reset it to resume this capped campaign. Every POST attempt, including retries, obtains a durable reservation before transmission, with cross-process locking and conservative UTF-8 input-byte/output-token bounds. Outstanding calls count against admission. At temporary saturation workers wait for existing requests to settle; unaffordable requests are recorded without sending HTTP. Missing/ambiguous costs remain reserved. Explicit authentication/credit/access rejection stops further admissions. All current requests have returned cost receipts and no reservations remain.

The guard admits only concurrent Sonnet 5.5 judging, with provider prices capped at $3/M input, $15/M output and zero request surcharge. Observed model rates at preflight were $2/M input and $10/M output; the saved model-list snapshot is `model-pricing.json`. This uses Foundry’s OpenRouter route exclusively. Native asynchronous batch submissions are intentionally outside this campaign guard. The default unguarded runner behavior remains available when this campaign environment variable is absent.

Requests explicitly send `Cache-Control: no-cache`, and cache-related response headers are logged. Model settings, gold rubrics and judge task fingerprints are unchanged by these transport/spending controls. Native batch jobs accepted by earlier work were left alone.

These are rubric-based model scores; validation establishes correct execution/data handling, not human agreement with every score.


## Publication metadata cleanup

After the successful judging checkpoint above, account/tracking diagnostics were removed from all ten public compact exports. Their answers, scores, evidence and metrics were preserved; original full method files were not edited. The earlier byte-identical comparison refers to the end-of-judging checkpoint, before this deliberate export-only cleanup. Current hashes and the explicit cleanup exception are in [final-report.json](final-report.json) and [../publication-report.json](../publication-report.json). The judge suite now has 31 passing tests, including a regression proving account fields are omitted while operational statistics and private local source data are retained.
