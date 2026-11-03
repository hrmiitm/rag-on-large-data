import {useMemo,useState} from 'react';
import {compareValues} from './table-order';
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
  const [rowSort,setRowSort]=useState<{method:string;configuration?:string;desc:boolean}|null>(null);
  const sortColumns=(key:string)=>{
    if(columnMetric===key&&direction==='desc'){setColumnMetric('default');setDirection('asc');}
    else {setDirection(columnMetric===key?'desc':'asc');setColumnMetric(key);}
  };
  const sortRows=(method:string,configuration?:string)=>{
    setRowOrder('default');
    setRowSort(old=>old?.method===method&&old.configuration===configuration?(old.desc?null:{method,configuration,desc:true}):{method,configuration,desc:false});
  };
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
  const orderedMetrics=(groups:Group[])=>{
    if(!rowSort)return visibleMetrics;
    const matches=groups.filter(g=>g.method===rowSort.method&&(!rowSort.configuration||g.configuration===rowSort.configuration)).sort((a,b)=>a.configuration.localeCompare(b.configuration));
    return matches.length?[...visibleMetrics].sort((a,b)=>compareValues(a.value(matches[0]),b.value(matches[0]),rowSort.desc)):visibleMetrics;
  };
  const orderedMethods=(groups:Group[])=>{
    if(columnMetric==='default')return methods;
    const metric=[...metrics,...extraMetrics].find(m=>m.key===columnMetric);
    const value=(method:string)=>{
      const matches=groups.filter(g=>g.method===method);
      return matches.length===1?(columnMetric==='coverage'?matches[0].judged/matches[0].n:metric?metric.value(matches[0]):null):null;
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
    <div className="results-heading"><h2 id="results-title">Results at a glance</h2><button aria-expanded={showMore} onClick={()=>setShowMore(!showMore)}>{showMore?'Fewer metrics':'More metrics'}</button></div>
    <div className="matrix-controls">
      <label>Metric rows <select value={rowOrder} onChange={e=>{setRowOrder(e.target.value);setRowSort(null);}}><option value="default">Default order</option><option value="asc">Name A–Z</option><option value="desc">Name Z–A</option></select></label>
      <label>Strategy columns <select value={columnMetric} onChange={e=>setColumnMetric(e.target.value)}><option value="default">Default order</option><option value="name">Strategy name</option><option value="coverage">Judged-answer coverage</option>{[...metrics,...extraMetrics].map(m=><option key={m.key} value={m.key}>{m.label}</option>)}</select></label>
      <label>Column direction <select value={direction} disabled={columnMetric==='default'} onChange={e=>setDirection(e.target.value)}><option value="asc">Ascending</option><option value="desc">Descending</option></select></label>
      <button disabled={rowOrder==='default'&&columnMetric==='default'&&!rowSort} onClick={()=>{setRowOrder('default');setColumnMetric('default');setDirection('asc');setRowSort(null);}}>Reset order</button>
    </div>
    {settings.map(setting=><div className="matrix-setting" key={setting.key}>
      <h3 className="matrix-setting-title" title={setting.groups[0].model}>{setting.label}
        {settings.filter(s=>s.label===setting.label).length>1&&<small>Corpus {setting.groups[0].rows[0].corpusHash?.slice(0,8)??'N/A'} · output limit {setting.groups[0].rows[0].maxOutput??'N/A'}</small>}
      </h3>
      <div className="matrix-scroll">
        <table className="comparison-matrix">
          <caption className="sr-only">Benchmark metrics by retrieval strategy for {setting.label}.</caption>
          <thead><tr><th scope="col"><button className="axis-sort" onClick={()=>{setRowSort(null);setRowOrder(rowOrder==='asc'?'desc':rowOrder==='desc'?'default':'asc');}}>Metric<span aria-hidden="true" className="sort-icon" data-direction="both"/></button></th>{orderedMethods(setting.groups).map(method=><th scope="col" key={method}>
            <button className="axis-sort" aria-label={`Sort metric rows by ${method}`} title="Sort metric rows by this strategy’s raw values (different units); tap again to reverse, then reset" onClick={()=>sortRows(method)}><span className="method-name"><i style={{background:color(method)}}/>{method}</span><span aria-hidden="true" className="sort-icon" data-direction={rowSort?.method===method?(rowSort.desc?'desc':'asc'):'both'}/></button>
            {setting.groups.filter(g=>g.method===method).length>1&&<div className="config-sort-options">{setting.groups.filter(g=>g.method===method).map(g=><button key={g.configuration} className="axis-sort" aria-label={`Sort metric rows by ${method} configuration ${g.configuration.slice(0,8)}`} onClick={()=>sortRows(method,g.configuration)}>Config {g.configuration.slice(0,8)}<span className="sort-icon" aria-hidden="true" data-direction={rowSort?.method===method&&rowSort.configuration===g.configuration?(rowSort.desc?'desc':'asc'):'both'}/></button>)}</div>}
          </th>)}</tr></thead>
          <tbody>
            {orderedMetrics(setting.groups).map(metric=><tr key={metric.key}>
              <th scope="row"><button className="axis-sort" aria-label={`Sort strategy columns by ${metric.label}`} onClick={()=>sortColumns(metric.key)}>{metric.label}<span aria-hidden="true" className="sort-icon" data-direction={columnMetric===metric.key?direction:'horizontal'}/></button></th>
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
            <tr><th scope="row"><button className="axis-sort" aria-label="Sort strategy columns by judged-answer coverage" onClick={()=>sortColumns('coverage')}>Judged answers<span aria-hidden="true" className="sort-icon" data-direction={columnMetric==='coverage'?direction:'horizontal'}/></button></th>{orderedMethods(setting.groups).map(method=>{
              const groups=setting.groups.filter(g=>g.method===method);
              return <td key={method} className={hover?.method&&hover.method!==method?'faded':''}>{groups.length?groups.map(g=><button key={g.key} className="matrix-result" aria-label={`Inspect judged answers for ${method}, ${setting.label}, configuration ${g.configuration.slice(0,8)}`} title={`Completed judgments / recorded evaluations\n${g.model}\nConfiguration ${g.configuration}`} onMouseEnter={()=>setHover({method})} onMouseLeave={()=>setHover(null)} onClick={()=>onOpen(g)}><span>{g.judged} / {g.n}</span>{groups.length>1&&<small>Config {g.configuration.slice(0,8)}</small>}</button>):<span className="unavailable">N/A</span>}</td>;
            })}</tr>
          </tbody>
        </table>
      </div>
    </div>)}
    {!settings.length&&<p className="empty">No results for this selection.</p>}
    <p className="table-note">Averages use the selected answers. Hover for sample counts; select a value to inspect its questions. Tap any metric row to sort strategy columns. Tap any strategy header to sort metric rows by raw numeric value across different units. For multiple configurations, use its configuration button; the main strategy header uses the first configuration in ID order. Tap again to reverse; a third tap resets. Column sorting uses each table’s values; unavailable or multiple-configuration values stay last. Judged coverage stays at the bottom.</p>
  </section>;
}
