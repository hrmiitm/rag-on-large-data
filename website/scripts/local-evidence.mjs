import fs from 'node:fs/promises';import path from 'node:path';import {hash} from './normalize.mjs';
// Optional, read-only evidence enrichment. The compact exports remain authoritative for every answer and metric.
export async function readLocalEvidence(root,sourceFile){
 if(typeof sourceFile!=='string'||!/^lume\/[a-zA-Z0-9_-]+\/q-a\.jsonl$/.test(sourceFile))return null;
 let bytes;try{const file=path.join(root,sourceFile);const stat=await fs.stat(file);if(stat.size>128*1024*1024)return {warning:`${sourceFile}: local passage snapshot exceeds 128 MiB; compact metadata retained.`};bytes=await fs.readFile(file);}catch(e){if(e.code==='ENOENT')return null;throw e;}
 const records=new Map();let parsed=0;
 for(const line of bytes.toString().split(/\r?\n/)){if(!line.trim())continue;try{const r=JSON.parse(line);if(r.schema_version==='rag-benchmark/1.0'){records.set(JSON.stringify([r.question_id,r.configuration_hash,r.run_id]),r);parsed++;}}catch{/* A partial raw snapshot never invalidates authoritative final results. */}}
 return {records,snapshot:{file:sourceFile,sha256:hash(bytes),records:parsed,bytes:bytes.length,scope:'Optional retrieved text only; authoritative metrics and answers come from final-results.'}};
}
export function enrichEvidence(d,record,local){
 const raw=local?.records?.get(JSON.stringify([record.question_id,record.configuration_hash,record.run_id]));let enriched=0;
 if(!raw||raw.provenance?.corpus_sha256!==record.provenance?.corpus_sha256)return {detail:d,enriched};
 const allChunks=[...(raw.retrieval?.chunks??[]),...Object.values(raw.answers??{}).flatMap(a=>a.retrieval?.chunks??[])];
 const byId=new Map(allChunks.filter(c=>typeof c.text==='string').map(c=>[c.chunk_id,c]));
 const fill=chunks=>{for(const c of chunks??[]){const source=byId.get(c.chunk_id);if(!source||source.document_id!==c.document_id)continue;const fields=['hash','start_char','end_char'];if(!fields.every(k=>c.source?.[k]!=null&&source.source?.[k]===c.source[k]))continue;c.text=source.text;c.passage_origin={file:local.snapshot.file,snapshot_sha256:local.snapshot.sha256,matched_on:['question_id','configuration_hash','run_id','corpus_sha256','chunk_id','document_id','source.hash','source.start_char','source.end_char']};enriched++;}};
 fill(d.retrieval?.chunks);for(const a of Object.values(d.answers))fill(a.retrieval?.chunks);
 d.evidenceAvailability={retrievedPassages:enriched,sourceSnapshot:local.snapshot.sha256};return {detail:d,enriched};
}
