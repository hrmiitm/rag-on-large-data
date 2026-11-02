# Data to embed and evaluate

## Give your embedding agent this file

**`financial_sections.parquet`** contains the actual retained text, not just a list of filing names: **4,615 10-K filings and 5,854 10-Q filings**, totaling **10,469 documents**. It is a filtered section corpus, not every complete annual/quarterly filing from the six originals. No document inclusion list is needed.

Agent instruction:

> Read every row of `financial_sections.parquet`. For each element of `sections`, chunk and embed **only its `text`**. Use `text-embedding-3-small`, 800 body tokens per chunk and 100-token overlap. Add a short company/form/filing-date/document-ID prefix. Store float32 vectors and preserve the document ID, source hash and original section offsets as metadata.

The six `sfd-v1-2025-*.parquet` files are the original source archive. They do not need to be passed to the embedding agent when using the prepared file. `questions.jsonl` contains reference answers and must stay outside the retrieval index.

## Exact preparation rule

Applied to all six source files, without a handpicked document list:

1. Keep **10-K annual reports and 10-Q quarterly reports** with at least 40,000 original characters.
2. Keep one version per `file_stem`: longest original text; break ties by MD5, source filename and row number.
3. Retain **MD&A and financial statements with their notes**. Standard locations are 10-K Items 7 and 8, and 10-Q Part I Items 1 and 2. Also recognize standalone financial-statement blocks, including those placed after Item 15. Ignore table-of-contents links. Unrecognized text has no whole-filing fallback.
4. Keep a document only if its retained sections total at least **10,000 `cl100k_base` tokens** and 16,000 characters. Preserve the original text and offsets.

The preparation helper is the canonical implementation of the heading and boundary rules. The measured output has a minimum of **10,020 retained tokens** per document and a median of **34,293**.

## Size and embedding cost

| Item | Measured size or projection |
| --- | ---: |
| Prepared Parquet | **390 MB** compressed |
| Retained section text | **1.79 GB** uncompressed |
| Retained source tokens | **444,518,010** |
| Chunks at 800/100, resetting at each section | **640,745** |
| Simulated embedding input, including filing prefixes | **529,668,358 tokens** |
| One embedding pass | **about $10.59** |
| One pass with a 20% allowance | **about $12.71** |
| Raw 1536-dimensional float32 vectors | **3.94 GB** |
| Database including text, metadata and index overhead | **roughly 9–15 GB**, engine-dependent |

Costs use the [standard small-model rate](https://developers.openai.com/api/docs/models/text-embedding-3-small) of $0.02 per million input tokens, checked November 3, 2026. Token counts were measured over the complete retained corpus. The simulation counts each filing prefix separately; a different chunker must recount its actual final inputs.

Plan for **about 40 GB total workspace**, including the original archive, prepared data, one active database, an optional text export and build headroom. Database size is a planning estimate: verify a pilot before building the full index. Keep total workspace below 45 GB to leave room under the 50 GB limit.

The embedding budget is cumulative. A second complete pass would bring the baseline cost to about $21.19 before allowances. Reuse the same embeddings for retrieval, hybrid-search and reranking experiments where possible. Question generation, answering, judging and database hosting are separate costs. No paid embeddings were generated during preparation.

## Valid evaluation questions

**`questions.jsonl` contains 50 questions across five categories, including 10 connected multi-document questions.** Twenty-eight previous questions were retained and 22 were replaced to match this section rule. Stable IDs have gaps intentionally.

All **102 evidence references** were verified inside the exact prepared corpus; all **27 recorded calculations** passed. Every question source is a retained 10-K or 10-Q. Evidence carries document IDs, hashes and original character offsets. Pass each question's `as_of` cutoff to the answering system; keep expected answers, evidence and grading points with the evaluator. Narrative answers received editorial review, not an external judge run.

## Reproduce and validate

From the repository root:

```bash
python -m pip install duckdb tiktoken
python scripts/prepare_sec_sections.py \
  --output data/financial_sections.parquet \
  --validate-questions data/questions.jsonl
```

This performs local preparation and validation only; it does not call an embedding API. The output is one row per retained filing. Within `sections`, `text` is the embeddable content and `start_char`/`end_char` refer to the original filing text.
