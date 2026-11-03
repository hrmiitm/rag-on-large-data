# Live answer evaluation — 3 November 2026

All six retained techniques (including the separate self-reflective runner) completed 50 live answers each, with $5.29044809 total recorded API cost under a $10 cap. Methods ran sequentially with five question workers each; real HTTP overlap reached five. Twenty-three shared-runtime tests and eleven reflection tests passed after the transport correction. All six final setup checks, all 300 record/context/source audits and the cost/mechanism integrity checks passed. Twelve protected original-method output/configuration snapshots remained identical. No gold-reference judging or new corpus embedding pass was run.

One question initially exhausted its output limit in both hybrid-rerank and RRF; successful retries preserve the full prior attempts. One initial hybrid retry replayed the same generation ID; Cache-Control: no-cache fixed that transport issue without changing prompts/settings/retrieval. Its receipt is still included conservatively in the cost total. The explicit transport-only compatibility transition preserves original configuration hashes. See [LIVE-EVAL.md](LIVE-EVAL.md) and the final campaign report for receipts, metadata status and concurrency measurements.

The preparation and removal accounts below are historical.

---

# Runtime relocation and method removal — 3 November 2026

The top-level `query-decomposition`, `mmr` and `retrieval-variants` folders were removed at the user's request. Shared code, environment, native source and reranker assets were moved into `lume/hybrid-rerank/runtime` to keep the retained methods operational. The supported evaluation list is now `hybrid-rerank`, `semantic-rerank`, `rrf`, `rrf-rerank` and `hyde`.

Entry points, setup configuration, documentation and environment paths were updated. After relocation, native compilation and setup verification passed; all 18 offline tests and all five no-API launcher dry runs passed. All 12 protected result/export/log files retained identical content hashes. No real evaluation or paid API call is authorized by this change. Existing experiment results and judge exports are protected by before/after content hashes.

The earlier preparation verification below is historical: its seven-method count describes the original setup, before this removal.

---

# Preparation validation — 3 November 2026

The seven new method folders are prepared. No real benchmark retrieval, answer generation, query generation, query embedding or judging was run. No new method has a `q-a.jsonl` or `raw-eval.log`, and no final-result JSONL was created. Public pinned reranker assets were downloaded during setup; those are ordinary model-file downloads, not Foundry inference requests.

The new native executable compiled offline against an independent copy of pinned Lume `f031390f0f4afdeeb14d609775ce51617d1a3f2c`. Its query-vector adapter injects vectors into memory and exposes candidate vectors for MMR; it never persists query vectors to the shared sidecars. The reproducible source addition is shipped in `src/native/query-adapter.rs.inc` and applied only to the new vendor copy by `src/build_native.py`.

Setup verified all 640,745 existing chunk vectors across 33 shard hashes, the 1,536-dimensional embedding profile, original question-vector coverage, the question-only snapshot and global BM25 statistics. All seven CLI `--check-setup` and `--dry-run` checks passed without retrieval or API calls, including reproducible sampling and ten-worker configuration. The all-method launcher was also checked in `--dry-run` mode.

The offline suite contains 18 tests. It covers:

- The actual seven driver paths on 50 synthetic question records per method with five workers; a ten-worker HyDE fixture; bounded concurrent HTTP mocks, atomic schema-valid checkpoints, fresh reset, sample preservation and full resume without repeating completed work.
- Truncated-answer recovery that repeats only the affected generation, preserves the original attempt snapshot and includes both attempts' usage/cost.
- Query-generation and query-embedding response replay, request-identity rejection, unknown/ambiguous costs and missing token-detail handling; input plus output totals never add reasoning twice.
- RRF deduplication and per-source ranks; subquestion-balanced merging; MMR diversity using existing vectors; complete overlapping reranker token windows.
- Ten-query native-dispatch coalescing, exact future mapping, and waking all waiters after a batch failure.
- Saving native candidates before reranking, then recovering from a reranker failure without another retrieval pass.
- Deferred metadata collection for query-generation and answer IDs, excluding embedding IDs and avoiding repeated completed lookups.
- Real native lexical/cosine/hybrid operations on three **temporary synthetic documents**, dynamic query-vector injection, hard date cutoffs, formula checks, missing-query failure, unchanged fixture vectors and the 2 GiB cap.
- Real CPU ONNX cross-encoder inference on synthetic planet descriptions and token-window checks on synthetic long text. This validates model loading/interfaces, not financial retrieval quality.
- Compatibility with the existing shared judge's preparation and compact-export functions for every new method. Synthetic compact outputs validate against `rag-presentation/1.0`; raw requests/responses and resumable stage state are absent. No judge file is written by these checks.

The existing 50 question strings were tokenized locally to check cross-encoder input limits; the longest was 23 reranker tokens. No corpus retrieval or model answer was generated for that check.

The isolation audit compared SHA-256 content hashes of 398 existing experiment source/config/output/log/lock files before and after preparation; no content changes were found. Shared vector hashes were independently rechecked by setup/CLI validation. Detailed operational reports remain under this new support folder's ignored `db/`, including `offline-tests.log`, `cli-validation.json`, `isolation-before.json` and `isolation-after.json`. Existing corpus files, method outputs, judge artifacts and jobs were not edited or controlled.

Live Foundry availability, gateway credits, live provider usage fields, real-corpus retrieval timing, answer quality and full evaluation completion remain untested. Offline tests and asset checks cannot establish those outcomes. A future paid pilot is the next validation stage when execution is authorized.

Final metadata collection succeeded for all 424 chat attempts across the six-method campaign, with HTTP 200 and matching generation IDs. The complete measured handoff is [LIVE-RESULTS.json](LIVE-RESULTS.json).
