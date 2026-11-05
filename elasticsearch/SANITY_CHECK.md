# Post-run sanity check

The saved benchmark passed the operational audit. This review made zero new
model/embedding calls and did not change answers, judgments or retrieval settings.
The full audit and compact result hashes still match the final validation report.

The agent executed 180 searches (93 hybrid, 87 keyword) and 32 neighbouring
passage reads. All 212 tool executions succeeded; 179 searches used a company
filter. No semantic-only searches were chosen. All 259 generation requests, 259
metadata lookups and 50 judge requests in the successful run completed with HTTP
200. Reported costs reconcile to the ledger at $4.463595875, with no unknown-cost
reservations. Earlier rejected key-limit attempts remain separate in history.

Recorded retrieval averaged 18.82 ms per tool execution and 79.80 ms total per
question. These are local, filtered, observed wall timings on this run; they are
not a distributed/concurrent search load test. The 47.10-second average answer
latency is largely model/tool orchestration time rather than local retrieval.

## Observed system comparison

| Configuration | Mean correctness / 100 | Mean answer-ready seconds | Mean serving cost |
| --- | ---: | ---: | ---: |
| Elasticsearch agent | 90.18 | 47.10 | $0.03816 |
| Lume agentic search | 80.96 | 178.16 | $0.04105 |

All 50 question IDs/text/cutoffs, corpus/question-set hashes, answer model
(Gemini 3.8 Flash HIGH, 8,192 output limit) and judge settings (Sonnet 5.5 low,
temperature 0) match. This compares complete agent configurations: Elasticsearch
adds structured filters, hybrid retrieval and neighbouring passage tools; it ran
five workers after a single-question check, while Lume used ten workers. Hardware
contention, caches and run timing were not controlled. The result supports keeping
this configuration as a strong candidate; it does not isolate an engine-only
quality gain or establish a general latency speedup.

## Remaining weaknesses

- 27/50 questions used all six model turns. This is not 27 failures, but shows
  the turn budget is often binding.
- For **q028**, the agent searched Alphabet, read neighbours, searched Amazon,
  read neighbours, then searched Meta. The forced final turn arrived before a
  Netflix search. Netflix was required for the correct minimum comparison. The
  0.15 correctness judgment is consistent with that missing evidence; it is an
  agent-planning failure rather than missing corpus ingestion.
- Other weaker answers omit parts of requested reconciliations or required
  accounting distinctions, or make claims broader than the passages support.
- Mean correctness 90.18/100 is a partial-credit model-judge rubric score.
  Only 18/50 answers scored exactly 1.0; it is not 90.18% perfectly correct answers
  or a human-verified accuracy measurement.
- Against 102 gold evidence items, context contained the matching filing/hash
  for 100 items and fully covered 72 complete gold spans by union of character
  offsets. This strict whole-passage coverage can miss cases where relevant rows
  were supplied but the full reference passage was not; it is not ANN recall,
  required-fact recall or a binary answer score. ANN recall against exact cosine
  remains unmeasured.
- Semantic refinements reuse the original question vector. Rewritten text
  changes lexical retrieval, while company/form filters narrow both branches.

The clearest next experiment is to require coverage of every requested company
or document before optional neighbour reads. A separate experiment should
measure ANN recall and warm/cold search performance. Preserve this completed
run; do not tune or silently replace its answers using these judge results.

## Website

The current local server is `http://127.0.0.1:5173/`. Data generation discovered
550 evaluations from all 11 methods with zero warnings, including 50 valid
Elasticsearch records. The root HTML, manifest and evaluations asset returned
HTTP 200. No real-browser visual/touch review was performed for this check.

Choose `elasticsearch` under Method, or leave all methods selected to compare.
Click a table value / Inspect answers and open q028 to see the weak case and
judge explanation. The response-time graph uses median latency (44.82 seconds
for Elasticsearch); the main table reports mean latency (47.10 seconds).

The optional retrieved-passage enricher currently accepts only `lume/.../q-a.jsonl`
paths, so local Elasticsearch passage text is not enriched on the site. Its
answers, scores, gold evidence, metrics and retrieval metadata are still present.
Full Elasticsearch passages/tool traces remain in the local audit JSONL. The
method-description panel now explains the combined search techniques and LLM
workflow, with measured comparisons recalculated from matching filtered results.

For a later local session, run `npm --prefix website run dev`. The static site
needs no Elasticsearch process or model API to display saved results. A hosted
GitHub Pages site changes only after a new deployment; nothing was published.
