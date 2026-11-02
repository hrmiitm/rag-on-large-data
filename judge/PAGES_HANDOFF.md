# Small GitHub Pages handoff

The presentation data is sufficient to build a static comparison dashboard without the original SEC Parquets, retrieval indexes, binaries, virtual environments, raw logs or full method `q-a.jsonl` files. A fresh dashboard agent can use only `data/questions.jsonl` and the final-result JSONL files as its data inputs. Give it this guide, `AGENTS.md` and `evaluation.schema.json` as well so it interprets fields consistently.

## Files to provide

- `data/questions.jsonl`: question pool, categories, gold answers/evidence and calculation/reference details (currently about 208 KB).
- Every `judge/final-results/*.jsonl`: actual method answers, all retained operational metrics, compact retrieval metadata, judge scores/explanations, status/error information and full gold evidence. The BM25 export is currently about 1.01 MB for 50 questions, before judging.
- `judge/evaluation.schema.json`: the `rag-presentation/1.0` contract.
- `AGENTS.md` and this guide: method discovery, metric interpretation and presentation requirements.

No original method file is required for the dashboard features above. The final exports already embed the gold evidence; root questions remain useful for showing expected coverage, unanswered questions and the category/reference catalog. Source filenames and hashes in provenance are audit references, not required browser fetches.

The data files are not themselves a website. The dashboard agent still needs to create HTML/CSS/JavaScript (or static framework output), a build script that discovers files, and a Pages deployment configuration. GitHub Pages serves static assets; no API key, live LLM call, database server or Python backend is needed in the browser. See [GitHub's Pages overview](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages).

## Required discovery and comparisons

1. At build time, glob **all** `judge/final-results/*.jsonl` in sorted order. Generate a manifest for browser fetches automatically. Do not hard-code method filenames, hand-maintain a manifest, or expect HTTP directory listing.
2. Strip `q-a-eval-` and `.jsonl` from the filename to get the displayed method name. `q-a-eval-lume-agentic-search.jsonl` is `lume-agentic-search`; preserve all hyphens. The record's source `method` may be `agentic`, which is distinct from this file-derived display label.
3. Parse one JSON object per nonempty line and check `schema_version: rag-presentation/1.0`. Join root references by `question_id` (root references use `id`).
4. Use `answers[answer_model]` for per-model answers, metrics and judging. Top-level `judge` / `judge_details` are aliases only when exactly one answer model exists; they are null with multiple models.
5. Include coverage/status counts. A running or partially evaluated method may have fewer than 50 records or pending/skipped/error answers. Show missing/null metrics as unavailable. Compute score averages only over valid completed judgements, and display the denominator. Compare matched question IDs/models when ranking methods.
6. Keep RAG operational cost/timing in `metrics` / `answers[model].metrics` separate from evaluation overhead in `answers[model].judge_details.metrics`. Do not add reasoning tokens to output tokens again. Shared `batch_usage` totals repeat across judged rows; deduplicate by batch ID rather than adding them as per-answer cost.
7. Provide question/category filters, model/method comparison, answers vs gold, full gold evidence drill-down, four judge metrics/explanations, and cost/time/token/retrieval/tool/DB/RAM metrics when available. Use the available metric keys dynamically so future metrics are not silently dropped.
8. Gold calculations, reasoning and required-answer points are in `gold_details`. Retrieved IDs/ranks/scores/source metadata are retained, but **retrieved passage text, exact sent prompts/contexts, model reasoning and raw API histories are intentionally absent**. Those features, exact prompt replay or rejudging faithfulness would need separately supplied originals; the dashboard must not pretend the gold passages were the retrieved context.

## Size and Git policy

The root `.gitignore` keeps small source files, docs, `.env.example`, questions, compact final results and small sanitized validation reports. It excludes `.env`, SEC Parquets, method databases, virtual environments, downloaded vendor sources/toolchains, compiled binaries, full method JSONL, raw logs, judge audit/state and build outputs. These ignored files remain local; no Git repository was initialized.

The measured candidate Git contents are roughly 1.6 MB at this stage, before the future full agentic export and site assets. Snapshot measurements are saved in `validation/git-footprint-report.json` and `validation/offline-snapshot-report.json`; a running agentic snapshot is not a final size forecast. Use lazy per-method loading if many datasets accumulate.

This is well below GitHub's [50 MiB file warning / 100 MiB hard file limit](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) and the [1 GB published Pages site limit](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits). Recheck sizes as methods and result history grow; the limit is not a promise about unlimited future results. The current export has pending scores until judging is run; sample calibration is not a full evaluation or human accuracy guarantee.

## Reproducing benchmark runs later

The small presentation repository is enough to build the dashboard. Rebuilding retrieval or generating/judging new answers additionally requires downloading/preparing the ignored corpus, rebuilding indexes and installing dependencies, plus local credentials for API calls. Those tasks are independent of Pages deployment. Judge tests live under `judge/`; never run setup/evaluation inside a user's active method folder while validating the judge.
