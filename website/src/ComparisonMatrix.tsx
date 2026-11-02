import {useMemo,useState} from 'react';
import {groupRows} from './data.mjs';
import {color,metricMean,money,num,percent,seconds,shortModel} from './format';
import type {Evaluation,Group,Hover} from './types';

type Metric = {
  key:string;
  label:string;
  value:(group:Group)=>number|null;
  format:(value:number|null)=>string;
  count:(group:Group)=>number;
};
const measured=(group:Group,key:string)=>group.rows.filter(row=>typeof row.metrics[key]==='number'&&Number.isFinite(row.metrics[key])).length;
const quality=(key:string,label:string):Metric=>({key,label,value:g=>g.scores[key],format:percent,count:g=>g.rows.filter(row=>row.scores[key]!==null).length});
const metrics:Metric[]=[
  quality('answer_correctness','Answer correctness'),
  quality('faithfulness','Faithfulness'),
  quality('context_relevance','Context relevance'),
  quality('answer_relevance','Answer relevance'),
  {key:'cost',label:'Avg. API cost',value:g=>g.cost,format:money,count:g=>g.costN},
  {key:'latency',label:'Avg. answer latency',value:g=>g.latency,format:seconds,count:g=>g.latencyN},
  {key:'tokens',label:'Avg. total tokens',value:g=>g.tokens,format:v=>num(v,0),count:g=>g.rows.filter(row=>row.tokens!==null).length},
];
const extraMetrics:Metric[]=[
  {key:'medianLatency',label:'Median answer latency',value:g=>g.medianLatency,format:seconds,count:g=>g.latencyN},
  ...[
    ['input_tokens','Avg. input tokens'],
    ['output_tokens','Avg. output tokens'],
    ['reasoning_tokens','Avg. reasoning tokens'],
    ['tool_calls','Avg. tool calls'],
    ['llm_api_calls','Avg. LLM API calls'],
    ['db_queries','Avg. DB queries'],
    ['retrieval_time_ms','Avg. retrieval time (ms)'],
    ['llm_generation_time_ms','Avg. generation time (ms)'],
    ['retrieval_peak_rss_mb','Avg. peak retrieval memory (MiB)'],
  ].map(([key,label]):Metric=>({key,label,value:g=>metricMean(g.rows,key),format:v=>num(v),count:g=>measured(g,key)})),
];

/** Strategies are columns and metrics are rows. Model/settings/configuration boundaries stay explicit. */
export default function ComparisonMatrix({rows,methods,hover,setHover,onOpen}:{
  rows:Evaluation[];methods:string[];hover:Hover;
  setHover:(value:Hover)=>void;onOpen:(group:Group)=>void;
}) {
  const [showMore,setShowMore]=useState(false);
  const settings=useMemo(()=>{
    const grouped=new Map<string,{key:string;label:string;groups:Group[]}>();
    for(const group of groupRows(rows)) {
      const first=group.rows[0];
      const key=JSON.stringify([group.model,first.reasoning,first.maxOutput,first.corpusHash,first.questionHash]);
      const effort=typeof first.reasoning==='string'?first.reasoning.toLowerCase():'unspecified';
      if(!grouped.has(key))grouped.set(key,{key,label:`${shortModel(group.model)} @ ${effort}`,groups:[]});
      grouped.get(key)!.groups.push(group);
    }
    return [...grouped.values()].sort((a,b)=>a.label.localeCompare(b.label));
  },[rows]);
  const visibleMetrics=showMore?[...metrics,...extraMetrics]:metrics;
  return <section className="results-summary" aria-labelledby="results-title">
    <div className="results-heading"><h2 id="results-title">Results at a glance</h2><button aria-expanded={showMore} onClick={()=>setShowMore(!showMore)}>{showMore?'Fewer metrics':'More metrics'}</button></div>
    {settings.map(setting=><div className="matrix-setting" key={setting.key}>
      <h3 className="matrix-setting-title" title={setting.groups[0].model}>{setting.label}
        {settings.filter(s=>s.label===setting.label).length>1&&<small>Corpus {setting.groups[0].rows[0].corpusHash?.slice(0,8)??'N/A'} · output limit {setting.groups[0].rows[0].maxOutput??'N/A'}</small>}
      </h3>
      <div className="matrix-scroll">
        <table className="comparison-matrix">
          <caption className="sr-only">Benchmark metrics by retrieval strategy for {setting.label}.</caption>
          <thead><tr><th scope="col">Metric</th>{methods.map(method=><th scope="col" key={method}>
            <span className="method-name"><i style={{background:color(method)}}/>{method}</span>
          </th>)}</tr></thead>
          <tbody>
            {visibleMetrics.map(metric=><tr key={metric.key}>
              <th scope="row">{metric.label}</th>
              {methods.map(method=>{
                const groups=setting.groups.filter(g=>g.method===method);
                return <td key={method} className={hover?.method&&hover.method!==method?'faded':''}>
                  {groups.length?groups.map(g=><button key={g.key} className="matrix-result"
                    aria-label={`Inspect ${metric.label.toLowerCase()} for ${method}, ${setting.label}, configuration ${g.configuration.slice(0,8)}`}
                    title={`${g.method} · ${g.model}\n${metric.label}: ${metric.format(metric.value(g))}\nMeasured n=${metric.count(g)} of ${g.n} evaluations\nConfiguration ${g.configuration}`}
                    onMouseEnter={()=>setHover({method})} onMouseLeave={()=>setHover(null)} onClick={()=>onOpen(g)}>
                    <span>{metric.format(metric.value(g))}</span>
                    {groups.length>1&&<small>Config {g.configuration.slice(0,8)}</small>}
                  </button>):<span className="unavailable">N/A</span>}
                </td>;
              })}
            </tr>)}
            <tr><th scope="row">Judged answers</th>{methods.map(method=>{
              const groups=setting.groups.filter(g=>g.method===method);
              return <td key={method} className={hover?.method&&hover.method!==method?'faded':''}>{groups.length?groups.map(g=><button key={g.key} className="matrix-result" aria-label={`Inspect judged answers for ${method}, ${setting.label}, configuration ${g.configuration.slice(0,8)}`} title={`Completed judgments / recorded evaluations\n${g.model}\nConfiguration ${g.configuration}`} onMouseEnter={()=>setHover({method})} onMouseLeave={()=>setHover(null)} onClick={()=>onOpen(g)}><span>{g.judged} / {g.n}</span>{groups.length>1&&<small>Config {g.configuration.slice(0,8)}</small>}</button>):<span className="unavailable">N/A</span>}</td>;
            })}</tr>
          </tbody>
        </table>
      </div>
    </div>)}
    {!settings.length&&<p className="empty">No results for this selection.</p>}
    <p className="table-note">Averages use the selected answers. Hover for sample counts; select a value to inspect its questions.</p>
  </section>;
}
