import {Fragment,useEffect,useMemo,useRef,useState} from 'react';
import {X,ArrowUpRight,ExternalLink,FileText,GitCompareArrows,FileCode2,Clock,DollarSign,ChevronLeft,ChevronRight,Sparkles,Layers} from 'lucide-react';
import Markdown from 'react-markdown';import remarkGfm from 'remark-gfm';
import Table from './Table';import {Panel} from './Charts';import {labels,numeric,readable,scoreKeys} from './data.mjs';import {color,money,num,percent,seconds,shortModel} from './format';import type {Evaluation,Manifest,Detail,Hover} from './types';
export const Status=({status}:{status:string})=><span className={`status status-${status}`}><i/>{status==='missing'?'Not Evaluated':readable(status)}</span>;

export function QuestionMatrix({rows,manifest,onInspect}:{rows:Evaluation[];manifest?:Manifest|null;onInspect:(r:Evaluation)=>void}){
  const [pageIndex,setPageIndex]=useState(0);
  const pageSize=10;

  const methods=useMemo(()=>{
    if(manifest?.methods?.length){
      return manifest.methods.filter(m=>rows.some(r=>r.method===m));
    }
    return [...new Set(rows.map(r=>r.method))];
  },[rows,manifest]);

  const methodFileMap=useMemo(()=>{
    const map=new Map<string,string>();
    if(manifest?.sources){
      for(const s of manifest.sources){
        map.set(s.method,s.file);
      }
    }
    return map;
  },[manifest]);

  const getMethodFile=(m:string)=>methodFileMap.get(m)??`q-a-eval-${m}.jsonl`;

  const questions=useMemo(()=>{
    const map=new Map<string,{id:string;question:string;category:string;asOf:string;evaluations:Record<string,Evaluation>}>();
    for(const r of rows){
      if(!map.has(r.questionId)){
        map.set(r.questionId,{id:r.questionId,question:r.question,category:r.category,asOf:r.asOf,evaluations:{}});
      }
      map.get(r.questionId)!.evaluations[r.method]=r;
    }
    return [...map.values()].sort((a,b)=>a.id.localeCompare(b.id));
  },[rows]);

  const totalPages=Math.max(1,Math.ceil(questions.length/pageSize));
  const currentQuestions=useMemo(()=>questions.slice(pageIndex*pageSize,(pageIndex+1)*pageSize),[questions,pageIndex,pageSize]);

  const getAdvantage=(evals:Record<string,Evaluation>)=>{
    if(methods.length<2)return null;
    const m1=evals[methods[0]],m2=evals[methods[1]];
    if(!m1||!m2)return null;
    let speedText='';
    const lat1=m1.latency,lat2=m2.latency;
    if(lat1!==null&&lat2!==null&&lat1>0&&lat2>0){
      if(lat1<lat2){
        const ratio=(lat2/lat1).toFixed(1);
        speedText=`${methods[0]} ${ratio}x faster`;
      }else if(lat2<lat1){
        const ratio=(lat1/lat2).toFixed(1);
        speedText=`${methods[1]} ${ratio}x faster`;
      }else{
        speedText='Tied latency';
      }
    }
    const cost1=m1.cost,cost2=m2.cost;
    let costText='';
    if(cost1!==null&&cost2!==null&&cost1>0&&cost2>0){
      if(cost1<cost2){
        costText=`${methods[0]} cheaper`;
      }else if(cost2<cost1){
        costText=`${methods[1]} cheaper`;
      }
    }
    const c1=m1.scores.answer_correctness,c2=m2.scores.answer_correctness;
    let scoreText='';
    if(c1!==null&&c2!==null){
      if(c1>c2){
        scoreText=`${methods[0]} +${Math.round((c1-c2)*100)}%`;
      }else if(c2>c1){
        scoreText=`${methods[1]} +${Math.round((c2-c1)*100)}%`;
      }else{
        scoreText=`Tied (${percent(c1)})`;
      }
    }
    return {speedText,costText,scoreText};
  };

  if(!questions.length){
    return <div className="empty">No questions match these filters.</div>;
  }

  return <div className="question-matrix-container" id="per-question-matrix">
    <div className="matrix-toolbar">
      <div className="matrix-meta">
        <strong>{questions.length} Questions</strong>
        <span className="subtle">Comparing {methods.length} retrieval strategies side-by-side</span>
      </div>
      <div className="pagination">
        <span>Page {pageIndex+1} of {totalPages}</span>
        <div className="inline">
          <button aria-label="Previous question page" disabled={pageIndex===0} onClick={()=>setPageIndex(p=>Math.max(0,p-1))}>
            <ChevronLeft size={15}/>
          </button>
          <button aria-label="Next question page" disabled={pageIndex>=totalPages-1} onClick={()=>setPageIndex(p=>Math.min(totalPages-1,p+1))}>
            <ChevronRight size={15}/>
          </button>
        </div>
      </div>
    </div>
    <div className="matrix-scroll">
      <table className="question-matrix-table">
        <thead>
          <tr className="matrix-header-super">
            <th className="th-q" rowSpan={2}>Reference Question</th>
            {methods.map(m=><th key={m} colSpan={2} className="th-strategy-group">
              <div className="strategy-header-box">
                <span className="file-pill mono" title={`Source file: ${getMethodFile(m)}`}>
                  <FileCode2 size={12}/> {getMethodFile(m)}
                </span>
                <div className="strategy-title">
                  <i style={{background:color(m)}}/>
                  <strong>{m}</strong>
                </div>
              </div>
            </th>)}
            {methods.length>=2&&<th className="th-adv" rowSpan={2}>Comparison & Advantage</th>}
            <th className="th-act" rowSpan={2}>Action</th>
          </tr>
          <tr className="matrix-header-sub">
            {methods.map(m=><Fragment key={m}>
              <th className="th-col-quality">Quality (Correctness & Faithfulness)</th>
              <th className="th-col-metrics">Cost & Time Taken (Latency)</th>
            </Fragment>)}
          </tr>
        </thead>
        <tbody>
          {currentQuestions.map(q=>{
            const evals=q.evaluations;
            const advantage=getAdvantage(evals);
            const firstEval=Object.values(evals)[0];
            return <tr key={q.id} className="matrix-row" aria-label={`Side-by-side comparison for ${q.id}`}>
              <td className="td-question">
                <div className="question-info">
                  <div className="inline">
                    <span className="mono q-badge">{q.id}</span>
                    <span className="category-pill">{readable(q.category)}</span>
                  </div>
                  <p className="q-text" title={q.question}>{q.question}</p>
                  {q.asOf&&<small className="subtle">As of {q.asOf}</small>}
                </div>
              </td>
              {methods.map(m=>{
                const e=evals[m];
                if(!e){
                  return <Fragment key={m}>
                    <td className="td-quality td-empty"><span className="unavailable">N/A</span></td>
                    <td className="td-metrics td-empty"><span className="unavailable">N/A</span></td>
                  </Fragment>;
                }
                const corr=e.scores.answer_correctness,faith=e.scores.faithfulness;
                const isPending=e.judgeStatus==='pending',isMissing=e.judgeStatus==='missing',isError=e.judgeStatus==='error';
                return <Fragment key={m}>
                  <td className="td-quality">
                    <div className="quality-cell-content">
                      {corr!==null?<span className={`score-badge ${corr>=0.8?'score-high':corr>=0.5?'score-mid':'score-low'}`}>{percent(corr)} Correct</span>:isPending?<span className="score-badge score-pending">Pending</span>:isError?<span className="score-badge score-error">Error</span>:<span className="score-badge score-missing">Not Evaluated</span>}
                      {faith!==null&&<span className="sub-stat">Faith: <b>{percent(faith)}</b></span>}
                    </div>
                  </td>
                  <td className="td-metrics">
                    <div className="metrics-cell-content">
                      <div className="metric-pill latency-pill" title={`Latency: ${seconds(e.latency)}`}>
                        <Clock size={12}/>
                        <span>{seconds(e.latency)}</span>
                      </div>
                      <div className="metric-pill cost-pill" title={`Serving cost: ${money(e.cost)}`}>
                        <DollarSign size={12}/>
                        <span>{money(e.cost)}</span>
                      </div>
                    </div>
                  </td>
                </Fragment>;
              })}
              {methods.length>=2&&<td className="td-advantage">
                {advantage?<div className="advantage-box">
                  {advantage.speedText&&<span className="adv-pill speed-adv">⚡ {advantage.speedText}</span>}
                  {advantage.scoreText&&<span className="adv-pill score-adv">🎯 {advantage.scoreText}</span>}
                  {advantage.costText&&<span className="adv-pill cost-adv">💰 {advantage.costText}</span>}
                </div>:<span className="unavailable">—</span>}
              </td>}
              <td className="td-action">
                {firstEval&&<button className="inspect-btn" onClick={()=>onInspect(firstEval)} aria-label={`Open question lab for ${q.id}`} title={`Inspect question ${q.id} answers and evidence`}>
                  Inspect <ArrowUpRight size={13}/>
                </button>}
              </td>
            </tr>;
          })}
        </tbody>
      </table>
    </div>
  </div>;
}

export function Explorer({rows,onInspect,judge=false,manifest}:{rows:Evaluation[];onInspect:(r:Evaluation)=>void;judge?:boolean;hover?:Hover;setHover?:(h:Hover)=>void;manifest?:Manifest|null}){
 const columns:any[]=[{accessorKey:'questionId',header:'Question ID',cell:({getValue}:any)=><span className="mono accent">{getValue()}</span>},{accessorKey:'category',header:'Category',cell:({getValue}:any)=><span className="category-label">{readable(getValue())}</span>},{accessorKey:'question',header:'Question',cell:({getValue}:any)=><span className="question-cell">{getValue()}</span>},{accessorKey:'method',header:'Strategy',cell:({getValue}:any)=><span className="method-name"><i style={{background:color(getValue())}}/>{getValue()}</span>},{accessorKey:'model',header:'Model',cell:({getValue}:any)=><span title={getValue()}>{shortModel(getValue())}</span>},{accessorKey:'configuration',header:'Config',cell:({getValue}:any)=><span className="mono">{getValue().slice(0,8)}</span>},{id:'correctness',accessorFn:(r:Evaluation)=>r.scores.answer_correctness,header:'Correctness',cell:({getValue}:any)=><span className={getValue()===null?'unavailable':'score'}>{percent(getValue())}</span>},...(judge?scoreKeys.filter(k=>k!=='answer_correctness').map(k=>({id:k,accessorFn:(r:Evaluation)=>r.scores[k],header:labels[k],cell:({getValue}:any)=>percent(getValue())})):[]),{accessorKey:'cost',header:'API cost',cell:({getValue}:any)=>money(getValue())},{accessorKey:'latency',header:'Latency',cell:({getValue}:any)=>seconds(getValue())},{accessorKey:'judgeStatus',header:'Judge status',cell:({getValue}:any)=><Status status={getValue()}/>}];
 if(judge)columns.push({id:'gold',accessorFn:(r:Evaluation)=>r.preview.gold,header:'Gold answer',cell:({getValue}:any)=><span className="clamp" title={getValue()}>{getValue()}</span>},{id:'answer',accessorFn:(r:Evaluation)=>r.preview.answer,header:'Generated answer',cell:({getValue}:any)=><span className="clamp" title={getValue()}>{getValue()}</span>},{id:'explanation',accessorFn:(r:Evaluation)=>Object.entries(r.explanations).map(([k,v])=>`${labels[k]??k}: ${typeof v==='string'?v:JSON.stringify(v)}`).join('\n')||'Explanation unavailable',header:'Judge explanation',cell:({getValue}:any)=><span className="clamp" title={getValue()}>{getValue()}</span>});

 if(judge){
   return <Panel title="Judge results" sub="Select a row to inspect the answer, gold reference, citations and judge evaluations."><Table data={rows} columns={columns} filename="judge-results" initialVisibility={{category:false,model:false,configuration:false,gold:false,answer:false,explanation:false}} onRow={onInspect}/></Panel>;
 }

 return <div className="explorer-view-wrapper">
   <div className="explorer-quick-nav">
     <a href="#per-question-matrix" className="quick-nav-pill"><Sparkles size={14}/> Side-by-Side Question Matrix (by JSONL files)</a>
     <a href="#all-evaluations-table" className="quick-nav-pill"><Layers size={14}/> All Evaluation Records (Sorting & CSV Export)</a>
   </div>

   <Panel title="Per-Question Strategy Comparison" sub="Side-by-side comparison across JSONL files. Quality (correctness & faithfulness) and Cost & Time Taken (latency) organized by strategy columns.">
     <QuestionMatrix rows={rows} manifest={manifest} onInspect={onInspect}/>
   </Panel>

   <div id="all-evaluations-table">
     <Panel title="All Evaluation Records" sub="Multi-column sortable table with column visibility toggles and CSV export. Select any row to inspect execution and evidence.">
       <Table data={rows} columns={columns} filename="question-evaluations" initialVisibility={{category:false,model:false,configuration:false,gold:false,answer:false,explanation:false}} onRow={onInspect}/>
     </Panel>
   </div>
 </div>;
}

const md=(s:string)=><Markdown remarkPlugins={[remarkGfm]}>{s}</Markdown>;
export function QuestionDetail({row,manifest,onClose}:{row:Evaluation;manifest:Manifest;onClose:()=>void}){
 const [data,setData]=useState<Detail[]|null>(null),[error,setError]=useState(''),[compare,setCompare]=useState(false),[tab,setTab]=useState('answers'),[citation,setCitation]=useState<string|null>(null);
 const dialog=useRef<HTMLDivElement>(null),close=useRef<HTMLButtonElement>(null);
 useEffect(()=>{const controller=new AbortController();fetch(`${import.meta.env.BASE_URL}data/${manifest.details}${row.detailId}.json`,{signal:controller.signal}).then(r=>{if(!r.ok)throw Error(`Question details returned HTTP ${r.status}`);return r.json();}).then(setData).catch(e=>{if(e.name!=='AbortError')setError(String(e));});return()=>controller.abort();},[manifest.details,row.detailId]);
 useEffect(()=>{const previous=document.activeElement as HTMLElement;const overflow=document.body.style.overflow;document.body.style.overflow='hidden';close.current?.focus();const key=(e:KeyboardEvent)=>{if(e.key==='Escape')onClose();if(e.key==='Tab'&&dialog.current){const nodes=[...dialog.current.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], select, input, [tabindex="0"]')];const first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}};document.addEventListener('keydown',key);return()=>{document.body.style.overflow=overflow;document.removeEventListener('keydown',key);previous?.focus();};},[onClose]);
 const selected=data?.find(d=>d.method===row.method&&d.configuration===row.configuration)??data?.[0];const views=(compare?data??[]:selected?[selected]:[]).flatMap(d=>Object.entries(d.answers).filter(([model])=>compare||model===row.model).map(([model,a])=>({record:d,model,answer:a as Detail})));
 const selectCitation=(key:string)=>{setCitation(key);setTab('evidence');setTimeout(()=>document.getElementById(`chunk-${key}`)?.scrollIntoView({block:'center',behavior:'smooth'}),80);};
 return <div className="modal-backdrop" onClick={e=>e.target===e.currentTarget&&onClose()}><div ref={dialog} className="detail-dialog" role="dialog" aria-modal="true" aria-labelledby="detail-title"><div className="detail-top"><span className="eyebrow">QUESTION LAB · {row.questionId}</span><button ref={close} onClick={onClose} aria-label="Close question details"><X size={20}/></button></div><h2 id="detail-title">{row.question}</h2><div className="inline detail-meta"><span className="badge">{readable(row.category)}</span><span>As of {row.asOf??'N/A'}</span><span>{row.questionId}</span></div>{error&&<p role="alert">{error}</p>}{!data&&!error&&<div className="empty">Loading answers and evidence…</div>}{selected&&<><div className="gold-reference"><span className="eyebrow">GOLD / REFERENCE ANSWER</span><div className="markdown">{md(selected.goldAnswer)}</div></div><div className="detail-tabs"><div className="inline">{['answers','evidence','execution','provenance'].map(t=><button key={t} className={tab===t?'active':''} onClick={()=>setTab(t)}>{readable(t)}</button>)}</div><button className={compare?'primary':'small'} onClick={()=>setCompare(!compare)}><GitCompareArrows size={14}/>{compare?'Showing all methods · focus selected':'Compare Methods'}</button></div>{compare&&<p className="footnote">All exported answers for {row.questionId}, including methods outside the current filters. Match model and configuration before drawing conclusions.</p>}
 {tab==='answers'&&<div className="answer-grid">{views.map(({record:d,model,answer:a},i)=><article className="answer-card" key={`${d.method}:${d.configuration}:${model}`}><div className="answer-heading"><span className="method-name"><i style={{background:color(d.method)}}/>{d.method}</span><Status status={a.judge_details?.status??'missing'}/></div><p className="subtle">{model} · config <span className="mono">{(d.configuration??'N/A').slice(0,8)}</span></p><div className="mini-metrics"><span>Serving cost <b>{money(a.metrics?.api_cost_usd)}</b></span><span>Answer ready <b>{seconds(a.metrics?.answer_ready_time_seconds??a.metrics?.total_time_seconds)}</b></span><span>Total tokens <b>{num(numeric(a.metrics?.input_tokens)!==null&&numeric(a.metrics?.output_tokens)!==null?a.metrics.input_tokens+a.metrics.output_tokens:null,0)}</b></span></div><div className="markdown generated-answer"><Markdown remarkPlugins={[remarkGfm]} components={{a:({href,children})=>href?.startsWith('#cite-')?<button className="citation" onClick={()=>selectCitation(`${i}-${href.slice(6)}`)}>{children}</button>:<a href={href} target="_blank" rel="noreferrer">{children}</a>}}>{(a.final_answer||'No generated answer available.').replace(/\[(\d+)\](?!\()/g,'[$1](#cite-$1)')}</Markdown></div><div className="citation-list">{(a.citations??[]).map((c:any,j:number)=><button className="citation" key={j} onClick={()=>selectCitation(`${i}-${c.marker}`)}>[{c.marker}] <FileText size={11}/></button>)}</div><div className="judge-score-grid">{scoreKeys.map(k=><details key={k}><summary><span>{labels[k]}</span><b>{percent(a.judge?.[k])}</b></summary><p>{typeof a.judge_details?.explanations?.[k]==='string'?a.judge_details.explanations[k]:a.judge_details?.explanations?.[k]?JSON.stringify(a.judge_details.explanations[k]):'No completed assessment or explanation is available.'}</p></details>)}</div><p className="footnote">Judge: {a.judge_details?.model_requested??'Identity unavailable'} · {a.judge_details?.evaluated_at??'Not Evaluated'}</p></article>)}</div>}
 {tab==='evidence'&&<div className="evidence-view"><h3>Retrieved evidence & citations</h3><p className="notice">The compact exports retain ranks, scores, document IDs, source offsets and citation maps. Where a matching original local snapshot is available, retrieved text is included below. Other passages are labeled unavailable. Gold passages are separate reference evidence, not the context sent to the model.</p>{views.map(({record:d,model,answer:a},i)=>{const retrieval=a.retrieval??d.retrieval;const context=a.context??d.context?.by_model?.[model]??d.context;const map=context?.citation_map??{};return <div key={i}><h4>{d.method} · {shortModel(model)}</h4><details><summary>Search queries ({retrieval?.queries?.length??0})</summary><pre>{JSON.stringify(retrieval?.queries??[],null,2)}</pre></details>{(retrieval?.chunks??[]).map((c:any,j:number)=>{const markers=Object.entries(map).filter(([,id])=>id===c.chunk_id).map(([m])=>m);const key=markers[0]??String(c.rank??j);return <details id={`chunk-${i}-${key}`} open={citation===`${i}-${key}`||markers.some(m=>citation===`${i}-${m}`)} className="chunk" key={`${c.chunk_id}-${j}`}><summary><span className="mono">#{c.rank??j+1}</span><span>{c.metadata?.title??c.document_id??c.chunk_id}</span>{markers.length>0&&<span className="badge">Citations {markers.map(m=>`[${m}]`).join(' ')}</span>}</summary><dl className="source-grid"><dt>Chunk ID</dt><dd className="mono">{c.chunk_id}</dd><dt>Document ID</dt><dd>{c.document_id??'N/A'}</dd><dt>Rank / scores</dt><dd>{c.rank??'N/A'} · {JSON.stringify(c.scores??{})}</dd><dt>Source metadata</dt><dd><pre>{JSON.stringify(c.source??{},null,2)}</pre></dd></dl>{c.text?<><p className="footnote">Retrieved passage · verified against source IDs, hashes and offsets{c.passage_origin?` · snapshot ${c.passage_origin.snapshot_sha256.slice(0,12)}`:''}</p><div className="markdown">{md(c.text)}</div></>:<p className="footnote">Full retrieved passage unavailable in the presentation export.</p>}</details>})}<details><summary>Exact supplied chunk IDs & citation map</summary><pre>{JSON.stringify(context,null,2)}</pre></details></div>;})}<h3>Gold evidence passages</h3>{(selected.goldEvidence??[]).map((e:any,i:number)=><details className="gold-evidence" key={i} open={i===0}><summary><FileText size={15}/> {e.document_id} · {e.form??'Form N/A'} · {e.filed_date??'Date N/A'}</summary><p className="footnote">{e.section} · original characters {e.start_char}–{e.end_char} · hash {e.parsed_md5??'N/A'}</p><div className="markdown">{md(e.passage)}</div></details>)}<details><summary>Gold calculations & answer requirements</summary><pre>{JSON.stringify(selected.goldDetails,null,2)}</pre></details></div>}
 {tab==='execution'&&views.map(({record:d,model,answer:a},i)=><section key={i}><h3>{d.method} · {model}</h3><p>Generation status: {a.status??'N/A'}</p><div className="execution-grid">{Object.entries(a.metrics??{}).map(([k,v])=><div key={k}><span>{readable(k)}</span><b>{v===null?'N/A':typeof v==='object'?JSON.stringify(v):typeof v==='number'?num(v,5):String(v)}</b></div>)}</div><details><summary>Record metrics (shared; do not add to answer metrics)</summary><pre>{JSON.stringify(d.metrics,null,2)}</pre></details><h4>Errors & retry history</h4><pre>{JSON.stringify({answer:a.errors??[],attempt_history:a.attempt_history??[],record:d.errors??[],judge:a.judge_details?.error??null},null,2)}</pre><details><summary>Judge status, errors & provenance</summary><pre>{JSON.stringify(a.judge_details??null,null,2)}</pre></details><details><summary>Judge overhead (separate from serving)</summary><pre>{JSON.stringify(a.judge_details?.metrics??null,null,2)}</pre></details></section>)}
 {tab==='provenance'&&views.map(({record:d,model,answer:a},i)=><section key={i}><h3>{d.method} · {model}</h3><pre>{JSON.stringify({runId:d.runId,configuration:d.configuration,generation_id:a.generation_id,finish_reason:a.finish_reason,native_finish_reason:a.native_finish_reason,metadata_status:a.metadata_status,createdAt:d.createdAt,updatedAt:d.updatedAt,provenance:d.provenance,judgeProvenance:d.judgeProvenance,model_returned:a.model_returned,provider:a.provider,thinking_level:a.thinking_level,max_output_tokens:a.max_output_tokens},null,2)}</pre></section>)}</>}</div></div>;
}
