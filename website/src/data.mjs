export const scoreKeys = ['answer_correctness','context_relevance','faithfulness','answer_relevance'];
export const labels = {answer_correctness:'Answer correctness',context_relevance:'Context relevance',faithfulness:'Faithfulness',answer_relevance:'Answer relevance'};
export const readable = s => String(s ?? '').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
export const numeric = v => typeof v === 'number' && Number.isFinite(v) ? v : null;
export const mean = xs => {const v=xs.filter(x=>numeric(x)!==null);return v.length ? v.reduce((a,b)=>a+b,0)/v.length:null;};
export const median = xs => {const v=xs.filter(x=>numeric(x)!==null).sort((a,b)=>a-b);return v.length ? (v[Math.floor((v.length-1)/2)]+v[Math.floor(v.length/2)])/2:null;};
export const initialFilters = () => ({categories:[],methods:[],models:[],configs:[],status:[],search:'',correctnessMin:'',correctnessMax:'',costMin:'',costMax:'',latencyMin:'',latencyMax:''});
export function filterRows(rows,f) {
 return rows.filter(r => (!f.categories.length||f.categories.includes(r.category)) && (!f.methods.length||f.methods.includes(r.method)) && (!f.models.length||f.models.includes(r.model)) && (!f.configs?.length||f.configs.includes(r.configuration)) && (!f.status.length||f.status.includes(r.judgeStatus)) && (!f.search||`${r.questionId} ${r.question} ${r.method} ${r.model}`.toLowerCase().includes(f.search.toLowerCase())) && [['correctness',r.scores.answer_correctness===null?null:r.scores.answer_correctness*100],['cost',r.cost],['latency',r.latency]].every(([k,v])=>(f[k+'Min']===''||(v!==null&&v>=Number(f[k+'Min'])))&&(f[k+'Max']===''||(v!==null&&v<=Number(f[k+'Max'])))));
}
export function groupRows(rows) {
 const groups=new Map();
 for(const r of rows){const key=JSON.stringify([r.method,r.model,r.configuration]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(r);}
 return [...groups.entries()].map(([key,rs])=>({key,method:rs[0].method,model:rs[0].model,configuration:rs[0].configuration,rows:rs,n:rs.length,judged:rs.filter(r=>r.judgeStatus==='completed').length,generated:rs.filter(r=>r.generated).length,retrieved:rs.filter(r=>r.retrieved).length,scores:Object.fromEntries(scoreKeys.map(k=>[k,mean(rs.map(r=>r.scores[k]))])),cost:mean(rs.map(r=>r.cost)),costN:rs.filter(r=>r.cost!==null).length,latency:mean(rs.map(r=>r.latency)),medianLatency:median(rs.map(r=>r.latency)),latencyN:rs.filter(r=>r.latency!==null).length,tokens:mean(rs.map(r=>r.tokens)),input:mean(rs.map(r=>numeric(r.metrics.input_tokens))),output:mean(rs.map(r=>numeric(r.metrics.output_tokens))),tools:mean(rs.map(r=>numeric(r.metrics.tool_calls))),db:mean(rs.map(r=>numeric(r.metrics.db_queries)))}));
}
export function matchedComparison(groups) {
 if(groups.length<2)return {n:0,groups:[],reason:'At least two method / model / configuration series are needed for a matched comparison.'};
 if(new Set(groups.map(g=>g.method)).size<2)return {n:0,groups:[],reason:'Select at least two different retrieval methods.'};
 const key=r=>JSON.stringify([r.questionId,r.model,r.asOf,r.corpusHash,r.questionHash,r.reasoning,r.maxOutput]);
 const sets=groups.map(g=>new Map(g.rows.filter(r=>r.judgeStatus==='completed'&&r.corpusHash&&r.questionHash).map(r=>[key(r),r])));
 const common=[...sets[0].keys()].filter(k=>sets.every(s=>s.has(k)));
 if(!common.length)return {n:0,groups:[],reason:'No jointly judged questions with the same model, corpus hash, question-set hash, cutoff and generation settings. No winner can be inferred.'};
 return {n:common.length,groups:sets.map(s=>groupRows(common.map(k=>s.get(k)))[0]),reason:null};
}
export function parseFilters(search) {
 const p=new URLSearchParams(search), f=initialFilters();
 for(const k of Object.keys(f)){if(Array.isArray(f[k]))f[k]=p.getAll(k);else f[k]=p.get(k)||'';}
 return f;
}
export function filtersQuery(f) {const p=new URLSearchParams();for(const [k,v]of Object.entries(f)){if(Array.isArray(v))v.forEach(x=>p.append(k,x));else if(v!=='')p.set(k,String(v));}return p;}
export function csv(rows,columns) {const esc=v=>'"'+String(v??'N/A').replaceAll('"','""').replace(/^[=+@\-\t\r]/,"'$&")+'"';return [columns.map(c=>esc(c.label)).join(','),...rows.map(r=>columns.map(c=>esc(c.value(r))).join(','))].join('\r\n');}
