# Elasticsearch agent evaluation

**Current status:** the live run is complete: 50 answers, 50 judgments, all
generation metadata available, total reported cost $4.463595875. See
[RESULTS.md](RESULTS.md) for latency, costs, scores and verification. Access
failure notes below describe historical attempts. The container was stopped
after completion to release RAM; the index is retained.

`src/eval.py` runs all 50 question-only inputs through Gemini 3.8 Flash HIGH via
LLM Foundry's `/openrouter/v1/chat/completions`, using the validated Elasticsearch
index. Default concurrency is five independent questions, configurable from one
to ten. Each question owns its conversation and citations; model/tool responses
checkpoint atomically. Completed answers resume without new generation calls.

## Agent tools and retrieval

- `search_filings`: keyword, semantic or hybrid retrieval; optional company and
  10-K/10-Q filters. Every branch enforces the server-side as-of cutoff. Hybrid
  combines top-50 lexical and top-50 vector rankings with application-side RRF
  (constant 60); ANN uses 200 candidates. Five selected passages are fetched with
  filters reapplied. Candidate IDs/ranks/scores are retained, and every fetched
  passage is retained in the benchmark audit record.
- `read_passages`: up to two previously returned passage IDs and their immediate
  neighbours in the same filing, with the same date cutoff. Arbitrary paths,
  raw Elasticsearch DSL and date overrides are not exposed to the model.
- `report_missing_evidence`: guidance when evidence is insufficient.

Semantic retrieval always uses the existing cached **original question** vector.
Rewritten query text changes keyword retrieval; company/form filters can narrow
both branches. No embedding API calls occur. This limitation is explicit in the
system/tool descriptions and provenance. Elasticsearch remains read-only during
evaluation. Gold answers/evidence are not loaded by the evaluator.

Default limits match the existing agent experiment: six model turns including
the final answer, six searches, eight total tool calls, 16,000 cumulative evidence
tokens and 8,192 output tokens per turn (including reasoning). Tools are disabled
on the final turn. Reasoning details/signatures survive tool continuations.

Outputs are `elasticsearch/q-a.jsonl` using the byte-identical
`rag-benchmark/1.0` schema and append-only `elasticsearch/raw-eval.log`. They retain
sanitized API requests/responses and attempts, tool arguments/results, exact
contexts, citation maps, stable source identities/offsets and named scores.
Metadata GET lookups are deferred until all generation workers finish and run
sequentially. Non-streaming TTFT and unmeasured Elasticsearch process RAM remain
null. Serving cost excludes judging; output tokens already include reasoning.

## Budget

`db/budget-ledger.json` caps the campaign at **$15 total** and evaluation at **$7**,
leaving $8 for judging/reserve. Each paid attempt reserves a conservative bound
before transmission, with provider prices capped at $0.75/M input and $3.75/M
output. Reported costs settle reservations; uncertain remote attempts retain the
full reservation. Rejected-before-generation requests account zero. Access/credit
rejections stop further admission. Spending history is never reset by `--fresh`.
The judge adapter shares this ledger with the existing concurrent judge guard.
Its first invocation had no eligible answers and made zero model calls.

## Commands

From the repository root, reuse the installed interpreter read-only; install no
dependencies into another experiment:

```bash
PYTHONDONTWRITEBYTECODE=1 lume/agentic-search/src/.venv/bin/python elasticsearch/src/eval.py --check-retrieval --model google/gemini-3.8-flash
PYTHONDONTWRITEBYTECODE=1 lume/agentic-search/src/.venv/bin/python elasticsearch/src/eval.py --model google/gemini-3.8-flash --thinking-level HIGH --batch-size 5
PYTHONDONTWRITEBYTECODE=1 python elasticsearch/src/eval_status.py
PYTHONDONTWRITEBYTECODE=1 lume/agentic-search/src/.venv/bin/python elasticsearch/src/eval.py --model google/gemini-3.8-flash --refresh-metadata
```

`--batch-size 10` changes only execution provenance, not retrieval configuration.
`--defer-metadata` skips the final collector until an explicit refresh. Generation
and retrieval code were adapted as independent copies of the existing agent
runner; no original experiment source, output, database, locks or environment
was changed. Tokenizer cache and question-only inputs were independently copied.

## Current verification and live blocker

All 50 actual Elasticsearch retrieval checks passed and a real neighbouring
passage read passed. Offline tests cover the real multi-turn loop at five and ten
workers, atomic checkpoints, citations, independent contexts, opaque reasoning
continuation, completed resume, unknown passage rejection, cutoff restrictions,
spending reservations and access-stop behavior. These fixtures do not establish
a completed paid run or answer quality.

The first live run was blocked by **HTTP 403: the configured upstream API key's
total usage limit was exceeded**. Five actual concurrent requests were rejected
before generation. Forty-five further attempts were denied locally; no further
HTTP generation calls were made. No answer was generated and the ledger accounts
$0. All attempts are preserved. The runner now also stops queued question workers
immediately on access failure. The later judge invocation produced a compact
export with all 50 judgments skipped and null scores; it is not a scored run.

After the configured Foundry/OpenRouter access is restored, resume with:

```bash
PYTHONDONTWRITEBYTECODE=1 lume/agentic-search/src/.venv/bin/python elasticsearch/src/eval.py --model google/gemini-3.8-flash --thinking-level HIGH --batch-size 5 --resume-after-access-restored
```

This explicitly clears only the access halt, preserves all budget history and
failed attempts, and retains the same index/settings. Do not use `--fresh` to
bypass the blocker or discard audit data. The detailed local status is in
`db/evaluation-report.json`; credentials belong only in the environment or root
`.env`, never in chat or committed files.

## Judge integration

`src/judge.py` reuses the shared `judge/eval.py` evaluator, exact gold joins,
four rubrics, schemas and resume logic. The adapter supplies the top-level
Elasticsearch folder because the shared judge's CLI currently restricts input
folders to `lume/`. No shared runner or other method files were changed.

```bash
PYTHONDONTWRITEBYTECODE=1 lume/agentic-search/src/.venv/bin/python elasticsearch/src/judge.py --dry-run
PYTHONDONTWRITEBYTECODE=1 lume/agentic-search/src/.venv/bin/python elasticsearch/src/judge.py --concurrency 5
```

It uses Claude Sonnet 5.5, low reasoning, temperature 0, concurrent mode and the
same $15 campaign ledger. Judge API requests pass exclusively through Foundry's
OpenRouter route. Operational state/audit/locks stay directly under `judge/`;
the compact export is `judge/final-results/q-a-eval-elasticsearch.jsonl`, which
Pages discovers automatically as `elasticsearch` on the next build. The full
original method output remains unchanged.

Actual first invocation: 50 records, zero eligible answers, 50 skipped judgments,
all scores null, no judge API requests and $0 judge cost. The compact schema and
retained gold evidence passed validation for all 50 records. The shared judge's
31 offline tests passed. See `judge/validation/elasticsearch-judge-report.json`.
After successful answers exist, rerunning the adapter replaces skipped entries
with actual judgments while preserving valid completed scores. An access halt
must first be cleared explicitly after credentials/limits have been restored;
use `--resume-after-access-restored` for that case, and `--retry-errors` if a prior
actual judge attempt failed. Gold references remain confined to judging/exports.

An earlier user-requested access recheck resumed one real question (`q065`) and
again received HTTP 403 with `openrouter_key_limit` before generation. It recorded
zero new generation IDs and zero cost, then halted admissions. The remaining
generation run and subsequent judging were not started at that checkpoint. There
were zero successful answers and no latency/correctness results at that time.
That historical result is in `db/access-check-report.json`; the $15 ledger and every
earlier attempt remain preserved.
