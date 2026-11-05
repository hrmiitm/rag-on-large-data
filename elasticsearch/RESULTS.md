# Completed Elasticsearch agent benchmark

The live run completed on November 5, 2026: **50 successful answers and 50
completed gold-reference judgments**, using five question workers and five judge
workers. Foundry/OpenRouter access was restored before this run.

| Measurement | Actual result |
| --- | --- |
| Answer model | Google Gemini 3.8 Flash, HIGH reasoning |
| Judge | Claude Sonnet 5.5, low reasoning, temperature 0 |
| Answer/judgment coverage | 50/50 and 50/50 |
| Average active answer-ready latency | 47.10 seconds (n=50) |
| Average serving API cost per answer | $0.03815956 (n=50; excludes judging) |
| Answer-generation reported cost | $1.907977875 |
| Judge reported cost | $2.555618 |
| Total reported/accounted cost | **$4.463595875**, within the shared $15 limit |
| Unknown-cost reservations at completion | 0 |
| New embedding calls/cost | 0 / $0 |
| Successful generation requests | 259/259 HTTP 200 |
| Metadata lookups | 259/259 HTTP 200; all 50 answers enriched |
| Judge requests | 50/50 HTTP 200 |

| Judge rubric | Mean score / 100 | Valid judgments |
| --- | ---: | ---: |
| Answer correctness | **90.18** | 50 |
| Faithfulness | 90.68 | 50 |
| Context relevance | 90.60 | 50 |
| Answer relevance | 92.58 | 50 |

Correctness is the mean model-judge rubric score with partial credit, not binary
or human-verified accuracy. Eighteen answers received exactly 1.0 correctness;
other scores include partial credit. Missing/failed judgments were not converted
to zero or included as valid scores.

The generation phase spanned 655.33 seconds (10.92 minutes), including the
one-question access check saved as a successful answer. Sequential metadata
enrichment spanned 602.87 seconds (10.05 minutes), and judging spanned 69.92
seconds (1.17 minutes). First successful generation request to last judge response
was 1,335.26 seconds (22.25 minutes). Active answer-ready latency excludes
pre-worker queue time, metadata enrichment and judging; ingestion/setup is separate.

The run used keyword/cached-question semantic/RRF hybrid searches, company/form
filters and neighbouring passage reads. No settings were tuned using the resulting
judge scores. Existing embeddings were reused.

Final validation covered all 50 common-schema records, retrieved text offsets,
date cutoffs, citation maps, per-turn contexts, usage totals, all generation
metadata and the compact result schema. There were zero unmapped parsed citation
markers and no generation/tool errors in this successful run. The 662 retrieved
chunk entries counted are unique within each question, not necessarily across
the whole benchmark.

The original method file remained unchanged by judging and completed resume.
The compact export preserved answers, operational metrics and full gold evidence.
Completed evaluation resume scheduled zero paid calls; judge dry-run found zero
pending answers. Historical rejected key-limit attempts remain in local audit/
history, account zero, and are not scored answers or successful model calls.

Artifacts:

- Full local audit: `elasticsearch/q-a.jsonl` and `elasticsearch/raw-eval.log`.
- Compact export: `judge/final-results/q-a-eval-elasticsearch.jsonl`.
- Small report: `judge/validation/elasticsearch-final-report.json`.
- Verification: `judge/validation/elasticsearch-final-validation.json` and
  `judge/validation/elasticsearch-source-validation.json`.
- Local spending ledger: `elasticsearch/db/budget-ledger.json`.

Pages discovers the export as `elasticsearch` automatically at build time.
Source, documentation and this compact export can be published without the local
index, full answer audit or credentials. The dedicated Elasticsearch
container was stopped after completion to release RAM and restore its pre-run
state; the validated index remains intact. Before a new retrieval run, start it
with `docker compose -f elasticsearch/compose.yaml up -d`.
