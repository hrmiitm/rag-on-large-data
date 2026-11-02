#!/usr/bin/env python3
"""Install pinned Lume and ingest the prepared SEC corpus into ../db (BM25 only).

Run: python lume/bm25/src/setup.py
Dependencies: pyarrow==26.0.0, tiktoken==0.14.0. No embedding or LLM calls.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import sqlite3
import subprocess
import tarfile
import urllib.request

SRC = Path(__file__).resolve().parent
HOME = SRC.parent
REPO = SRC.parents[2]
DB = HOME / "db"
BIN = SRC / "bin" / "lume"
HELPER = SRC / "native" / "target" / "release" / "lume-bm25-bounded"
VERSION = "v0.16.3"
SOURCE_COMMIT = "f031390f0f4afdeeb14d609775ce51617d1a3f2c"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


@contextlib.contextmanager
def database_lock():
    with (DB / ".lock").open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another setup/eval process is using this database")
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def runtime_env():
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("LUME_", "BM25_", "SHIVVR_", "NUTS_", "OLLAMA_", "LLMFOUNDRY_")) or key in ("ALPHA", "GRAPH_ALPHA"):
            env.pop(key)
    runtime = DB / "runtime"
    runtime.mkdir(exist_ok=True)
    env.update(HOME=str(runtime), XDG_CACHE_HOME=str(runtime), TMPDIR=str(runtime),
               LUME_STEM="1", LUME_TITLE_FALLBACK="0")
    return env


def install_lume():
    if BIN.exists():
        if VERSION[1:] not in subprocess.check_output([str(BIN), "--version"], text=True):
            raise RuntimeError("Unexpected Lume version in src/bin")
        return
    arch = {"x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}[platform.machine()]
    system = {"Linux": "unknown-linux-gnu", "Darwin": "apple-darwin"}[platform.system()]
    name = f"lume-{VERSION}-{arch}-{system}"
    url = f"https://github.com/DeepBlueDynamics/lume/releases/download/{VERSION}"
    cache = SRC / ".cache"
    cache.mkdir(exist_ok=True)
    archive = cache / (name + ".tar.gz")
    sums = urllib.request.urlopen(url + "/SHA256SUMS", timeout=60).read().decode()
    expected = next(line.split()[0] for line in sums.splitlines() if line.split()[-1] == archive.name)
    if not archive.exists() or sha256(archive) != expected:
        urllib.request.urlretrieve(url + "/" + archive.name, archive)
    if sha256(archive) != expected:
        raise RuntimeError("Lume download checksum mismatch")
    BIN.parent.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:
        member = next(m for m in tar.getmembers() if m.isfile() and Path(m.name).name == "lume")
        with tar.extractfile(member) as src, BIN.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    BIN.chmod(0o755)
    install_lume()


def windows(text, enc):
    ids = enc.encode_ordinary(text)
    raw, last_byte, last_char, token_byte = text.encode(), 0, 0, 0
    for start in range(0, len(ids), 700):
        end = min(start + 800, len(ids))
        a, b = token_byte, token_byte + len(enc.decode_bytes(ids[start:end]))
        while a and a < len(raw) and raw[a] & 0xC0 == 0x80:
            a -= 1
        while b < len(raw) and raw[b] & 0xC0 == 0x80:
            b -= 1
        first = last_char + len(raw[last_byte:a].decode())
        body = raw[a:b].decode()
        yield first, first + len(body), body
        last_byte, last_char = a, first
        if end == len(ids):
            break
        token_byte += len(enc.decode_bytes(ids[start:start + 700]))


def prepare_questions():
    source = REPO / "data" / "questions.jsonl"
    before = sha256(source)
    original = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    if len(original) != 50 or len({q["id"] for q in original}) != 50:
        raise RuntimeError("Expected 50 distinct source questions")
    # Reference answers, evidence and grading instructions are never copied.
    target = SRC / "questions.jsonl"
    target.write_text("".join(json.dumps({k: q[k] for k in ("id", "question", "as_of")}, ensure_ascii=False) + "\n" for q in original))
    if sha256(source) != before:
        raise RuntimeError("Original questions changed during setup")
    return sha256(target)



def memory_limit(megabytes=2048):
    resource.setrlimit(resource.RLIMIT_AS, (megabytes << 20, megabytes << 20))


def limited_command(command, megabytes=2048):
    limiter = shutil.which("prlimit")
    if not limiter:
        raise RuntimeError("Memory-safe execution requires prlimit from util-linux")
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        available = next(int(line.split()[1])*1024 for line in meminfo.read_text().splitlines() if line.startswith("MemAvailable:"))
        if available < (megabytes+256) << 20:
            raise RuntimeError("Insufficient free RAM for a bounded native process; close other applications and resume")
    return [limiter, f"--as={megabytes << 20}", "--", *command]


def run_bounded(command, log, limit_mb=2048, timeout=900):
    return subprocess.run(limited_command(command, limit_mb), cwd=HOME, env=runtime_env(), stdout=log,
                          stderr=subprocess.STDOUT, check=True, timeout=timeout)


def build_helper():
    if HELPER.exists():
        return
    vendor = SRC / "native" / "vendor" / "lume"
    if not vendor.exists():
        subprocess.run(["git", "clone", "https://github.com/DeepBlueDynamics/lume.git", str(vendor)], check=True)
        subprocess.run(["git", "-C", str(vendor), "checkout", SOURCE_COMMIT], check=True)
    env = dict(os.environ, RUSTUP_HOME=str(SRC / ".rustup"), CARGO_HOME=str(SRC / ".cargo"), CARGO_BUILD_JOBS="1")
    cargo = SRC / ".cargo" / "bin" / "cargo"
    if not cargo.exists():
        script = SRC / ".cache" / "rustup-init.sh"
        urllib.request.urlretrieve("https://sh.rustup.rs", script)
        subprocess.run(["sh", str(script), "-y", "--profile", "minimal", "--no-modify-path", "--default-toolchain", "stable"], env=env, check=True)
    with (SRC / ".cache" / "native-build.log").open("w") as log:
        subprocess.run([str(cargo), "build", "--release", "--jobs", "1", "--manifest-path", str(SRC / "native" / "Cargo.toml")], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)


def export_corpus(source_hash, limit, shard_chunks):
    import pyarrow.parquet as pq
    os.environ["TIKTOKEN_CACHE_DIR"] = str(SRC / ".cache" / "tiktoken")
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    specification = {"source_sha256": source_hash, "limit_documents": limit, "body_tokens": 800,
                     "overlap": 100, "encoding": "cl100k_base", "shard_chunks": shard_chunks, "format": 2}
    state = DB / "export.json"
    if state.exists():
        previous = json.loads(state.read_text())
        if any(previous.get(k) != v for k, v in specification.items()):
            raise RuntimeError("Existing database uses different inputs; remove db contents before rebuilding")
        if previous.get("complete"):
            return previous
    else:
        save(state, specification)
    corpus = DB / "corpus"
    corpus.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB / "chunks.sqlite")
    conn.execute("CREATE TABLE IF NOT EXISTS chunks(file TEXT,line INTEGER,document_id TEXT,source_hash TEXT,shard TEXT,filing_date INTEGER,section TEXT,section_start INTEGER,section_end INTEGER,start_char INTEGER,end_char INTEGER,title TEXT,body TEXT,PRIMARY KEY(file,line))")
    conn.execute("CREATE TABLE IF NOT EXISTS documents(document_id TEXT PRIMARY KEY,shard_id INTEGER,chunks INTEGER)")
    completed = {r[0] for r in conn.execute("SELECT document_id FROM documents")}
    last = conn.execute("SELECT COALESCE(MAX(shard_id),0) FROM documents").fetchone()[0]
    used = conn.execute("SELECT COALESCE(SUM(chunks),0) FROM documents WHERE shard_id=?", (last,)).fetchone()[0]
    fields = ["document_id","md5","shard","company","form","filing_date","sections","chunks_800_overlap100"]
    # Arrow streams individual rows instead of decoding the entire nested text column.
    parquet = pq.ParquetFile(DB / "financial_sections.parquet")
    for number, batch in enumerate(parquet.iter_batches(batch_size=1, columns=fields, use_threads=False)):
        if limit is not None and number >= limit:
            break
        for record in batch.to_pylist():
            docid, md5, shard, company, form, date, sections, planned = (record[k] for k in fields)
            if docid in completed:
                continue
            if not re.fullmatch(r"[A-Za-z0-9_-]+", docid):
                raise RuntimeError("Invalid filing ID")
            date = int(date.replace("-", ""))
            title = f"Company: {company} | Form: {form} | Filed: {date} | Document: {docid}"
            file, line = docid + ".txt", 1
            if used and used + planned > shard_chunks:
                last += 1
                used = 0
            target = corpus / f"shard-{last:04d}"
            target.mkdir(exist_ok=True)
            with (target / file).open("w") as output:
                for section in sections:
                    if len(section["text"]) != section["end_char"] - section["start_char"]:
                        raise RuntimeError("Source section offsets are inconsistent")
                    for a, b, body in windows(section["text"], enc):
                        output.write(re.sub(r"\s+", " ", title + " " + body).strip() + "\n" * 25)
                        conn.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (file,line,docid,md5,shard,date,section["section"],section["start_char"],section["end_char"],section["start_char"]+a,section["start_char"]+b,title,body))
                        line += 25
            actual = (line - 1) // 25
            if actual != planned:
                raise RuntimeError(f"Chunk-count mismatch for {docid}")
            conn.execute("INSERT INTO documents VALUES(?,?,?)", (docid,last,actual))
            conn.commit()
            completed.add(docid)
            used += actual
        if len(completed) % 100 == 0:
            print(f"Exported {len(completed)} filings", flush=True)
    shards = []
    for shard_id, count in conn.execute("SELECT shard_id,SUM(chunks) FROM documents GROUP BY shard_id ORDER BY shard_id"):
        name = f"shard-{shard_id:04d}"
        with (corpus / name / "lume.meta.jsonl").open("w") as f:
            for (docid,) in conn.execute("SELECT document_id FROM documents WHERE shard_id=?", (shard_id,)):
                file = docid + ".txt"
                date = conn.execute("SELECT filing_date FROM chunks WHERE file=? AND line=1", (file,)).fetchone()[0]
                f.write(json.dumps({"path": file, "fields": {"filing_date": date}}) + "\n")
        save(corpus / name / "lume.schema.json", {"filing_date": "integer"})
        shards.append({"name": name, "chunks": count, "index": "index/" + name})
    conn.commit()
    specification.update(complete=True, documents=len(completed), chunks=conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], shards=shards)
    conn.close()
    save(state, specification)
    return specification


def build_indexes(manifest, memory_mb):
    stats = DB / "stats"
    stats.mkdir(exist_ok=True)
    for i, shard in enumerate(manifest["shards"], 1):
        path = DB / shard["index"]
        sealed = path / "ready.json"
        if sealed.exists():
            continue
        with (stats / (shard["name"] + ".log")).open("w") as log:
            run_bounded([str(BIN),"index",str(DB / "corpus" / shard["name"]),"--db",str(path)], log, memory_mb)
            run_bounded([str(HELPER),"stats",str(path),str(stats / (shard["name"] + ".json"))], log, memory_mb)
        local = json.loads((stats / (shard["name"] + ".json")).read_text())
        if local["num_docs"] != shard["chunks"]:
            raise RuntimeError("Shard lost chunks during ingestion")
        save(sealed, {"chunks": local["num_docs"]})
        print(f"Indexed shard {i}/{len(manifest['shards'])}: {shard['chunks']} chunks", flush=True)
    # Global corpus statistics keep scores comparable across shards.
    aggregate = sqlite3.connect(stats / "global.sqlite")
    aggregate.execute("DROP TABLE IF EXISTS df")
    aggregate.execute("CREATE TABLE df(term TEXT PRIMARY KEY,title INTEGER,body INTEGER)")
    n = title_sum = body_sum = 0
    for shard in manifest["shards"]:
        local = json.loads((stats / (shard["name"] + ".json")).read_text())
        n += local["num_docs"]
        title_sum += local["title_length_sum"]
        body_sum += local["body_length_sum"]
        for field, col in (("title_dfs", "title"),("body_dfs", "body")):
            aggregate.executemany(f"INSERT INTO df VALUES(?,?,?) ON CONFLICT(term) DO UPDATE SET {col}={col}+excluded.{col}",
                ((word,count if col=="title" else 0,count if col=="body" else 0) for word,count in local[field].items()))
        aggregate.commit()
    if n != manifest["chunks"]:
        raise RuntimeError("Global corpus count is inconsistent")
    with (DB / "global-stats.json").open("w") as output:
        head = {"num_docs": n, "avg_title_len": title_sum/n, "avg_body_len": body_sum/n}
        output.write(json.dumps(head)[:-1] + ',"terms":{')
        separator = ""
        for word,title,body in aggregate.execute("SELECT term,title,body FROM df ORDER BY term"):
            output.write(separator + json.dumps(word) + ":" + json.dumps([title,body]))
            separator = ","
        output.write("}}\n")
    aggregate.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-documents", type=int, help="Optional small pilot; omit for all filings")
    parser.add_argument("--shard-chunks", type=int, default=20000)
    parser.add_argument("--memory-limit-mb", type=int, default=2048)
    args = parser.parse_args()
    if args.limit_documents is not None and args.limit_documents < 1:
        parser.error("--limit-documents must be positive")
    if not 1000 <= args.shard_chunks <= 20000 or not 512 <= args.memory_limit_mb <= 3072:
        parser.error("Use 1000..20000 chunks per shard and a 512..3072 MB child memory limit")
    DB.mkdir(parents=True, exist_ok=True)
    with database_lock():
        source = REPO / "data" / "financial_sections.parquet"
        before = sha256(source)
        copy = DB / source.name
        if not copy.exists():
            temp = copy.with_suffix(".tmp")
            shutil.copyfile(source, temp)
            temp.replace(copy)
        if sha256(copy) != before:
            raise RuntimeError("Copied corpus differs from original")
        questions_hash = prepare_questions()
        install_lume()
        manifest = export_corpus(before, args.limit_documents, args.shard_chunks)
        build_helper()
        config = {**manifest, "lume_version": VERSION, "source_commit": SOURCE_COMMIT, "helper_sha256": sha256(HELPER), "memory_limit_mb": args.memory_limit_mb, "global_stats": "global-stats.json", "binary_sha256": sha256(BIN), "questions_sha256": questions_hash, "alpha": 0, "graph": 0}
        ready = DB / "config.json"
        if ready.exists():
            previous = json.loads(ready.read_text())
            if all(previous.get(k) == v for k, v in config.items()):
                stats_hash = sha256(DB / "global-stats.json")
                if previous.get("global_stats_sha256", stats_hash) != stats_hash:
                    raise RuntimeError("Global BM25 statistics changed; inspect before reusing this database")
                config["global_stats_sha256"] = stats_hash
                save(ready, config)
                print("BM25 database already built with these settings")
                return
        build_indexes(manifest, args.memory_limit_mb)
        if sha256(source) != before:
            raise RuntimeError("Original corpus changed during setup")
        config["global_stats_sha256"] = sha256(DB / "global-stats.json")
        save(ready, config)
        print(f"BM25 ready: {manifest['documents']} filings / {manifest['chunks']} chunks in {DB / 'index'}")


if __name__ == "__main__":
    main()
