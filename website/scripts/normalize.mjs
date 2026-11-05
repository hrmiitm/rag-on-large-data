import {numeric,scoreKeys} from '../src/data.mjs';
import {createHash} from 'node:crypto';
export const hash = x=>createHash('sha256').update(typeof x==='string'||Buffer.isBuffer(x)?x:JSON.stringify(x)).digest('hex');
// Only presentation fields are exported. These removals also protect future schema additions.
const blocked=/^(authorization|api_?key|token|password|secret|base_url|generation_statistics|api_calls|request|response|raw.*|trace|messages|reasoning_details|agent_state|batch_result|batch_metadata)$/i;
export function sanitize(value) {
 if(typeof value==='string')return value.replace(/(?:\/home\/|\/Users\/|[A-Z]:\\)[^\s"']+/g,'[local path omitted]');
 if(Array.isArray(value))return value.map(sanitize);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).filter(([k])=>!blocked.test(k)).map(([k,v])=>[k,sanitize(v)]));
 return value;
}
export function methodName(filename) {const stem=filename.replace(/\.jsonl$/,'');const at=stem.indexOf('eval-');if(at<0||!stem.slice(at+5))throw Error(`Result filename must contain eval- and a method suffix: ${filename}`);return stem.slice(at+5);}
export function normalize(record,filename) {
 const method=methodName(filename), answers=Object.entries(record.answers);
 return answers.map(([model,a])=>{
  const am=a.metrics??{}, shared=answers.length===1?record.metrics:Object.fromEntries(Object.entries(record.retrieval.metrics??{}));
  const metrics=sanitize({...shared,...am});
  const details=a.judge_details??(answers.length===1?record.judge_details:null);
  const status=details?.status??'missing';
  const rawScores=a.judge??(answers.length===1?record.judge:null);
  const scores=Object.fromEntries(scoreKeys.map(k=>[k,status==='completed'&&numeric(rawScores?.[k])!==null&&rawScores[k]>=0&&rawScores[k]<=1?rawScores[k]:null]));
  const configuration=record.configuration_hash??hash({index:record.provenance?.index_config_sha256,run:record.run_id});
  const cost=numeric(metrics.api_cost_usd), latency=numeric(am.answer_ready_time_seconds)??numeric(am.total_time_seconds)??(answers.length===1?numeric(record.metrics.total_time_seconds):null);
  const input=numeric(metrics.input_tokens),output=numeric(metrics.output_tokens);
  const id=hash([method,record.question_id,model,configuration]).slice(0,24);
  const retrieval=a.retrieval??record.retrieval;
  const retrievalProfile=sanitize({retriever:typeof record.provenance?.retriever==='string'?record.provenance.retriever:null,
   modes:[...new Set((retrieval.queries??[]).map(q=>q.mode).filter(v=>typeof v==='string'))].sort(),
   signals:[...new Set((retrieval.chunks??[]).flatMap(c=>Object.keys(c.scores??{})))].sort()});
  return {id,questionId:record.question_id,question:record.question,category:record.question_category,asOf:record.as_of,method,sourceMethod:record.method,model,configuration,runId:record.run_id??null,corpusHash:record.provenance?.corpus_sha256??null,questionHash:record.provenance?.questions_sha256??null,reasoning:a.thinking_level??a.reasoning??null,maxOutput:a.max_output_tokens??null,judgeStatus:status,judgeModel:details?.model_requested??null,explanations:sanitize(details?.explanations??{}),scores,generated:typeof a.final_answer==='string'&&a.final_answer.trim().length>0&&['ok','completed','success'].includes(a.status??record.status),retrieved:(record.retrieval.chunks?.length??0)>0,cost,latency,tokens:input!==null&&output!==null?input+output:null,metrics,retrievalProfile,preview:{gold:record.gold_answer.slice(0,240),answer:(a.final_answer??'').slice(0,300)},updatedAt:record.updated_at??record.created_at??null,detailId:hash(record.question_id).slice(0,20)};
 });
}
export function detail(record,filename) {
 return sanitize({method:methodName(filename),sourceMethod:record.method,runId:record.run_id,questionId:record.question_id,question:record.question,category:record.question_category,asOf:record.as_of,goldAnswer:record.gold_answer,goldEvidence:record.gold_evidence,goldDetails:record.gold_details,retrieval:record.retrieval,context:record.context,errors:record.errors,metrics:record.metrics,configuration:record.configuration_hash,provenance:record.provenance,judgeProvenance:record.judge_provenance,createdAt:record.created_at,updatedAt:record.updated_at,answers:Object.fromEntries(Object.entries(record.answers).map(([model,a])=>[model,{final_answer:a.final_answer,status:a.status,generation_id:a.generation_id,run_id:a.run_id,finish_reason:a.finish_reason,native_finish_reason:a.native_finish_reason,metadata_status:a.metadata_status,attempt_history:a.attempt_history,citations:a.citations,judge:a.judge,judge_details:a.judge_details,metrics:a.metrics,retrieval:a.retrieval,context:a.context,errors:a.errors,model_returned:a.model_returned,thinking_level:a.thinking_level,max_output_tokens:a.max_output_tokens,provider:a.provider,usage:a.usage}]))});
}
