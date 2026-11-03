//! Sequential bounded Lume shards, native local vectors and native hybrid fusion.
use lume::search::{search, LoadedIndex, SearchMode, SearchOptions};
use lume::bm25::SearchHit;
use lume::hybrid::{section_hash, blend_hybrid_scores};
use serde::Deserialize;
use serde_json::json;
use std::{collections::HashMap, env, fs, path::Path, time::Instant, io::Write};

#[derive(Deserialize)] struct Shard { index: String }
#[derive(Deserialize)] struct Manifest { shards: Vec<Shard>, global_stats: String, technique: String }
#[derive(Deserialize)] struct Stats { num_docs: usize, avg_title_len: f64, avg_body_len: f64, terms: HashMap<String,[usize;2]> }
#[derive(Deserialize)] struct Query { text: String, cutoff: u32 }
fn read<T: serde::de::DeserializeOwned>(p: &Path) -> Result<T,String> {
    serde_json::from_reader(std::io::BufReader::new(fs::File::open(p).map_err(|e|e.to_string())?)).map_err(|e|e.to_string())
}
fn rss() -> Option<u64> { fs::read_to_string("/proc/self/status").ok()?.lines().find(|l|l.starts_with("VmHWM:"))?.split_whitespace().nth(1)?.parse().ok() }
fn run() -> Result<(),String> {
    // Serialize native index opens across ingestion, prefetch and both methods.
    let lock_path=Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap().join("db/native-process.lock");
    let native_lock=fs::OpenOptions::new().create(true).write(true).open(lock_path).map_err(|e|e.to_string())?;
    native_lock.lock().map_err(|e|e.to_string())?;
    let a:Vec<String>=env::args().collect();
    match a.get(1).map(String::as_str) {
        Some("describe") if a.len()==4 => {
            let pause_path=Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap().join("db/ingestion-pause-before.json");
            if pause_path.exists() {
                let pause:serde_json::Value=read(&pause_path)?;
                if Path::new(&a[2]).file_name().and_then(|n|n.to_str())==pause["shard"].as_str() {
                    return Err("Ingestion checkpoint reached; supervisor will resume in its detached process tree".into());
                }
            }
            let idx=LoadedIndex::open(&a[2])?;
            let mut out=std::io::BufWriter::new(fs::File::create(&a[3]).map_err(|e|e.to_string())?);
            for (i,s) in idx.bm25.sections.iter().enumerate() {
                writeln!(out,"{}",json!({"id":section_hash(s),"file":s.filename,"line":s.line_number,"index":i})).map_err(|e|e.to_string())?;
            }
        }
        Some("validate") if a.len()==3 => {
            let mut idx=LoadedIndex::open(&a[2])?;
            idx.local_vectors=lume::local_vectors::LocalVectors::open(Path::new(&a[2]),&idx.bm25.sections)?;
            if idx.local_vectors.is_none() {return Err("Native vectors missing".into())}
            println!("{}",json!({"chunks":idx.bm25.sections.len(),"peak_rss_kib":rss()}));
        }
        Some("search-batch") if a.len()==5 => {
            let start=Instant::now(); let path=Path::new(&a[2]); let root=path.parent().ok_or("No root")?;
            let m:Manifest=read(path)?; let g:Stats=read(&root.join(&m.global_stats))?;
            let queries:Vec<Query>=read(Path::new(&a[3]))?; let k:usize=a[4].parse().map_err(|_|"Invalid k")?;
            let dates:HashMap<String,u32>=read(&root.join("filing-dates.json"))?;
            let mut all:Vec<Vec<serde_json::Value>>=queries.iter().map(|_|Vec::new()).collect();
            let mut scoring=vec![0.;queries.len()];
            for shard in &m.shards {
                let mut idx=LoadedIndex::open(root.join(&shard.index))?;
                idx.local_vectors=lume::local_vectors::LocalVectors::open(&root.join(&shard.index),&idx.bm25.sections)?;
                idx.bm25.compact_for_v4()?;
                for (term,df) in idx.bm25.title_dfs.iter_mut() { *df=g.terms.get(std::str::from_utf8(term).map_err(|e|e.to_string())?).ok_or("Missing DF")?[0]; }
                for (term,df) in idx.bm25.body_dfs.iter_mut() { *df=g.terms.get(std::str::from_utf8(term).map_err(|e|e.to_string())?).ok_or("Missing DF")?[1]; }
                idx.bm25.num_docs=g.num_docs; idx.bm25.avg_title_len=g.avg_title_len; idx.bm25.avg_body_len=g.avg_body_len;
                let vectors=idx.local_vectors.as_ref().ok_or("Dense vectors required; no lexical fallback")?;
                let hashes:HashMap<String,usize>=idx.bm25.sections.iter().enumerate().map(|(i,s)|(section_hash(s),i)).collect();
                for (qi,q) in queries.iter().enumerate() {
                    let t=Instant::now();
                    // All candidates, then cutoff, then top-k. No post-top-k date loss.
                    let (mut sem,cached)=vectors.search(&q.text,"http://127.0.0.1:9",None,usize::MAX)?;
                    if !cached { return Err("Query vector must be preloaded".into()) }
                    sem.retain(|s|s.source.as_ref().and_then(|h|hashes.get(h)).and_then(|i|idx.bm25.sections[*i].filename.as_ref()).and_then(|f|Path::new(f).file_name()).and_then(|n|n.to_str()).and_then(|f|dates.get(f)).is_some_and(|d|*d<=q.cutoff));
                    let lex=if m.technique=="hybrid" {
                        let opts=SearchOptions{limit:idx.bm25.sections.len(),mode:SearchMode::LexicalOnly,alpha:0.,graph_beta:0.,..Default::default()};
                        search(&idx,&format!("{} filing_date:<={}",q.text,q.cutoff),&opts)?.hits.into_iter().map(|h|SearchHit{section_index:h.section_index,score:h.score}).collect::<Vec<_>>()
                    } else {Vec::new()};
                    let fused=if m.technique=="hybrid" {blend_hybrid_scores(&lex,&sem,&HashMap::new(),&hashes,0.5,0.)} else {
                        blend_hybrid_scores(&[],&sem,&HashMap::new(),&hashes,0.5,0.)
                    };
                    let mut hits=Vec::new();
                    for h in fused {
                        let s=&idx.bm25.sections[h.section_index];
                        let f=s.filename.as_ref().ok_or("No file")?;
                        let name=Path::new(f).file_name().and_then(|n|n.to_str()).ok_or("Bad file")?;
                        if dates.get(name).ok_or("Missing filing date")?>&q.cutoff {return Err("Cutoff violated".into())}
                        hits.push(json!({"file":f,"line":s.line_number,"score":h.hybrid_score,"scores":{"bm25":h.bm25_score,"cosine":h.semantic_score,"hybrid":if m.technique=="hybrid" {Some(h.hybrid_score)} else {None}}}));
                    }
                    hits.sort_by(order); hits.truncate(k); all[qi].extend(hits); scoring[qi]+=t.elapsed().as_secs_f64()*1000.;
                }
            }
            let ms=start.elapsed().as_secs_f64()*1000.; let mut result=Vec::new();
            for (i,mut hits) in all.into_iter().enumerate() {hits.sort_by(order);hits.truncate(k); result.push(json!({"hits":hits,"shard_queries":m.shards.len(),"search_ms":ms,"query_scoring_ms":scoring[i],"peak_rss_kib":rss()}));}
            println!("{}",json!({"results":result,"batch_wall_ms":ms}));
        }
        _=>return Err("describe INDEX OUT | validate INDEX | search-batch CONFIG QUERIES K".into())
    } Ok(())
}
fn order(a:&serde_json::Value,b:&serde_json::Value)->std::cmp::Ordering {b["score"].as_f64().unwrap().total_cmp(&a["score"].as_f64().unwrap()).then(a["file"].as_str().cmp(&b["file"].as_str())).then(a["line"].as_u64().cmp(&b["line"].as_u64()))}
fn main(){if let Err(e)=run(){eprintln!("{e}");std::process::exit(1)}}
