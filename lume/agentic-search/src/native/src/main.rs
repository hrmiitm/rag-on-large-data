//! Bounded-memory access to unmodified Lume BM25. Each shard is opened and
//! dropped sequentially. Only scoring statistics are replaced in memory;
//! stored shard files and local document IDs remain unchanged.
use lume::search::{search, LoadedIndex, SearchMode, SearchOptions};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::{collections::HashMap, env, fs, path::Path, time::Instant};

#[derive(Deserialize)]
struct Shard { index: String }
#[derive(Deserialize)]
struct Manifest { shards: Vec<Shard>, global_stats: String }
#[derive(Deserialize)]
struct GlobalStats {
    num_docs: usize,
    avg_title_len: f64,
    avg_body_len: f64,
    terms: HashMap<String, [usize; 2]>,
}
#[derive(Serialize)]
struct Hit { file: String, line: usize, score: f64 }

fn read<T: serde::de::DeserializeOwned>(path: &Path) -> Result<T, String> {
    let file = fs::File::open(path).map_err(|e| e.to_string())?;
    serde_json::from_reader(std::io::BufReader::new(file)).map_err(|e| e.to_string())
}

fn peak_rss_kib() -> Option<u64> {
    fs::read_to_string("/proc/self/status").ok()?.lines()
        .find(|line| line.starts_with("VmHWM:"))?
        .split_whitespace().nth(1)?.parse().ok()
}

fn run() -> Result<(), String> {
    let args: Vec<String> = env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("stats") if args.len() == 4 => {
            let index = LoadedIndex::open(&args[2])?;
            let b = &index.bm25;
            let title: HashMap<_, _> = b.title_dfs.iter().map(|(k, v)| (String::from_utf8_lossy(k).into_owned(), *v)).collect();
            let body: HashMap<_, _> = b.body_dfs.iter().map(|(k, v)| (String::from_utf8_lossy(k).into_owned(), *v)).collect();
            let output = fs::File::create(&args[3]).map_err(|e| e.to_string())?;
            serde_json::to_writer(std::io::BufWriter::new(output), &json!({
                "num_docs": b.sections.len(), "title_length_sum": b.title_lens.iter().sum::<usize>(),
                "body_length_sum": b.body_lens.iter().sum::<usize>(), "title_dfs": title, "body_dfs": body
            })).map_err(|e| e.to_string())?;
        }
        Some("search" | "search-batch") if args.len() == 5 => {
            let started = Instant::now();
            let manifest_path = Path::new(&args[2]);
            let root = manifest_path.parent().ok_or("Manifest has no parent")?;
            let manifest: Manifest = read(manifest_path)?;
            let global: GlobalStats = read(&root.join(&manifest.global_stats))?;
            let k: usize = args[4].parse().map_err(|_| "Invalid limit")?;
            let queries: Vec<String> = if args[1] == "search-batch" { read(Path::new(&args[3]))? } else { vec![args[3].clone()] };
            let mut hits: Vec<Vec<Hit>> = queries.iter().map(|_| Vec::new()).collect();
            let mut scoring_ms = vec![0.0; queries.len()];
            for shard in &manifest.shards {
                let mut index = LoadedIndex::open(root.join(&shard.index))?;
                // This public Lume method initializes compact postings using LOCAL
                // document IDs before corpus-wide N is applied for IDF scoring.
                index.bm25.compact_for_v4()?;
                if index.bm25.sections.len() > global.num_docs { return Err("Invalid global document count".into()); }
                for (word, df) in index.bm25.title_dfs.iter_mut() {
                    let key = std::str::from_utf8(word).map_err(|e| e.to_string())?;
                    *df = global.terms.get(key).ok_or("Missing global title DF")?[0];
                }
                for (word, df) in index.bm25.body_dfs.iter_mut() {
                    let key = std::str::from_utf8(word).map_err(|e| e.to_string())?;
                    *df = global.terms.get(key).ok_or("Missing global body DF")?[1];
                }
                index.bm25.num_docs = global.num_docs;
                index.bm25.avg_title_len = global.avg_title_len;
                index.bm25.avg_body_len = global.avg_body_len;
                let opts = SearchOptions { limit: k, mode: SearchMode::LexicalOnly,
                    alpha: 0.0, graph_beta: 0.0, ..Default::default() };
                for (i, query) in queries.iter().enumerate() {
                    let search_started = Instant::now();
                    let result = search(&index, query, &opts)?;
                    scoring_ms[i] += search_started.elapsed().as_secs_f64()*1000.0;
                    for hit in result.hits {
                        hits[i].push(Hit { file: hit.filename.ok_or("Missing source file")?, line: hit.line_number, score: hit.score });
                    }
                }
                // Drop index here; never hold multiple shard indexes in memory.
            }
            let wall_ms = started.elapsed().as_secs_f64()*1000.0;
            let mut results = Vec::new();
            for (i, mut hits) in hits.into_iter().enumerate() {
                hits.sort_by(|a, b| b.score.total_cmp(&a.score).then(a.file.cmp(&b.file)).then(a.line.cmp(&b.line)));
                hits.truncate(k);
                results.push(json!({"hits": hits, "shard_queries": manifest.shards.len(), "search_ms": wall_ms,
                    "query_scoring_ms": scoring_ms[i], "peak_rss_kib": peak_rss_kib()}));
            }
            if args[1] == "search" {
                println!("{}", results.first().ok_or("No query")?);
            } else {
                println!("{}", json!({"results": results, "batch_wall_ms": wall_ms}));
            }
        }
        _ => return Err("Usage: lume-bm25-bounded stats INDEX OUT | search MANIFEST QUERY K".into()),
    }
    Ok(())
}
fn main() {
    if let Err(error) = run() { eprintln!("{error}"); std::process::exit(1); }
}
