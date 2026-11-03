# Self-reflective RAG evaluation

This is a **prompt-based reflection workflow**, using the same answer model to review its draft. It is not an implementation of the original Self-RAG paper's trained reflection-token models. Live answer evaluation completed on 3 November 2026: **50/50 answers**, **$1.45740168** recorded API cost. No gold-reference judge was run.

The method reads the existing shared SEC corpus, exact vectors and global BM25 statistics without changing them. Its scripts, independent Python environment, question-only snapshot, configuration, tokenizer cache, checkpoints and outputs belong to `lume/self-reflective-rag/`. Shared library code and the native helper are read from `lume/hybrid-rerank/runtime/`; all method-specific paths are set only inside this evaluator's process. No existing script is edited and the other methods' launcher remains unchanged.

## Method and cost bounds

1. Run native hybrid retrieval for the original question, with top 10 chunks and the original hard `as_of` cutoff. It uses the same native multiplicative formula as the hybrid baseline, global BM25 statistics and existing `text-embedding-3-small` vectors. The original question vector is already cached; no corpus embedding pass is needed.
2. Generate a draft using `google/gemini-3.8-flash`, HIGH reasoning, up to 8,192 output tokens and the baseline SEC-only citation prompt.
3. Review the draft against exactly those passages using the same model, LOW reasoning, temperature 0 and a separate 2,048-token output limit. Structured checks cover citations, company/period/units, calculations and evidence sufficiency. The review receives no reference answer or gold evidence.
4. The review chooses one action: **accept** the draft; **revise** using existing evidence; or **retrieve** with one focused query and then revise. Accepted drafts require two chat generations total; revised answers require three, before retries. There is never a second valid review cycle or a second additional search for the same answer model.

A new search query may require one query-only embedding through Foundry. Its document candidates still use the existing vectors. Additional searches use the original cutoff; the model cannot select paths, databases or cutoff overrides. Original and new candidates alternate by rank with stable-ID deduplication, and the final answer receives at most 10 chunks and 12,000 `cl100k_base` tokens. All candidates and their per-query scores/occurrences remain in the full audit, including passages omitted from final context.

There is no cross-encoder stage, so the primary comparison is with the existing hybrid baseline. The review is an internal generation step, not an independent benchmark judge. A revised final answer is not reviewed a second time. Whether reflection helps financial answer quality needs separate judging; self-review does not establish correctness.

## Setup and no-API checks

The independent `.venv`, configuration, question snapshot and owned tokenizer cache are already prepared. To reproduce preparation from this workspace's existing corpus/runtime:

```bash
uv venv --python 3.12 lume/self-reflective-rag/src/.venv
uv pip install --python lume/self-reflective-rag/src/.venv/bin/python -r lume/self-reflective-rag/src/requirements.txt
PYTHONDONTWRITEBYTECODE=1 lume/self-reflective-rag/src/.venv/bin/python lume/self-reflective-rag/src/setup.py
```

Setup verifies all 33 existing vector hashes, global BM25 statistics, native helper, source configuration, existing query-vector snapshot and the 50 question-only records. It creates only this method's configuration/metadata copies and tokenizer cache. It makes zero embedding/LLM calls and runs zero production retrievals. A configuration change with saved results is rejected. The six original Parquets, prepared corpus, shared sidecars, other method files and judge state remain read-only.

```bash
PYTHONDONTWRITEBYTECODE=1 lume/self-reflective-rag/src/.venv/bin/python lume/self-reflective-rag/src/eval.py --check-setup
PYTHONDONTWRITEBYTECODE=1 lume/self-reflective-rag/src/.venv/bin/python lume/self-reflective-rag/src/eval.py --dry-run --sample-size 5 --seed 77 --concurrency 10
```

These two modes do not retrieve, call APIs, write answers or create judge results.

## Execution commands

All generation, reflection, new query embeddings and metadata calls use `LLMFOUNDRY_BASE_URL/openrouter/v1/...`. Credentials come from repository `.env`/environment. No direct provider/OpenRouter host calls are used and authentication headers are never saved.

```bash
# Optional paid five-question pilot, with fixed selection.
PYTHONDONTWRITEBYTECODE=1 lume/self-reflective-rag/src/.venv/bin/python lume/self-reflective-rag/src/eval.py --sample-size 5 --seed 77 --batch-size 5 --defer-metadata

# All 50 questions; completed work resumes.
PYTHONDONTWRITEBYTECODE=1 lume/self-reflective-rag/src/.venv/bin/python lume/self-reflective-rag/src/eval.py --batch-size 5 --defer-metadata

# Sequential optional statistics GETs for every draft, review and revision ID.
PYTHONDONTWRITEBYTECODE=1 lume/self-reflective-rag/src/.venv/bin/python lume/self-reflective-rag/src/eval.py --refresh-metadata

# Separate independent judging, only when generation is complete.
PYTHONDONTWRITEBYTECODE=1 lume/self-reflective-rag/src/.venv/bin/python judge/eval.py self-reflective-rag --mode concurrent --concurrency 5
```

The default is five question workers; `--batch-size` / `--concurrency` supports 1..10. Free slots immediately take the next question. A shared dispatcher coalesces waiting searches (`--search-batch-wait-ms`, default 250, range 0..1000). Native shards are opened sequentially under the existing shared native-process lock using a read-only descriptor and a 2 GiB native address-space cap. No native readers run concurrently against these shared indexes. The existing available-RAM guard applies. Models supplied through repeated `--model` execute sequentially per question, each with independent draft, review, optional search, context and citation numbering.

Supported controls also include `--thinking-level`, `--max-output-tokens`, `--fresh`, `--sample-size`, `--seed` and `--defer-metadata`. Use the same model reasoning/output settings for resume and metadata refresh. Worker count is execution provenance, not part of the retrieval/configuration identity. `--fresh` clears only this folder's `q-a.jsonl` and `raw-eval.log` under its own lock; shared indexes and other experiments are untouched. Sampling preserves saved records outside the selection.

## Checkpoints, records and metrics

Every received API response is atomically checkpointed before parsing or progressing. Successful stages replay from saved responses, including an interruption between receipt and completion of the surrounding step. Invalid/truncated reviews retry the review stage on a later run; truncated revisions retry only the revision. Native candidates are saved before downstream work. A completed extra search is not repeated when resuming a failed final revision.

An interrupted request whose response was never saved has unknown remote acceptance and may incur another charge if repeated. Transient HTTP retries are bounded by the shared client; permanent errors do not silently fall back to a draft. A bad review or failed extra search remains an explicit execution error. SIGINT/SIGTERM stop new stage admissions and allow active operations to checkpoint. Offline tests do not guarantee live gateway availability or an error-free run.

Saved `q-a.jsonl` records use the unchanged `rag-benchmark/1.0` schema, preserving raw sanitized API attempts, retrieved text and source offsets, every supplied context, per-model citation maps, reviewer decision/checks and retry/error history. Internal response checkpoints and draft/review state live in `trace`, which the existing compact exporter removes. Each final answer includes its exact `context` and `retrieval`; `context.by_model` disambiguates models. The judge evaluates the final answer against the context actually supplied for that answer, using gold references only in the separate judge process.

API serving cost and tokens include drafts, reviews, revisions, query embeddings and recorded retries. Input plus output tokens form the total; reasoning is already in output. Missing usage/cost/token-detail values remain null with observed totals/completeness flags. Record totals count the initial retrieval once and sum independent model executions. Metrics separate reflection/draft/revision time, additional searches, DB operations, context sizes, model/embedding/metadata HTTP calls, retries and memory. Answer-ready latency includes active retrieval, queueing and all generation steps, excluding metadata enrichment and downtime between resumes. Metadata coverage counts all successful chat generation IDs; the primary answer's `metadata_status` alone does not imply complete metadata for earlier stages.

The independent judge will produce `judge/final-results/q-a-eval-lume-self-reflective-rag.jsonl`. The existing website will discover it automatically after actual generation/judging and a site build. Setup creates no placeholder result dataset.

## Offline verification

```bash
PYTHONDONTWRITEBYTECODE=1 lume/self-reflective-rag/src/.venv/bin/python -m unittest discover -s lume/self-reflective-rag/src -p 'test_*.py' -v
```

Tests use synthetic questions and mocked HTTP/retrieval. They cover all three review decisions, 50 synthetic questions with five workers, ten workers, independent models/contexts, cost/token accounting, atomic writes, response replay, retries, fresh/sample/resume, metadata for all chat stages, actual local tokenization, and compatibility with the existing judge and compact schema. See [VALIDATION.md](VALIDATION.md) for actual verification status and limits.

The live answer campaign uses a shared spending ledger and no external judge. See [budget policy](../hybrid-rerank/runtime/LIVE-EVAL.md). Preserve `RAG_SPEND_LEDGER` when resuming.
