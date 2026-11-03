# rrf-rerank

RRF candidates followed by the shared CPU cross-encoder.

Live answer evaluation completed: **50/50 answers**, **$0.67838850** recorded API cost. No judge was run. See the [shared setup, concurrency, method definitions, metrics and validation guide](../../hybrid-rerank/runtime/README.md).

From the repository root, verify setup without evaluation:

```bash
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/rrf-rerank/src/eval.py --check-setup
```

Evaluation (paid Foundry calls), with five question workers:

```bash
PYTHONDONTWRITEBYTECODE=1 lume/hybrid-rerank/runtime/src/.venv/bin/python lume/rrf-rerank/src/eval.py --batch-size 5
```

Supports `--concurrency 10`, `--model`, `--sample-size`, `--seed`, `--defer-metadata`, `--refresh-metadata`, `--fresh` and `--dry-run`. Outputs belong to this folder only. The shared corpus is read-only.

For the current capped campaign, preserve the shared `RAG_SPEND_LEDGER` environment variable described in [LIVE-EVAL.md](../../hybrid-rerank/runtime/LIVE-EVAL.md). Do not reset its ledger or use `--fresh` when resuming.
