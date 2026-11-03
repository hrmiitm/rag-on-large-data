import {useId,useState} from 'react';
import {color} from './format';
import type {Evaluation,Hover} from './types';

// Descriptions follow recorded adapter identities, never guesses from filenames.
// Discovery remains data-driven; unfamiliar adapters get an explicit fallback.
export function methodDescription(rows:Evaluation[]) {
  const sources=[...new Set(rows.map(row=>row.sourceMethod))];
  const profiles:Record<string,{search:string;sent:string}>={
    bm25:{search:'BM25 keyword matching over SEC filing chunks.',sent:'The question and top retrieved SEC passages with citation markers.'},
    agentic:{search:'The LLM issues and refines BM25 searches over SEC filings.',sent:'The question and passages returned by successive read-only search tools.'},
    'semantic-search':{search:'Cosine similarity over SEC chunks embedded with text-embedding-3-small.',sent:'The question and top semantic matches with citation markers.'},
    hybrid:{search:'BM25 keyword scores and embedding cosine similarity, using native multiplicative fusion.',sent:'The question and top passages from the combined ranking, with citation markers.'},
  };
  if(!rows.length)return {search:'No evaluations for the current filters.',sent:'No supplied context in this selection.'};
  if(sources.length!==1)return {search:'Multiple recorded retrieval techniques in this selection.',sent:'Context stays separate for each model and configuration.'};
  return Object.hasOwn(profiles,sources[0])?profiles[sources[0]]:{search:'Retrieval technique is not documented for this recorded adapter.',sent:'Recorded answer context; inspect a question for details.'};
}

export default function MethodLegend({methods,rows,hover,setHover}:{methods:string[];rows:Evaluation[];hover:Hover;setHover:(value:Hover)=>void}) {
  const [active,setActive]=useState<string|null>(null),id=useId();
  const selected=active!==null&&methods.includes(active)?active:null;
  const info=methodDescription(rows.filter(row=>row.method===selected));
  const show=(method:string)=>{setActive(method);setHover({method});};
  const hide=()=>{setActive(null);setHover(null);};
  return <div className="chart-method-legend" role="group" aria-label="Chart methods">
    {methods.map(method=><button type="button" key={method} className={hover?.method&&hover.method!==method?'faded':''}
      aria-label={method} aria-describedby={selected===method?id:undefined}
      onMouseEnter={()=>show(method)} onMouseLeave={event=>{if(document.activeElement!==event.currentTarget)hide();}}
      onFocus={()=>show(method)} onBlur={hide} onClick={()=>show(method)} onKeyDown={event=>{if(event.key==='Escape')hide();}}>
      <i aria-hidden="true" style={{background:color(method)}}/>{method}
    </button>)}
    {selected!==null&&<div className="chart-method-tip" id={id} role="tooltip">
      <strong>{selected}</strong><p><b>Search:</b> {info.search}</p><p><b>LLM receives:</b> {info.sent}</p>
    </div>}
  </div>;
}
