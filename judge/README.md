# Gold-reference answer judging

Run this after a method creates `lume/<folder>/q-a.jsonl`. It evaluates **every available successful answer** against the matching reference in root `data/questions.jsonl`, using only LLM Foundry's OpenRouter route. Gold references go to the judge, never into the retrieval index or answering prompts. This is a separate stage from `lume/bm25/src/eval.py`.

For a stable full evaluation, wait until answer generation and metadata enrichment finish. Validation may read snapshots of a running method without changing its files, but source changes can invalidate saved judgement fingerprints or prevent an active native batch from resuming against the changed inputs.

From the repository root, using the existing environment:

```bash
lume/bm25/src/.venv/bin/python judge/eval.py bm25
```

Or install the sole dependency in your own Python environment:

```bash
python -m pip install -r judge/requirements.txt
python judge/eval.py bm25
```

This reads `lume/bm25/q-a.jsonl` and writes **`judge/final-results/q-a-eval-lume-bm25.jsonl`**. Substitute another method folder name to produce `q-a-eval-lume-<foldername>.jsonl`. Paths such as `lume/bm25` also work. Inputs must follow the shared `rag-benchmark/1.0` schema. Only records present in the input are evaluated: five saved pilot records produce five output records, not a new 50-question generation run.

Credentials come from repository `.env` / environment, using `LLMFOUNDRY_BASE_URL`, `LLMFOUNDRY_API_KEY`, and `LLM_PROVIDER=llmfoundry`. Environment variables override `.env`, which overrides `.env.example`. Authentication headers are never logged; the configured key is redacted from saved API data.

For the top-level Elasticsearch experiment, use `PYTHONDONTWRITEBYTECODE=1 lume/agentic-search/src/.venv/bin/python elasticsearch/src/judge.py --concurrency 5`.
This adapter reuses this shared evaluator without changing its `lume/` CLI path
restriction, shares the experiment's $15 campaign ledger, and writes
`final-results/q-a-eval-elasticsearch.jsonl`. Its first invocation found zero
eligible source answers and exported 50 skipped/null judgments with zero API
calls; this is not a completed scored benchmark. See
[`elasticsearch/EVALUATION.md`](../elasticsearch/EVALUATION.md).

The subsequent full Elasticsearch run completed all 50 answers and all 50
Sonnet judgments: $1.907977875 generation plus $2.555618 judging, $4.463595875
total. All compact schemas, gold evidence, source preservation and zero-call
resume checks passed. See [`elasticsearch/RESULTS.md`](../elasticsearch/RESULTS.md)
and `validation/elasticsearch-final-validation.json`.

## GitHub Pages discovery

GitHub Pages must discover every `.jsonl` file in `judge/final-results/` at build time, rather than hard-coding filenames or a method list. Derive the displayed method name from everything after `eval-`, excluding `.jsonl`: `q-a-eval-lume-bm25.jsonl` becomes `lume-bm25`, and `q-a-eval-lume-agentic-search.jsonl` becomes `lume-agentic-search`. Preserve the complete suffix, including hyphens. An automatically generated manifest is suitable for browser loading; a manually maintained registry is not. Audit logs, state and locks stay outside this discovery directory.

## Model and batching

Defaults: **`anthropic/claude-sonnet-5.5`**, **low reasoning effort**, **temperature 0**, 4,096 maximum output tokens. Change the judge with `--model`; answering models are taken from the input and are not regenerated.

```bash
python judge/eval.py bm25 --model anthropic/claude-sonnet-5.5 --reasoning-effort low --temperature 0
python judge/eval.py bm25 --batch-size 50 --max-wait-seconds 0
```

Native OpenRouter Batch API is the default. It sends up to 50 independent judging requests per job, with unique content-derived `custom_id` values, through **`LLMFOUNDRY_BASE_URL/openrouter/v1/batches`**. It saves the accepted batch ID and polls `.../batches/<id>` sequentially every 60 seconds. Results are matched by ID rather than arrival order. `--max-wait-seconds 0` submits and checks once, then exits with pending records; rerun the identical command to collect them. Normal runs wait up to 24 hours locally. There is no direct OpenRouter/provider fallback.

OpenRouter's [Batch API quickstart](https://openrouter.ai/docs/batch-quickstart) documents the asynchronous queue and 24-hour completion window. Native batching is intended for throughput and lower cost; it does **not** guarantee the fastest wall-clock result for a small evaluation. For an interactive evaluation, choose bounded parallel chat completions explicitly:

```bash
python judge/eval.py bm25 --mode concurrent --concurrency 10
```

Concurrent mode sends individual requests through `.../openrouter/v1/chat/completions`; it is not a native batch. Finish outstanding native jobs before changing mode, model, or inputs. Native model availability and parameter support depend on the gateway/provider; route reachability alone does not prove a paid generation will succeed.

## Compact presentation output

`final-results/` contains compact `rag-presentation/1.0` records. The original method `q-a.jsonl` stays unchanged with its full `rag-benchmark/1.0` audit data. The judge always reads the full original context for evaluation; compaction happens only when writing the presentation export.

The export keeps **every recorded top-level, per-answer, retrieval, tool-execution and judge metric**, token/cost usage, model/provider and generation IDs, finish reasons, errors/statuses, scores/explanations and compact retry history. Retrieval IDs, ranks, scores, hashes, source offsets and citation maps remain. Generation metadata is retained as `generation_statistics`.

It removes raw API requests/responses, raw JSON strings, model reasoning/messages, traces, resumable agent messages, repeated retrieved/context passage text and the repeated full index/shard configuration. Full gold evidence appears once in `gold_evidence`; gold calculations/reasoning/answer points remain in `gold_details`. Other retained reference fields are mapped to the question/category/as-of/answer fields instead of repeating the entire reference object.

Fields added to the presentation record:

| Field | Contents |
| --- | --- |
| `question_category` | Gold `category`, including financial inference and multi-document categories. |
| `gold_answer` | Exact gold `expected_answer`. |
| `gold_evidence` | Full evidence objects: passages, filing IDs, source hashes, dates and original offsets. |
| `gold_details` | Remaining reference fields, including calculations, reasoning, required answer points and document connections when present. |
| `answers[model].judge` | Four scores in `[0, 1]`, or `null` while pending, skipped or failed. |
| `answers[model].judge_details` | Explanations, judge settings/model/provider, all judge metrics, usage/cost, generation/request IDs, batch ID, status/error and compact retry history. Raw judge requests/responses stay in audit/state outside this directory. |
| `judge`, `judge_details` | Convenient aliases when the record has exactly one answering model. Both are `null` for multiple models; use each answer's fields. |
| `judge_provenance` | Gold path/hash, original record hash and scoring version/scope. |

The judge returns four separate metrics:

- **Answer correctness:** agreement with gold answer/evidence, including units, periods, arithmetic and required answer points.
- **Context relevance:** relevance and sufficiency of the context actually sent to the answering model.
- **Faithfulness:** support for candidate claims in that sent context. Gold evidence cannot credit this score. A justified abstention may be faithful and still incorrect against an answerable gold question.
- **Answer relevance:** how directly and completely the answer addresses the question, evaluated separately from correctness.

These are rubric-based model judgements, not human-validated accuracy measurements. Each metric gets an explanation. Malformed, truncated, refused or out-of-range judge responses become errors with `null` scores; they are never silently converted into zeroes. Failed/unavailable source answers are skipped. Gold joins require exact question ID, question text and as-of date agreement.

Full input records are validated against the shared benchmark schema. Every presentation write is atomic, uses compact JSON separators, and is validated against `evaluation.schema.json`. Judging metrics stay inside `judge_details.metrics` so original RAG costs/timings remain usable. Missing usage/cost stays `null`; output tokens already include reasoning. `batch_usage` is the **shared job total**, repeated for traceability: do not sum it across rows. Per-answer cost is recorded only when that result reports it. Native per-answer HTTP latency/call counts remain `null`; submission/poll calls and timings are in the audit log. No TTFT is invented for non-streaming requests.

## Resume and checks

```bash
python judge/eval.py bm25 --dry-run
python judge/eval.py bm25 --export-only
python judge/eval.py bm25 --check-endpoint
python judge/eval.py bm25 --retry-errors
python -m unittest discover -s judge -p 'test_*.py' -v
```

`--export-only` rebuilds the compact presentation file without making any API calls. It preserves saved judgements when the original source and gold hashes match, even if different model options are passed; it leaves missing judgements pending with null scores. This also compacts older full enriched exports.

`--dry-run` validates the gold joins and reports pending answers with no writes or API calls. `--check-endpoint` performs a read-only batch-list request and records the sanitized HTTP exchange; it does not call a model.

Completed judgements resume without API calls when the answer, source record, gold record, rubric, judge settings and gateway match. Failed judgements remain saved unless `--retry-errors` is supplied; retries retain previous results in `attempt_history`. Changed inputs/settings invalidate cached scores. The runner does not generate missing answers. Changing an active batch's input/settings is rejected before overwriting output.

Operational sidecars stay directly under `judge/`, outside `final-results/`:

- `q-a-eval-lume-<folder>.state.json`: accepted native batch IDs, full job responses and progress. Keep this to resume pending jobs without submitting them twice.
- `q-a-eval-lume-<folder>.audit.jsonl`: append-only sanitized HTTP requests/responses/errors, including native batch submission and polling.
- `q-a-eval-lume-<folder>.lock`: advisory lock against simultaneous judge writers for that output.

Batch submissions are not automatically retried: a timeout/5xx can occur after acceptance. An uncertain submission blocks new work until its audit/state is reconciled with the gateway's job list. A definite admission rejection is recorded as an error and can be retried explicitly. Do not delete active state files to bypass this protection. To regenerate after all jobs finish, remove the output JSONL; the completed native state is not reused as a score cache.

Exit codes: `0` no pending/error judgements (skipped source answers may remain), `1` failure, `2` native work still pending.

Validation: 25 offline tests pass, including both modes, compaction, resume and input preservation. Read-only BM25 and active agentic snapshots pass schema/gold/metric/context checks. Six live concurrent samples passed all four controlled calibration cases; see `validation/sample-concurrent-report.json`. Compact JSONL samples for both real methods are in `validation/presentation-lume-*.jsonl` and passed schema/evidence/metrics/resume checks without new calls. Native batch results are recorded separately in `validation/sample-batch-report.json` once collected. No full 50-question judging run has been performed; production final results still have pending scores.

## Live samples and Pages handoff

`sample_test.py` reads source snapshots without locking or writing either method directory. `--live` runs six isolated judgements: completed BM25/agentic answers and four controlled scoring cases based on root gold references. These are sanity checks, not a full accuracy evaluation. Reports are under `validation/`, outside final results; native accepted batch state is resumable.

```bash
PYTHONDONTWRITEBYTECODE=1 lume/bm25/src/.venv/bin/python judge/sample_test.py
PYTHONDONTWRITEBYTECODE=1 lume/bm25/src/.venv/bin/python judge/sample_test.py --live --mode batch
PYTHONDONTWRITEBYTECODE=1 lume/bm25/src/.venv/bin/python judge/sample_test.py --live --mode concurrent
```

[Pages handoff](PAGES_HANDOFF.md) describes the minimal data/code set, the small Git policy, automatic method discovery, comparison semantics and features intentionally excluded from compact files. The root `.gitignore` retains questions, small source/docs and compact final results, while excluding local credentials and large/rebuildable artifacts.

The native sample batch was accepted but remained `validating` when the local collection window ended. Its report is `pending`; native completion is not claimed. Rerun the batch sample command to collect the saved job without resubmission. The sample runner exits `2` for pending work, `1` for failed checks and `0` for passed checks.


## Completed semantic and hybrid run

On November 3, 2026, both `semantic-search` and `hybrid` completed all 50 Gemini answers and all 50 Sonnet 5.5 low/temperature-0 judgments. The earlier credit-related failures remain in audit/attempt history. The final resume preserved completed scores and original method files; read-only resume checks report zero pending judgments. Final exports are `final-results/q-a-eval-lume-semantic-search.jsonl` and `final-results/q-a-eval-lume-hybrid.jsonl`. See `validation/semantic-hybrid-final-validation.json` for source hashes, schema/score/gold checks and exact reported costs. Earlier sample/pending notes describe their recorded checkpoints rather than this completed run.


## Completed six-method concurrent run

On November 3, 2026, hybrid-rerank, HyDE, RRF, RRF-rerank, self-reflective RAG and semantic-rerank each completed all 50 judgments with Sonnet 5.5 low/temperature 0. Two five-worker processes reached ten concurrent requests; the measured HTTP window was 199.34 seconds. All 300 requests succeeded without retries, for $12.268684 reported judge cost under a separate $14 shared cap. All source answers and earlier judge exports were preserved; compact/gold/context/metrics/cost checks passed and every resume check found zero pending work. See [the measured report](validation/six-methods/final-report.json) and [campaign notes](validation/six-methods/README.md).

The optional `RAG_JUDGE_BUDGET_LEDGER` environment variable enables the shared durable per-attempt spending guard in `cost_control.py`. This campaign ledger admits only concurrent Sonnet 5.5 calls, caps provider rates and includes in-flight/unknown reservations. Preserve the existing ledger on resume. Requests now explicitly bypass whole-response gateway caching with `Cache-Control: no-cache`; this changes transport behavior, not judge rubrics/model settings or completed-score fingerprints. Thirty offline tests passed. Earlier preparation/sample counts above describe their original checkpoints.


Publication safety: compact generation statistics now omit provider account/tracking fields (workspace/user/session/application identifiers and user-agent/referrer diagnostics). Generation/request IDs, model/provider, usage/cost, timing and all benchmark metrics remain. The original full method audits remain unchanged and local. All ten compact exports were sanitized without new judging; [publication-report.json](validation/publication-report.json) records before/after hashes and preserved answers/scores/evidence/metrics. The privacy regression brings the offline judge suite to 31 passing tests.
