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

## Direct sorting across all data tables (2026-11-03)

Replaced the remaining static question, category, heatmap and configuration tables with the shared sortable table. Column headers sort the complete data before pagination; each row includes a keyboard-operable column-order button. The overview matrix supports direct metric-row and strategy-header sorting, including extra metrics, coverage and explicit configuration controls. Question/category correctness, faithfulness, cost and latency each have a separate sortable column, without pooling models, settings or retrieval configurations. Touch targets are at least 44px high. Repeated taps cycle forward/reverse/reset; missing measurements remain last. Sorting raw values across different metrics does not create a composite quality score.

Verification: 35 DOM/Plotly tests and 25 data/watcher tests, including direct controls on both axes, numeric ordering with missing values in both directions, keyboard operation without opening inspection, complete-set sorting before pagination, exact-answer inspection and separate category metric headers. Existing heatmap filtering and application interactions still pass. Production TypeScript/Vite build uses `/rag-on-large-data/`. Browser inventory again reports “Local browser use is disabled in Work settings”; visual and physical touch-device review remain unavailable. No method or judge jobs were run or modified.
