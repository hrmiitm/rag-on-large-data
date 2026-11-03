# Website validation · 3 November 2026

The dashboard was implemented and checked locally. It was not committed, pushed or deployed. The benchmark/judge runners and method directories were not modified, installed into, stopped or restarted. Optional retrieved passages came from a read-only BM25 output snapshot; active method outputs may change independently.

## Automated checks

- **25 Node tests passed**: actual export metric preservation; filename-derived discovery; score scales/statuses/nulls; per-model versus aggregate metrics; reasoning-token accounting; weighted category aggregation; shared filters/ranges; URL roundtrips; separate configurations; matched comparisons; CSV escaping; public-field sanitization; lazy details; invalid/empty/duplicate records; deterministic versions; new/modified/deleted method files; exact local-evidence matching; real Vite development file-watcher integration.
- **27 DOM/adapter tests passed**: current authoritative snapshot coverage/means, controlled category hover versus selection, multiple categories, heatmap cross-filtering, strategy selection, shared numeric/status filters, searching, lazy answers/gold/evidence/citations, method comparisons, sorting/pagination/column visibility, themes, query-string deep links, judge dimensions/statuses, methodology, loading errors/empty data, future-method discovery, the compact comparison matrix, a single active chart, collapsed secondary sections, scatter/bar click wiring, Plotly categorical/log axes, zoom configuration and PNG/SVG export wiring.
- **TypeScript + Vite production build passed** at `/rag-on-large-data/`.
- **Production HTTP smoke passed**: repository-prefixed entry point with filter queries, four compiled assets, manifest, summary data, all 50 lazy detail files and favicon returned successful responses with the expected content types. The preview server was stopped afterward.
- Public generated-data scanning found no authentication headers, private local workspace paths, service base URLs, raw API-call arrays, generation-statistics payloads or trace fields.

The generic discovery/normalization tests use isolated temporary directories; the watcher test adds/updates/deletes fixture files there, never under the live `judge/final-results/`. Interaction fixtures are based on a sanitized real presentation record and root question references; they are under `tests/`, outside the published site. Tests audit the current actual exports dynamically and do not require a fixed method list or a permanent pending-judgment count.

## Actual source snapshot

- Discovered method: `lume-bm25`.
- Final export: `q-a-eval-lume-bm25.jsonl`.
- Source SHA-256: `d39df96e35d61eacaa9d886a690758f5dc47b00fb0645aeba5eae79ced2d35ca`.
- 50 model evaluations; 50 pending judgments; no completed quality scores.
- Five categories; one answer model; zero schema-validation warnings.
- Full gold evidence: 102 passages.
- Optional locally verified retrieved text: 500 chunks, loaded only in question details.
- Summary data: approximately 163 KB; lazy details: approximately 2.71 MB total; production artifact approximately 4.5 MB before HTTP compression.

The source/export hashes and optional original-snapshot hashes are also generated into the manifest. They describe the read snapshots, not a guarantee that an active benchmark writer never changed its own files. No full-benchmark answer-quality claim, new judging run or API call is implied.

## Verification limits

The browser inventory returned **“Local browser use is disabled in Work settings.”** Real-browser rendering, screenshots, touch-device interaction, visual contrast and a full accessibility audit were therefore unavailable. Responsive layouts, keyboard/focus behavior, dark/light/system themes, semantic controls and reduced-motion styles are implemented; DOM tests and Plotly adapter tests do not establish visual correctness on physical desktop/mobile browsers. PNG/SVG tests verify export calls, not image pixel output.

GitHub Actions/Pages configuration is prepared but was not executed remotely. To publish, follow the normal repository process and the steps in [README.md](README.md).

## Presentation revision

Replaced the sidebar dashboard with the user-supplied reference's simpler reading layout: centered content, 16px system typography, a 17px comparison matrix, compact category/method controls, one active chart and closed secondary details. Extra table columns remain available through column controls. No benchmark data or calculation rules changed. Real-browser visual review remains unavailable because local browser use is disabled in Work settings.

## Metric-by-strategy table revision

The first overview table now puts retrieval strategies in columns and metrics in rows. Default rows show correctness, faithfulness, context relevance, answer relevance, average API cost, average answer-ready latency, average total tokens and judged-answer coverage. Additional operational rows are available through `More metrics`. Model/settings groups get separate tables, and multiple configurations retain distinct labeled values.

The latest checks passed: 27 DOM/Plotly adapter tests (including five focused matrix tests) and the TypeScript/Vite build at `/rag-on-large-data/`. Matrix checks cover orientation, exact per-metric means, missing values, measured denominators, configuration/model separation, click-through inspection and token accounting. The current read snapshot contains 100 completed judgments across `lume-agentic-search` and `lume-bm25`, with zero schema warnings; the earlier source snapshot above is historical. No benchmark or judge was rerun for this change. Browser visual verification remains unavailable as previously recorded.

## Table ordering update (2026-11-03)

Added independent metric-row name ordering and strategy-column sorting by name or numeric metric, ascending/descending controls and reset. Each model/settings table sorts its own values. Missing values and multi-configuration methods remain last in both directions without pooling configurations. Coverage remains at the bottom. Horizontal scrolling retains metric labels. Shared question/detail tables expose accessible sort state and a reset control.

Validation passed: 25 data/watcher tests, 29 DOM/Plotly adapter tests (including missing-last numeric ordering, reset, row ordering and configuration separation), TypeScript and the production build with `PAGES_BASE_PATH=/rag-on-large-data/`, and `git diff --check`. No live browser visual or touch-device review was performed for this update. No retrieval, generation or judging was run.

## Category-table hover and sorting (2026-11-03)

Kept the original category matrix, paired strategy columns, badges, descriptions, leader column and Inspect actions. Added small inline/header-edge sort arrows and a portal-based question preview that avoids clipping inside the table’s horizontal scroll area. The preview opens on hover, focus or tap, shows about 2–3 questions with vertical scrolling, stays open while entering/scrolling it, and supports Escape, close and outside-pointer dismissal. Column-group sorting moves both headers and their associated values together; the original leader computation stays independent of presentation order.

Passed 33 DOM/Plotly tests and 25 data/watcher tests, including four focused category tests for grouped-table preservation, numeric sorting/reset, missing values, header/cell alignment, unchanged inspection, category-specific preview contents, hover-to-popup movement, internal scroll, keyboard focus, click and dismissal. Production TypeScript/Vite build passes with `/rag-on-large-data/`. Browser visual/touch verification remains unavailable because local browser use is disabled in Work settings. No benchmark or judge job was run or modified.


## Inline matrix controls and overview method legend (2026-11-03)

Replaced the first table’s ordering dropdowns with compact inline header/row arrows. Buttons cycle ascending/descending/original order, show pressed state, work with Enter/Space, and keep reset and coverage placement. Numeric column ordering stays separate by model/settings, with missing/multi-configuration values last. No cross-unit ranking of metric rows was introduced; the vertical control orders metric names.

Added all currently selected/discovered method names above the overview chart, with colored markers and hover/focus/tap descriptions of retrieval and supplied LLM context. Escape dismisses the description without filtering. Scatter points now have hover-only names; their individual hover details include model/configuration, measured metrics and concise search/context descriptions. Known descriptions follow recorded adapter identities, with unknown/mixed-method fallbacks and escaped Plotly labels. No method-discovery registry or benchmark calculations changed.

Passed 25 data/watcher tests and 39 DOM/Plotly adapter tests. New checks cover inline sorting cycles and keyboard access, missing-last/model/configuration separation, all-method legend placement, scatter hover-only labels, technique/context descriptions, no filtering on legend hover, exact series inspection, future-method fallback and hover text escaping. Browser inventory returned “The browser access host is unavailable”; no live screenshot, visual or touch-device verification is claimed for this revision. Retrieval, generation and judging were not rerun. No Git staging, commits, push or publication was performed.

The revised production build passed TypeScript and Vite with `PAGES_BASE_PATH=/rag-on-large-data/`. A temporary localhost preview passed HTTP checks for the repository-prefixed entry point, three referenced compiled assets, manifest and evaluation data: four automatically discovered methods, 200 completed model evaluations and zero schema warnings. The preview was stopped. The semantic/hybrid original answer-file hashes still match the completed-pipeline validation report. These HTTP/DOM checks do not replace the unavailable live browser visual review.

## Corpus accounting above the first table (2026-11-03)

Added four concise bullets with full-corpus document/form totals, retained spans, shared baseline chunk counts/shards, chunk size/overlap, average retained words/tokens and total retained/Parquet sizes. A read-only, eight-row streaming scan of the prepared Parquet measured 276,228,782 whitespace-separated words, 1,792,664,837 retained UTF-8 bytes and 444,518,010 source tokens across 10,469 documents. Averages round to 26,385 words and 42,460 tokens per document. The small dataset snapshot supplies the site; original text is not bundled. These describe retained sections, not whole filings or repeated overlapping embedding input.

Passed 25 data/watcher tests and 40 DOM/Plotly tests, including placement before the first table and unchanged accounting after category filtering. Browser visual/touch review remains unavailable (browser host unavailable). No retrieval, generation, judging, staging, commit or publication was performed.


## Publication checks with all ten methods (2026-11-03)

The complete working website passed 25 data/watcher tests and 40 DOM/Plotly tests. TypeScript/Vite production build passed with `PAGES_BASE_PATH=/rag-on-large-data/`, automatically discovering all 10 final-result datasets and 500 judged evaluations with zero data warnings. Dependencies, generated `public/data/`, `dist/` and test logs remain ignored. Provider workspace/user-agent and related account diagnostics were removed from compact public generation statistics; answers, scores, full gold evidence and operational/token/cost metrics were preserved. See `judge/validation/publication-report.json`. No paid evaluation or judge call was made during these checks. Browser visual/touch review was not repeated in this publication pass.

## Chart interaction redesign (2026-11-03)

Replaced the floating method-description tooltip and sticky hover/focus fading with responsive numbered method controls, matching numbered scatter markers, concise measurement hover cards, and an inline pinned detail region below the plot. Point/bar clicks select locally; Inspect answers explicitly opens the exact series. Method controls, the series picker, clear/Escape and an exact-values table support keyboard and click interaction. Overlapping points keep their true coordinates and remain selectable through the method controls. Nonselected points retain at least 65% opacity, and the selected scatter point draws last.

Added all four quality measures to both scatter views, linear dollar cost by default with optional log scaling, labeled fitted/full quality ranges and a reset-zoom control. Removed the old frontier line that combined different settings. Descriptions now cover all ten recorded adapters, including HyDE's exclusion of hypothetical text from evidence and the bounded prompt-based nature of self-reflection. Unknown adapters remain discoverable. Category heatmap columns now keep model/configuration series separate, and category/heatmap drill-down preserves those exact filters. Mean serving cost, median answer-ready time, missing quality and individual measured denominators remain distinct.

Passed all 45 DOM/Plotly adapter tests and 25 data/watcher tests. Checks cover numbered controls/colors, concise escaped hover labels, pin/clear/Escape behavior, exact configuration inspection, missing values and denominators, stale selection after filtering, every known adapter description, future methods, separate heatmap series and fitted/currency axis configuration. TypeScript/Vite production build passed with `PAGES_BASE_PATH=/rag-on-large-data/`: 10 automatically discovered methods, 500 evaluations, zero data warnings. Browser inventory again reported “The browser access host is unavailable”; visual, screenshot and real touch-device review could not be performed. Changes are limited to website source, tests and documentation; no retrieval/generation/judging or benchmark-data changes were made.

## Graph first and default Pareto frontier (2026-11-03)

Moved the single selected graph to the start of the overview, immediately after shared filters and before corpus accounting and both comparison tables. Restored a checked-by-default Show Pareto frontier control for cost and response-time views. Dotted lines draw behind numbered points and recompute with filters, quality measure and axis. Frontier membership requires valid completed quality scores and measured costs/times on identical question IDs/cutoffs, with model, reasoning/output settings, corpus and question-set hashes kept separate. Unknown provenance and incomplete series do not form frontier lines. Dominated points are excluded, tied coordinates deduplicated, and a single frontier point produces no line. No benchmark inputs or outputs changed.

Passed 47 DOM/Plotly tests and 25 data/watcher tests, including overview order, default checkbox/toggling, actual rendered frontier coordinates, metric recomputation, tied-cost dominance, duplicate coordinates, missing measurements and incompatible settings/provenance/question sets. Production TypeScript/Vite build passed with the repository Pages base path, 10 methods, 500 evaluations and zero data warnings. Browser visual/touch review was not repeated; the browser host was unavailable during the preceding redesign.
