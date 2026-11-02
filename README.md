# RAG on Large Data

Compare retrieval strategies for financial question answering on SEC filings—answer quality, faithfulness, API cost, latency, and evidence.

**[Explore the benchmark →](https://hrmiitm.github.io/rag-on-large-data/)**

The corpus contains **10,469 filings and 640,745 chunks**, evaluated with **50 reference questions**. The website automatically includes every result file in `judge/final-results/`.

## Run the website locally

```bash
cd website
npm ci
npm run dev
```

## Project guide

- [Dataset and preparation](data/README.md)
- [BM25 benchmark](lume/bm25/src/README.md)
- [Agentic search benchmark](lume/agentic-search/src/README.md)
- [Judge and scoring](judge/README.md)
- [Website, tests, and deployment](website/README.md)

## Publish results

Push changes to the default branch. GitHub Actions tests the site, rebuilds the result data, and deploys GitHub Pages. New result JSONL files appear automatically on the next build.

Large datasets, indexes, credentials, and raw run logs stay local and are excluded from Git.
