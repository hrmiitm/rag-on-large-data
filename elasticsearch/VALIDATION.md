# Measured ingestion validation

This page records the earlier ingestion stage. The subsequent full live
evaluation and judging are complete; see [RESULTS.md](RESULTS.md).

The complete local Elasticsearch ingestion passed. This records ingestion and
search smoke verification only; no answer generation, judging or full retrieval
quality benchmark was run.

| Measurement | Result |
| --- | --- |
| Filings | 10,469 |
| Indexed chunks / existing vectors | 640,745 / 640,745 |
| Active import time, including trial and final refresh/flush | 650.80 seconds (10.85 minutes) |
| Final indexed-data validation | 115.54 seconds (1.93 minutes) |
| Source-Parquet verification, overlapped with import | 20.11 seconds |
| Import plus final validation | 12.77 minutes; excludes image download and implementation/setup |
| Reported Elasticsearch indexing failures | 0 |
| Cluster health | Green |
| Observed Elasticsearch memory | Approximately 2.5–2.8 GiB; configured cap 4 GiB, JVM heap 2 GiB |
| Importer peak resident memory | 177.94 MiB |
| Final indexed-data validator peak resident memory | 220.29 MiB |
| Separate original-Parquet validation peak memory | Approximately 970 MiB |
| Index store near completion | Approximately 9.58 GB decimal; changes while background segments merge |
| Data directory near completion | Approximately 9.1 GiB, including temporary/operational data |
| Official image size | 916,795,479 bytes; shared Docker storage accounting may differ |
| New embeddings / paid model requests / API spend | 0 / 0 / $0 |

All 640,745 SQLite text slices, dates, company/form titles and source hashes were
checked against the original prepared Parquet. Every indexed chunk's complete
stored text, metadata, stable identity and vector checksum was compared against
the read-only source database and native vectors. All 33 native vector sidecar
checksums matched; all 2,521 original embedding batch receipts matched their
exact text inputs, IDs and vector bytes. A further 99 actual stored Elasticsearch
vectors were read back and their directions compared with the original vectors.
The source SQLite checksum remained unchanged.

Keyword and ANN vector searches returned ten passages and respected each of
three filing-date cutoffs. The three smoke searches recorded lexical Elasticsearch
times of 39–113 ms and dense times of 224–608 ms. These are a few smoke requests,
not a latency benchmark, an ANN recall measurement or evidence of answer quality.
The initial 2,048-chunk trial also verified vector readback and a self-match
ranking first. Full-corpus ANN recall and gold-evidence coverage remain untested.

Seven offline tests passed: vector wire encoding/invalid values, native format
parsing/corruption, preserved source metadata/text, permanent bulk failures,
partial bulk responses, failed-item-only retries and explicit mappings. The
trial paused after 2,048 chunks and resumed to the complete corpus. A completed
resume preserved ready status, checked document/vector counts and performed zero
indexing writes.

The ignored `db/validation-report.json`, `db/source-validation.json`,
`db/ingestion-report.json`, `db/trial-report.json` and `db/ingestion-state.json`
hold detailed measurements and source/config fingerprints. `src/status.py`
reports current memory, progress and storage; the table above is a snapshot.
No existing method source/output/environment/database or active job was changed.

The service remains running at `http://127.0.0.1:19200` for the next stage. Stop
only this experiment with `docker compose -f elasticsearch/compose.yaml stop` to
release its RAM while keeping the completed index.
