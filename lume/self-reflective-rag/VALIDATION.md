# Live answer evaluation — 3 November 2026

All 50 live questions completed through Foundry/OpenRouter, with five question workers and a peak of five simultaneous paid HTTP requests. The internal review accepted 29 drafts and requested one extra search/revision for 21 questions. Recorded API cost including every draft, review, revision and query embedding was $1.45740168. No failed/truncated final answers or generation HTTP errors occurred. Context/offset/stable-ID/schema/token/cost checks passed, and the shared vector hashes were revalidated. The external gold-reference judge was not run; answer correctness and improvement remain unscored. See [shared campaign policy](../hybrid-rerank/runtime/LIVE-EVAL.md) and its final report for metadata coverage and full audit results.

The preparation-only account below is historical.

---

# Preparation validation — 3 November 2026

The method is prepared, with an independent Python environment and tokenizer cache. No real corpus retrieval, query embedding, generation, reflection or judging was run. No `q-a.jsonl`, `raw-eval.log` or final-result dataset was created. Dependencies were installed from the local package cache without network access.

The 11 offline tests passed in the new environment. They exercise the actual runner with mocked HTTP and retrieval on synthetic data:

- 50 synthetic questions through five workers, covering accept, revise and retrieve decisions; ten concurrent workers in a separate fixture.
- Independent draft/review/search/final contexts for two answer models, correct citation maps and per-model retrieval ranks/query occurrences.
- Two chat calls for accepted drafts; three for revised answers, plus query embedding when retrieval is requested. Cost and token totals include all stages/retries without double-counting reasoning.
- Invalid/inconsistent/unbounded reflection responses rejected; invalid JSON retries only the reviewer; a truncated revision retries only that revision.
- An interruption after a durable response resumes with zero new HTTP calls for that response. Completed runs resume with zero new generation or retrieval.
- Atomic checkpoints, sampled fresh reset, preservation of unrelated state and full resume retaining already completed questions.
- Metadata enrichment covers draft, reflection and revision IDs, excludes embedding requests, records complete coverage and makes zero repeated completed GETs.
- Original hard date cutoffs and native hybrid mode remain fixed on every additional search. Prompts contain no gold/reference-answer fields.
- Correct alternating evidence merge and actual local context tokenization within the specified test budget, using only this method's tokenizer cache.
- The existing independent judge receives each final answer's actual context. Compact synthetic records validate against `rag-presentation/1.0` and contain no raw API payloads or internal checkpoint traces. No judge artifacts are written by tests.

Setup verified the shared source configuration, question-only snapshot, global BM25 statistics, all 33 vector hashes covering 640,745 chunks, the existing original-query vector cache and native adapter. `--check-setup` and `--dry-run --concurrency 10` passed without API calls, real retrievals or result writes.

A before/after hash audit checked 3,658 existing source/configuration/output/report files outside this method. It observed 9 concurrent changes in semantic/hybrid judge exports, status/audit files and documentation; these changes were left intact, and no global unchanged-files claim is made. Shared runtime source, the shared corpus configuration and the question-only source remained unchanged. Before/after hashes are recorded in `db/preparation-validation.json`. Existing method code, data, environments, results, judge state and jobs are not edited or controlled by this setup. The shared native reader and libraries are reused read-only, with output paths configured only within this new evaluator's process.

These checks do not establish live Foundry/structured-output availability, actual benchmark speed/cost, reflection accuracy or answer-quality improvement. The method is prompt-based reflection, not the original Self-RAG trained reflection-token algorithm. Revised answers receive no second review, and an independent gold-reference judge is still necessary for a later live benchmark.

Final metadata collection succeeded for all 424 chat attempts across the six-method campaign, with HTTP 200 and matching generation IDs. The complete measured handoff is [LIVE-RESULTS.json](../hybrid-rerank/runtime/LIVE-RESULTS.json).
