import {Fragment} from 'react';
import {methodDescription} from './MethodLegend';

// Highlight known terms as React text, never as untrusted HTML/Markdown.
const important=/(BM25|Elasticsearch|LLM|RRF|HyDE|Self-RAG|cross-encoder|cosine similarity|exact vector|approximate vector|rank fusion|multiplicative fusion|saved vector|keyword|semantic|neighbouring passages|company\/form filters|filing-date cutoff|no new embeddings|CPU|serving (?:API )?(?:cost|spend)|judging|hypothetical passage|evidence tokens|original question)/gi;
export function Highlight({text}:{text:string}) {
 return <>{text.split(important).map((part,i)=>i%2?<strong key={i}>{part}</strong>:<Fragment key={i}>{part}</Fragment>)}</>;
}
const sentences=(text:string)=>text.split(/(?<=[.!?])\s+(?=[A-Z])/).filter(Boolean);
function Bullets({text}:{text:string}){return <ul>{sentences(text).map((item,i)=><li key={i}><Highlight text={item}/></li>)}</ul>;}
export default function TechniqueDetails({detail}:{detail:ReturnType<typeof methodDescription>}) {
 return <div className="chart-technique">
  <h4>How retrieval works</h4>
  <Bullets text={detail.search}/>
  {!!detail.steps?.length&&<ul>{detail.steps.map((step,i)=><li key={i}><Highlight text={step}/></li>)}</ul>}
  <h4>What the answering LLM receives</h4><Bullets text={detail.sent}/>
  {detail.comparison&&<><h4>Compared with other methods</h4><Bullets text={detail.comparison}/></>}
  {detail.performance&&<><h4>Speed, quality and cost</h4><Bullets text={detail.performance}/></>}
  {!!detail.observations?.length&&<details><summary>Measured comparisons for current filters</summary><ul>{detail.observations.map((text,i)=><li key={i}><Highlight text={text}/></li>)}</ul><small>Correctness is a partial-credit judge score. Model/settings and common questions match; hardware contention and run timing were not controlled.</small></details>}
 </div>;
}
