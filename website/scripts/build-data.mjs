import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import Ajv2020 from 'ajv/dist/2020.js';
import {normalize,detail,hash,methodName,sanitize} from './normalize.mjs';
import {readLocalEvidence,enrichEvidence} from './local-evidence.mjs';
const here=path.dirname(fileURLToPath(import.meta.url));
export async function buildData({root=path.resolve(here,'../..'),out=path.resolve(here,'../public/data')}={}) {
 const folder=path.join(root,'judge/final-results'), warnings=[], rows=[], details=new Map(), sources=[];
 const schemaBytes=await fs.readFile(path.join(root,'judge/evaluation.schema.json'));
 const validate=new Ajv2020({strict:false,allErrors:true}).compile(JSON.parse(schemaBytes));
 let files=[];try{files=(await fs.readdir(folder)).filter(f=>f.endsWith('.jsonl')).sort();}catch(e){if(e.code!=='ENOENT')throw e;}
 const unique=new Map(),localEvidence=new Map(),evidenceSnapshots=[];
 for(const file of files){
  let method;try{method=methodName(file);}catch(e){warnings.push(e.message);continue;}
  const bytes=await fs.readFile(path.join(folder,file)), stat=await fs.stat(path.join(folder,file));
  const source={file,method,sha256:hash(bytes),bytes:bytes.length,modifiedAt:stat.mtime.toISOString(),validRecords:0,invalidRecords:0};sources.push(source);
  for(const [i,line] of bytes.toString().split(/\r?\n/).entries()){
   if(!line.trim())continue;
   try{
    const r=JSON.parse(line);
    if(!validate(r)||typeof r.question_id!=='string'||typeof r.question!=='string'||!r.question_id||!Object.keys(r.answers).length)throw Error(validate.errors?.map(e=>`${e.instancePath} ${e.message}`).join('; ')||'Missing question ID, text or answers');
    const normalized=normalize(r,file);source.validRecords++;
    const localFile=r.judge_provenance?.source_file;
    if(localFile&&!localEvidence.has(localFile)){const local=await readLocalEvidence(root,localFile);localEvidence.set(localFile,local);if(local?.snapshot)evidenceSnapshots.push(local.snapshot);if(local?.warning)warnings.push(local.warning);}
    const enriched=enrichEvidence(detail(r,file),r,localEvidence.get(localFile)).detail;
    for(const row of normalized){const old=unique.get(row.id);if(old){warnings.push(`${file}:${i+1}: duplicate evaluation; keeping latest updated_at.`);if(String(old.row.updatedAt)>String(row.updatedAt))continue;}unique.set(row.id,{row,detail:enriched});}
   }catch(e){source.invalidRecords++;warnings.push(`${file}:${i+1}: ${e.message}`);}
  }
 }
 for(const {row,detail:d} of unique.values()){rows.push(row);if(!details.has(row.detailId))details.set(row.detailId,new Map());details.get(row.detailId).set(`${d.method}:${row.configuration}`,d);}
 rows.sort((a,b)=>a.questionId.localeCompare(b.questionId)||a.method.localeCompare(b.method)||a.model.localeCompare(b.model)||a.configuration.localeCompare(b.configuration));
 const qBytes=await fs.readFile(path.join(root,'data/questions.jsonl'));const questions=qBytes.toString().split(/\r?\n/).filter(x=>x.trim()).map(JSON.parse).map(q=>({id:q.id,question:q.question,category:q.category,asOf:q.as_of}));
 const datasetBytes=await fs.readFile(path.join(root,'website/dataset.json'));const dataset=JSON.parse(datasetBytes);
 const version=hash({normalized:hash(rows),evidenceSnapshots,evidenceCode:hash(await fs.readFile(path.join(here,'local-evidence.mjs'))),sources:sources.map(s=>[s.file,s.sha256]),questions:hash(qBytes),schema:hash(schemaBytes),dataset:hash(datasetBytes),normalizer:hash(await fs.readFile(path.join(here,'normalize.mjs'))),builder:hash(await fs.readFile(fileURLToPath(import.meta.url)))}).slice(0,20);
 const manifest={schema:'sec-rag-site/1.0',version,publishedAt:new Date().toISOString(),evidenceSnapshots,sourceUpdatedAt:sources.map(s=>s.modifiedAt).sort().at(-1)??null,sources,warnings:sanitize(warnings),records:rows.length,methods:[...new Set(rows.map(r=>r.method))].sort(),models:[...new Set(rows.map(r=>r.model))].sort(),categories:[...new Set([...questions.map(q=>q.category),...rows.map(r=>r.category)])].sort(),data:`${version}/evaluations.json`,details:`${version}/questions/`,dataset,questionCount:questions.length,questionsSha256:hash(qBytes),scoreScale:{min:0,max:1,display:'percentage'}};
 const versionDir=path.join(out,version);await fs.mkdir(path.join(versionDir,'questions'),{recursive:true});
 await fs.writeFile(path.join(versionDir,'evaluations.json'),JSON.stringify({rows,questions}));
 await Promise.all([...details].map(([id,ds])=>fs.writeFile(path.join(versionDir,'questions',`${id}.json`),JSON.stringify([...ds.values()]))));
 await fs.writeFile(path.join(out,'manifest.json.tmp'),JSON.stringify(manifest,null,2));await fs.rename(path.join(out,'manifest.json.tmp'),path.join(out,'manifest.json'));
 // Old hashed assets remain available until the new manifest is ready.
 for(const entry of await fs.readdir(out,{withFileTypes:true}))if(entry.isDirectory()&&/^[a-f0-9]{20}$/.test(entry.name)&&entry.name!==version)await fs.rm(path.join(out,entry.name),{recursive:true});
 return manifest;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){const m=await buildData();console.log(`Data ${m.version}: ${m.records} evaluations, ${m.methods.length} methods, ${m.warnings.length} warnings.`);if(m.warnings.length)console.warn(m.warnings.join('\n'));}
