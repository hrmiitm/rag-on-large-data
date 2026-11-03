# SEC Financial RAG · Benchmark Observatory

A static React + TypeScript dashboard built with Vite, Plotly.js and TanStack Table. It reads the existing benchmark outputs without running retrieval, generation or judging. No server, API key or database is required after building.

From the repository root:

```bash
cd website
npm ci
npm run dev
```

Open the Local URL printed by Vite (normally `http://localhost:5173`). The development watcher regenerates data and reloads the page when result JSONL files are added, changed or deleted. Benchmark runners remain independent and untouched.

```bash
npm test          # data, normalization, matching and real Vite watcher tests
npm run test:ui   # DOM interaction and Plotly adapter tests
npm run build    # regenerate data, type-check and create dist/
npm run preview  # serve that production build
```

## Reading the dashboard

The presentation follows the supplied [PageIndex benchmark reference](https://jivraj-18.github.io/benchmark-finance-pageindex/): a centered page, system fonts, a compact metric-by-strategy results table and one chart at a time. Body and answer text use 16px system fonts; the summary table uses 17px. There are no external font downloads.

The first table places **retrieval strategies in columns** and **metrics in rows**: correctness, faithfulness, context relevance, answer relevance, average API cost, average answer-ready latency, average total tokens and judged-answer coverage. `More metrics` reveals additional operational measurements. Each model/settings group has its own labeled table; multiple configurations remain separate, and hover details show each metric's denominator. Selecting a value opens the corresponding questions.

Use the **Chart** selector for cost, response time, categories, heatmap or resources. Secondary statistics, findings and detailed matched comparisons start collapsed. Question inspection and methodology remain separate navigation views. Table column controls reveal the extra metadata without crowding the default table.

## Data flow

`judge/final-results/*.jsonl` → JSON Schema validation → one evaluation per question × filename-derived method × model × configuration → hashed summary JSON + lazy question detail files → `public/data/manifest.json`.

All JSONL files are discovered in sorted order. A filename must contain `eval-`; the entire suffix after it, without `.jsonl`, is the method name. This preserves names such as `lume-agentic-search`. There is no fixed method registry. Invalid rows/files produce visible validation warnings; valid rows continue loading. Duplicate evaluation identities select the latest `updated_at` snapshot rather than duplicating costs.

The initial asset contains summaries, compact previews and operational metrics. Full answers, judge explanations, gold passages and retrieval metadata load only when a question opens. Everything is generated from source records; there are no sample evaluations bundled into the published site. Future-method fixtures live only inside tests and temporary directories.

Versions incorporate source hashes, reference questions, the schema, dataset documentation snapshot, normalization code and optional evidence snapshots. Assets have versioned paths. The manifest uses uncached fetches; an open tab checks for a newly published version every 60 seconds and when focused. Development builds reload immediately after watcher regeneration. A public static website changes only after a new publication; it cannot see unpublished local files.

### Optional retrieved text

When a final record references `lume/<method>/q-a.jsonl` and that file exists locally, the builder reads it once as an optional snapshot. It records snapshot hashes/counts and copies **only matching retrieved passages** into lazy detail files. Matching requires question ID, configuration, run ID, corpus hash, chunk ID, document ID, source hash and character offsets. Answers, scores and metrics always come from the authoritative compact final export. It never copies requests, responses, reasoning, raw histories or service credentials.

Original method files stay read-only. On GitHub runners these ignored originals will usually be absent: the same build then publishes retrieval metadata and full gold passages, with unavailable retrieved text explicitly labeled. Original raw method files are never required for deployment. Gold passages are not substituted for retrieved context.

`dataset.json` is a small documented snapshot of the existing corpus measurements from `data/README.md`, `AGENTS.md` and the read-only BM25 index configuration. It distinguishes filing dates from reporting years. It is **not a method registry**. Update its documented measurements if the prepared corpus changes. Exported per-run corpus/configuration/question hashes remain visible independently.

### Correct interpretation

- Judge scores follow the schema's [0, 1] range and are displayed as percentages. Completed valid judgments alone enter means. Pending, skipped, error and missing remain distinct.
- Cost/latency/tokens use their own measured denominators. There is no zero imputation and no unweighted average of category averages.
- Per-model metrics take precedence over record aliases. Multi-model records never reuse top-level aggregate serving metrics as individual-model charges.
- Latency prefers per-model `answer_ready_time_seconds`. Metadata enrichment is separate. It is not TTFT.
- Input + output gives total tokens; reasoning is already included in output.
- Tool calls mean what the method recorded. In plain BM25, `tool_calls=1` is a local retrieval wrapper, not an LLM tool call.
- Judge overhead stays separate from serving. Repeated batch usage is not added to serving cost.
- Methods/models/configurations stay separate leaderboard series. Matched comparisons intersect question ID, model, as-of date, corpus/question hashes, reasoning and output limits. No winner is inferred without comparable completed results. Heatmap cells explicitly pool selected models/configurations; filter to a model/configuration for controlled analysis.

## GitHub Pages deployment

The prepared workflow is `../.github/workflows/benchmark-pages.yml`. Nothing was initialized, committed, pushed or deployed by building this site.

1. When you choose to put this existing project on GitHub, retain the compact exports, questions, website source/lockfile, schema and workflow. Generated `public/data/`, dependencies and `dist/` are ignored and rebuilt automatically. Do not upload corpus databases, raw method JSONL or credentials.
2. In the repository's **Settings → Pages**, choose **GitHub Actions** as the publishing source.
3. Commit/push through your normal process to the repository's default branch, or trigger the workflow manually there. The workflow detects the default branch, installs dependencies, runs tests, regenerates every result asset, builds and deploys `website/dist/`.
4. The workflow obtains the repository/custom-domain path from `actions/configure-pages` and supplies `PAGES_BASE_PATH`. Queries handle navigation and shareable filters without requiring server rewrites. Adding or deleting result files triggers the next build automatically.

To reproduce a repository-path production build locally:

```bash
PAGES_BASE_PATH=/rag-on-large-data/ npm run build
PAGES_BASE_PATH=/rag-on-large-data/ npm run preview
# Open http://localhost:4173/rag-on-large-data/
```

For a root/custom-domain deployment, use `/`. This follows [Vite's GitHub Pages guidance](https://vite.dev/guide/static-deploy.html#github-pages). The workflow requires the normal Pages permissions and a repository with Actions enabled; no external hosting account is used.

## Verification limits

See [VALIDATION.md](VALIDATION.md). DOM tests verify filters, chart event wiring, tables, detail loading and themes, and separate adapter tests verify Plotly options/exports. They do not replace a real-browser visual, touch-device or accessibility audit. Browser access was disabled in the workspace Work settings during implementation; no screenshot/visual or mobile-browser verification is claimed.

Table ordering: the first table uses small inline arrows, matching the category table. The **↕** button beside **Metric** orders metric names; its **↔** button orders strategy names. The **↔** button beside each metric orders strategy columns by that recorded value. Buttons cycle ascending, descending, then original order; **Reset order** resets both axes. There are no ordering dropdowns. Sorting uses each model/settings table’s own values. Missing values and strategies with multiple configurations stay last; configurations are never pooled for sorting. Coverage remains the last row. Row labels remain visible during horizontal scrolling. Question/detail tables support header sorting, Shift-click multi-column sorting, and **Reset sorting**; active sort direction is exposed to assistive technology.

The category breakdown keeps its original grouped layout. Hover a category name/count, focus the question-count badge, or tap it to open a scrollable question preview (roughly 2–3 visible at once). The preview can be scrolled with the pointer or keyboard and dismissed with Escape, its close button, or an outside tap. Small header arrows sort category rows by name, question count, leader, correctness, faithfulness, cost or latency. The row ↔ arrow orders whole strategy column groups by correctness for that category. Sorting cycles ascending, descending, then original order; missing measurements remain last. Inspect continues to open the category’s questions.


The overview starts with the graph immediately after the shared filters, followed by corpus accounting and the comparison tables. The overview charts use numbered points and a responsive method selector with matching colors and numbers. Human-readable labels omit the common `lume-` prefix; original IDs remain in accessible labels and titles. Click a point, resource bar or method to pin its measurements and retrieval description **below** the graph, then use **Inspect answers** to open that exact model/configuration. Selection does not change global filters. Clear selection, click the selected method again, or press Escape to dismiss. Overlapping points remain selectable through the method buttons; a model/configuration selector disambiguates multiple series for one method. Hover cards are concise and never contain the full technique description. Other points retain at least 65% opacity.

Quality/cost and quality/time charts offer all four quality metrics. Cost starts on a linear dollar axis, with logarithmic scaling available. Quality starts fitted to filtered data (explicitly labeled); choose Full for the 0–100% reference range. Reset zoom restores the current scale. Numbered points retain exact measured coordinates; no jitter or composite quality score is added. **Show Pareto frontier** is enabled by default in the cost and response-time views. Dotted lines connect points for which no comparable point is at least as good on both axes and strictly better on one. Frontiers stay separate by model, reasoning/output settings, corpus hash, question-set hash and exact question IDs/cutoffs, and require complete valid judgments and measurements for those questions. Tied coordinates are deduplicated and at least two frontier points are needed to draw a line. Filters and the quality selector recompute the frontier; its checkbox hides it. This describes observed results, not a statistical winner. **Exact values** provides a keyboard-accessible table, separate measured denominators, and missing/unjudged series even when they cannot be plotted. Mean serving cost excludes judging, time uses median answer-ready latency, and quality uses only valid completed judgments. Category bars and heatmap cells drill into their exact model/configuration; heatmap columns never pool different series.

Method descriptions use recorded adapter identities (`sourceMethod`), including hybrid/semantic cross-encoder reranking, RRF with/without reranking, HyDE and bounded prompt-based self-reflection. Unknown adapters still appear automatically with an explicit fallback; descriptions do not control result-file discovery.

The overview shows four corpus-accounting bullets immediately before the first comparison table. These full-corpus totals stay fixed under evaluation filters: filing/form counts, retained spans, baseline chunk/shard counts, chunk sizes, average retained words/tokens per filing and text/Parquet sizes. `dataset.json` stores the small measurement snapshot; building the site requires no corpus access. Words count whitespace-separated pieces of retained `sections[].text`, not whole filings or overlapping embedding inputs.
