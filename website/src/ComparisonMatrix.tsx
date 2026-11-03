import {useMemo,useState} from 'react';
import {ArrowDownUp,ArrowLeftRight,ArrowUp,ArrowDown,ArrowLeft,ArrowRight} from 'lucide-react';
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
  const [rowOrder,setRowOrder]=useState('default');
  const [columnMetric,setColumnMetric]=useState('default');
  const [direction,setDirection]=useState('asc');
  const toggleRows=()=>setRowOrder(old=>old==='default'?'asc':old==='asc'?'desc':'default');
  const toggleColumns=(key:string)=>{
    if(columnMetric!==key){setColumnMetric(key);setDirection('asc');}
    else if(direction==='asc')setDirection('desc');
    else {setColumnMetric('default');setDirection('asc');}
  };
  const columnButton=(key:string,label:string)=><button type="button" className="matrix-sort" aria-label={label}
    title={`${label}; activate to sort ascending, descending, then restore original order`}
    aria-pressed={columnMetric===key} onClick={()=>toggleColumns(key)}>
    {columnMetric===key?(direction==='asc'?<ArrowRight size={12}/>:<ArrowLeft size={12}/>):<ArrowLeftRight size={12}/>}
  </button>;
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
  const visibleMetrics=[...(showMore?[...metrics,...extraMetrics]:metrics)];
  if(rowOrder!=='default')visibleMetrics.sort((a,b)=>(rowOrder==='asc'?1:-1)*a.label.localeCompare(b.label));
  const orderedMethods=(groups:Group[])=>{
    if(columnMetric==='default')return methods;
    const metric=[...metrics,...extraMetrics].find(m=>m.key===columnMetric);
    const value=(method:string)=>{
      const matches=groups.filter(g=>g.method===method);
      return matches.length===1&&metric?metric.value(matches[0]):null;
    };
    return [...methods].sort((a,b)=>{
      if(columnMetric==='name')return (direction==='asc'?1:-1)*a.localeCompare(b);
      const av=value(a),bv=value(b);
      if(av===null)return bv===null?0:1;
      if(bv===null)return -1;
      return (direction==='asc'?1:-1)*(av-bv);
    });
  };
  return <section className="results-summary" aria-labelledby="results-title">
    <div className="results-heading"><h2 id="results-title">Results at a glance</h2><div className="matrix-actions">
      <button disabled={rowOrder==='default'&&columnMetric==='default'} onClick={()=>{setRowOrder('default');setColumnMetric('default');setDirection('asc');}}>Reset order</button>
      <button aria-expanded={showMore} onClick={()=>setShowMore(!showMore)}>{showMore?'Fewer metrics':'More metrics'}</button>
    </div>
    </div>
    {settings.map(setting=><div className="matrix-setting" key={setting.key}>
      <h3 className="matrix-setting-title" title={setting.groups[0].model}>{setting.label}
        {settings.filter(s=>s.label===setting.label).length>1&&<small>Corpus {setting.groups[0].rows[0].corpusHash?.slice(0,8)??'N/A'} · output limit {setting.groups[0].rows[0].maxOutput??'N/A'}</small>}
      </h3>
      <div className="matrix-scroll">
        <table className="comparison-matrix">
          <caption className="sr-only">Benchmark metrics by retrieval strategy for {setting.label}.</caption>
          <thead><tr><th scope="col"><span className="matrix-label"><span>Metric</span><span className="matrix-header-sorts">
            <button type="button" className="matrix-sort" aria-label="Sort metric rows by name" title="Sort metric rows A–Z, Z–A, then restore original order" aria-pressed={rowOrder!=='default'} onClick={toggleRows}>
              {rowOrder==='default'?<ArrowDownUp size={12}/>:rowOrder==='asc'?<ArrowUp size={12}/>:<ArrowDown size={12}/>}
            </button>
            {columnButton('name','Sort strategy columns by name')}
          </span></span></th>{orderedMethods(setting.groups).map(method=><th scope="col" key={method}>
            <span className="method-name"><i style={{background:color(method)}}/>{method}</span>
          </th>)}</tr></thead>
          <tbody>
            {visibleMetrics.map(metric=><tr key={metric.key}>
              <th scope="row"><span className="matrix-label"><span>{metric.label}</span>{columnButton(metric.key,`Sort strategy columns by ${metric.label.toLowerCase()}`)}</span></th>
              {orderedMethods(setting.groups).map(method=>{
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
            <tr><th scope="row">Judged answers</th>{orderedMethods(setting.groups).map(method=>{
              const groups=setting.groups.filter(g=>g.method===method);
              return <td key={method} className={hover?.method&&hover.method!==method?'faded':''}>{groups.length?groups.map(g=><button key={g.key} className="matrix-result" aria-label={`Inspect judged answers for ${method}, ${setting.label}, configuration ${g.configuration.slice(0,8)}`} title={`Completed judgments / recorded evaluations\n${g.model}\nConfiguration ${g.configuration}`} onMouseEnter={()=>setHover({method})} onMouseLeave={()=>setHover(null)} onClick={()=>onOpen(g)}><span>{g.judged} / {g.n}</span>{groups.length>1&&<small>Config {g.configuration.slice(0,8)}</small>}</button>):<span className="unavailable">N/A</span>}</td>;
            })}</tr>
          </tbody>
        </table>
      </div>
    </div>)}
    {!settings.length&&<p className="empty">No results for this selection.</p>}
    <p className="table-note">Use the small arrows to order metric names (↕) or strategy columns (↔); activate again to reverse, then reset. Hover values for sample counts; select a value to inspect questions. Unavailable or multiple-configuration values stay last. Judged coverage stays at the bottom.</p>
  </section>;
}
