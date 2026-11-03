# Additional SEC retrieval evaluations

Five prepared experiments reuse the existing complete `lume/semantic-search/db` corpus, lexical indexes and `text-embedding-3-small` vectors. `hybrid-rerank/runtime` contains their shared implementation and its own Python environment, native executable, public reranker assets and validation reports; it is shared infrastructure inside a retained method.

**All six budgeted methods completed 50 live answers each (3 November 2026), with $5.29044809 recorded cost and no judging.** See [LIVE-EVAL.md](LIVE-EVAL.md) for the spending guard and campaign policy, and [LIVE-RESULTS.json](LIVE-RESULTS.json) for measured results and complete metadata coverage. Earlier preparation checks used synthetic fixtures; see [VALIDATION.md](VALIDATION.md).

| Folder under `lume/` | Pipeline |
| --- | --- |
| `hybrid-rerank` | Native multiplicative hybrid top 50; cross-encoder reranks all 50; up to 10 chunks enter context. |
| `semantic-rerank` | Exact cosine top 50; same cross-encoder; up to 10 context chunks. |
| `rrf` | Global BM25 top 50 and exact cosine top 50; equal-weight reciprocal rank fusion, `sum(1 / (60 + rank))`; up to 10 context chunks. |
| `rrf-rerank` | Same two lists and RRF; rerank the best 50 fused candidates; up to 10 context chunks. All candidates in the union remain recorded, including candidates outside the reranking depth. |
| `hyde` | Generate one hypothetical filing passage; embed that query using the same embedding model and dimensions; exact cosine retrieval; up to 10 context chunks. The hypothetical passage is never supplied as evidence to the answer model. |

Each method has `src/eval.py`, `src/setup.py`, `src/questions.jsonl`, its own `db/`, and (only after execution) its own `q-a.jsonl` and `raw-eval.log`. Existing BM25, agentic, semantic and hybrid sources, outputs, environments and databases are read-only inputs. There is no document embedding operation in this implementation.

## Prepared settings

All methods answer the same 50 question-only records using `google/gemini-3.8-flash`, HIGH reasoning, 8,192 maximum output tokens and the baseline SEC-only citation prompt. Context is capped at 10 chunks and 12,000 `cl100k_base` tokens. `--model` can be repeated; models for one question execute sequentially with the same retrieval/context. The query-planning model for HyDE is also Gemini 3.8 Flash HIGH, with a separate 4,096 output-token limit. Its settings and overhead are recorded separately.

The CPU cross-encoder is `cross-encoder/ms-marco-MiniLM-L6-v2`, pinned to revision `233902d25c440f23af6f7d6e94d2946bac0bee0a`, using the publisher's ONNX model and tokenizer. This is a small general passage reranker, not a financial-domain-trained model. Every candidate's title and body are tokenized into complete overlapping windows of at most 512 paired tokens, with 64 passage tokens of overlap. The maximum window logit determines the candidate score. All window scores and original retrieval ranks/scores are saved. Questions above 128 reranker tokens fail explicitly; the current 50 questions have a measured maximum of 23. CPU inference uses two threads and batches eight windows; `--reranker-batch-size` changes the execution batch only. Token-window aggregation is part of the method definition and may affect quality.

Answer generation, HyDE generation, new query embeddings and generation-metadata lookups use only the configured **LLM Foundry OpenRouter route**. No native search can fall back to a remote embedding service. Reranking runs locally, so it has measured CPU time and RAM but no reranking API charge. Public model-file downloads from Hugging Face happen during explicit setup, not during evaluation.

## Setup, without evaluation

The current workspace is already provisioned. To reproduce preparation from the existing complete shared corpus and pinned local Rust source/toolchain:

```bash
uv venv lume/hybrid-rerank/runtime/src/.venv
uv pip install --python lume/hybrid-rerank/runtime/src/.venv/bin/python -r lume/hybrid-rerank/runtime/src/requirements.txt
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/hybrid-rerank/runtime/src/build_native.py
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/hybrid-rerank/runtime/src/setup_variants.py --download-reranker
```

The build creates its own native/vendor copy and Cargo cache; the small, checked adapter addition is shipped as `native/query-adapter.rs.inc`. The existing Rust toolchain is read as a prerequisite. Setup verifies all 33 document-vector hashes, global BM25 statistics, the complete source configuration and question snapshot, then extracts the already-paid original question vectors into a new read-only snapshot. Each method's `db/config.json` records these identities. Existing nonempty results prevent an incompatible setup rewrite. No setup command embeds documents, retrieves production questions or calls Foundry.

A method's setup can also be run separately:

```bash
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/rrf/src/setup.py
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/rrf/src/eval.py --check-setup
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/rrf/src/eval.py --dry-run
```

`--check-setup` and `--dry-run` make zero API calls, run zero retrievals and write no result records. Evaluator startup also verifies the shared hashes. Credentials come from root `.env`/environment (`LLM_PROVIDER=llmfoundry`, `LLMFOUNDRY_BASE_URL`, `LLMFOUNDRY_API_KEY`); authentication headers are neither logged nor saved.

## Evaluation commands

One method, with five concurrent question workers:

```bash
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/hybrid-rerank/src/eval.py --batch-size 5
```

Ten workers, or a reproducible five-question pilot:

```bash
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/semantic-rerank/src/eval.py --concurrency 10
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/hyde/src/eval.py --sample-size 5 --seed 77 --defer-metadata
```

`--batch-size` / `--concurrency` accepts 1..10 and defaults to 5. Each worker owns one question, including query preparation and sequential answer models; free slots take the next question immediately. A retrieval dispatcher coalesces queued searches, with a default 250 ms collection window (`--search-batch-wait-ms`, 0..1000), up to four queries per question worker in a pass. It maps each result back to its exact query future. Query-specific cutoffs apply before top-k, with global corpus statistics and sequential shard loading. It acquires the existing shared native-process lock through a **read-only descriptor** and caps each native process at 2 GiB address space. It waits for 2,304 MiB available RAM before native work. No existing lock-file contents are changed. Cross-encoder inference is serialized across these new methods using their own shared lock.

Run all five methods sequentially, with concurrent questions inside each:

```bash
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/hybrid-rerank/runtime/src/run_all.py --batch-size 5
```

This order avoids loading five readers/reranker instances at once. The launcher stops if a method fails and leaves its saved work for resume. Generation metadata is deferred until every selected method has finished generation, then collected sequentially. `--method` can be repeated to select methods; `--dry-run` validates the selections without executing them. It does not automatically judge. To explicitly generate and then judge all five in the future, add `--judge`; the launcher invokes the existing shared judge in concurrent mode with the normal Sonnet 5.5 low/temperature-0 defaults and only the selected new folder names.

## Checkpoints, retries and measurements

Responses are saved atomically before parsing or selecting evidence. Successful query-generation, query-embedding and answer responses resume without another paid request, even if interruption occurs before the surrounding stage finishes. A request interrupted before its response is checkpointed is marked `remote_acceptance_unknown_after_interruption`; repeating that request may incur another charge. This is not an exactly-once guarantee. Invalid/truncated responses remain in history; a later run retries their stage. Transient HTTP errors use bounded backoff; permanent errors such as 401/402 stop the affected question's stage. An external error-free run is not guaranteed.

Native candidate results are checkpointed before reranking or context construction. A reranker failure can therefore resume without repeating retrieval. Candidate caches and query-side state belong to the new method only. Corrupt/mismatched checkpoints fail explicitly. A writer lock saves immutable per-question snapshots, preventing concurrent workers from dropping one another's results. Sampling preserves other saved questions. SIGINT/SIGTERM stop new work while active operations drain to checkpoints.

Repeating an evaluation command resumes completed stages. `--fresh` clears only that method's `q-a.jsonl` and `raw-eval.log` under its own lock; it never removes indexes or changes another experiment. Fresh runs intentionally issue new generation calls; orphaned candidate-cache files are not reused without a matching saved record. Deleting only the two output files also starts fresh generation.

Metadata is optional enrichment after all question workers finish. `--defer-metadata` postpones it; `--refresh-metadata` makes only sequential generation-statistics GETs. It covers every successful chat generation ID, including HyDE, and defers 404/429 rather than repeatedly hitting them. Use the same model reasoning/output settings when resuming or refreshing a custom run. Configuration hashes include method settings, corpus/question identities, code and answer settings, while worker count and scheduling do not change the retrieval identity.

Outputs use the unchanged `rag-benchmark/1.0` schema. They retain every unique retrieved candidate's text, IDs, source hashes/offsets, per-query occurrences/ranks/scores, reranker window scores, exact supplied context/citation maps, sanitized requests/responses, retries/errors, returned model/provider/usage/cost and operational metrics. Private query/answer stage checkpoints are stored inside `trace`, which the shared compact judge exporter already removes; no judge changes are necessary.

Serving API cost and tokens include query preparation plus answer calls. Per-answer metrics show preparation overhead, while record totals count shared preparation once across multiple answer models. Embedding calls are reported separately from LLM calls. Unknown/ambiguous usage or costs stay null with observed totals and completeness flags. Output tokens already include reasoning; reasoning is not added twice. Latency includes active query preparation, queueing, retrieval, reranking and generation, and excludes metadata enrichment and resumed downtime. Reranker cold-load/hash checks are setup overhead outside question latency. Local reranking's infrastructure dollar cost is not estimated.

## Separate judging and website export

After generation has actually completed, a new method can use the existing judge:

```bash
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python judge/eval.py hybrid-rerank --mode concurrent --concurrency 5
```

Replace the folder name for other methods. Final compact files become `judge/final-results/q-a-eval-lume-<folder>.jsonl`; Pages discovers them on its next build. No placeholders were created there, and no website edits are required. Gold references are read only by this separate judge; retrieval, query generation, reranking, answer generation and document/query vectors never receive them. Existing judge jobs/state are unrelated and remain untouched.

## Offline verification

```bash
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python -m unittest discover -s lume/hybrid-rerank/runtime/src -p 'test_*.py' -v
```

Tests exercise all five actual drivers with synthetic questions, five and ten workers, atomic checkpoints, resume/fresh/sample behavior, real native search on a tiny temporary corpus, and the downloaded ONNX model on synthetic text. They do not establish live Foundry availability, retrieval quality, corpus-run speed or completed benchmark results.

Model documentation: [publisher model card](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2), [pinned files](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/tree/233902d25c440f23af6f7d6e94d2946bac0bee0a). Query embedding request contract: [OpenRouter embeddings reference](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request), accessed only through Foundry in this implementation.
