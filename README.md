# SEC Financial RAG Benchmark: BM25 vs. Agentic Search

Comprehensive benchmark comparing retrieval strategies for financial question answering on 10,000+ SEC filings across answer correctness, faithfulness, serving API cost, latency, and evidence grounding.

**[Explore the Live Interactive Benchmark →](https://hrmiitm.github.io/rag-on-large-data/)**

---

## Benchmark Overview

| Strategy | Retrieval Engine | Architecture | Model | Shards / Chunks |
| :--- | :--- | :--- | :--- | :--- |
| **`lume-bm25`** | Native Lume BM25 | Single-pass top-$k$ retrieval | Gemini 3.8 Flash (High Reasoning) | 33 shards / 640,745 chunks |
| **`lume-agentic-search`** | Native Lume + Tool Loop | Multi-turn query decomposition & tool calls | Gemini 3.8 Flash (High Reasoning) | 33 shards / 640,745 chunks |

---

## Dataset Description & Preparation

The evaluation corpus is derived from regulatory SEC EDGAR filings for H1 2025:

- **10,469 Retained Filings**: 4,615 annual reports (`10-K`) and 5,854 quarterly reports (`10-Q`).
- **Section Filtering Rule**: Retains Management’s Discussion and Analysis (MD&A) and Financial Statements with Notes (Items 7 & 8 on 10-K; Part I Items 1 & 2 on 10-Q).
- **Corpus Size**: ~444.5 million source tokens, 640,745 chunks (800-token body, 100-token overlap, company/filing metadata prefix). Each document contains at least 10,000 retained tokens.
- **50 Reference Questions (`data/questions.jsonl`)**: Across 5 categories (`connected_multi_document`, `comparative_analysis`, `financial_reasoning`, `risk_governance`, and `disclosure_lookup`) with verified character-offset gold evidence.

### Setup & Extraction

To extract and validate the prepared section corpus locally:

```bash
# 1. Install extraction dependencies
python -m pip install duckdb tiktoken

# 2. Extract sections from raw filings and validate reference questions
python scripts/prepare_sec_sections.py \
  --output data/financial_sections.parquet \
  --validate-questions data/questions.jsonl
```

---

## Running the Benchmarks

### 1. BM25 Lexical Retrieval (`lume/bm25`)

Uses a memory-bounded sequential shard architecture (33 shards, max 2 GB native RSS) with global corpus-wide inverse document frequency (IDF) statistics to guarantee exact native scoring.

```bash
# Build / verify the 33 BM25 shard indexes
python lume/bm25/src/setup.py

# Verify retrieval without making LLM calls
python lume/bm25/src/eval.py --check-retrieval

# Run full 50-question evaluation (Gemini 3.8 Flash via OpenRouter/Foundry)
python lume/bm25/src/eval.py \
  --model google/gemini-3.8-flash \
  --thinking-level HIGH \
  --batch-size 5
```

### 2. Agentic Search (`lume/agentic-search`)

Adapts Lume's multi-turn agent loop to allow the LLM to autonomously issue `lume_search` queries, evaluate retrieved financial passages, reformulate sub-queries, gather multi-document evidence, and synthesize final answers with strict citation mapping.

```bash
# Ingest and build independent agentic indexes
python lume/agentic-search/src/setup.py

# Verify retrieval and tool execution
python lume/agentic-search/src/eval.py --check-retrieval

# Run full 50-question agentic search evaluation
python lume/agentic-search/src/eval.py \
  --model google/gemini-3.8-flash \
  --thinking-level HIGH \
  --batch-size 5
```

---

## Automated LLM Judge (`judge/`)

Evaluates generated answers against gold references across four distinct dimensions (Answer Correctness, Faithfulness, Context Relevance, and Answer Relevance) using Claude 3.5 Sonnet:

```bash
# Judge a specific method folder
python judge/eval.py lume/bm25
python judge/eval.py lume/agentic-search
```

Output is validated against `judge/evaluation.schema.json` and saved as compact `rag-presentation/1.0` JSONL files in `judge/final-results/`.

---

## Interactive Benchmark Observatory (Website)

The benchmark frontend automatically discovers any `.jsonl` result file placed under `judge/final-results/` at build time.

### Key Features

1. **Overall Performance Table (`Results at a Glance`)**: Strategy comparison matrix showing correctness, faithfulness, cost, latency, and tokens.
2. **Strategy Scores by Question Category**: Breakdown of accuracy and efficiency across all five financial question categories.
3. **Quality vs. Cost Plot**: Displays the Pareto frontier with logarithmic cost scale by default.
4. **Side-by-Side Question Matrix**: Compares retrieved evidence, correctness, faithfulness, cost, and latency for each individual reference question side-by-side.
5. **Question Lab Modal**: Detailed inspect modal with gold answers, model answers, citation links, and raw execution logs.

### Running the Website Locally

```bash
cd website
npm ci
npm run dev
```

Run test suite:

```bash
npm test         # Data discovery & normalization tests (25 tests)
npm run test:ui  # DOM & UI integration tests (27 tests)
```

### Deploying to GitHub Pages

Pushing to `main` triggers GitHub Actions (`.github/workflows/benchmark-pages.yml`), which tests, generates versioned static data, and publishes the website to GitHub Pages:

**[https://hrmiitm.github.io/rag-on-large-data/](https://hrmiitm.github.io/rag-on-large-data/)**
