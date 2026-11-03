import {useCallback,useEffect,useMemo,useState} from 'react';
import {ArrowRight,Search,Share2,X} from 'lucide-react';
import Charts from './Charts';import ComparisonMatrix from './ComparisonMatrix';import CategoryBreakdownTable from './CategoryBreakdownTable';import {Leaderboard,JudgeCharts,Methodology} from './Analytics';import {Explorer,QuestionDetail} from './Explorer';import {filterRows,filtersQuery,groupRows,initialFilters,matchedComparison,mean,parseFilters,readable} from './data.mjs';import {color,money,num,percent,seconds,shortModel} from './format';import type {Evaluation,Filters,Group,Hover,Manifest,Question} from './types';
const pages=[{id:'overview',label:'Overview'},{id:'questions',label:'Question explorer'},{id:'judge',label:'Judge analysis'},{id:'methodology',label:'Methodology'}];
const toggle=(xs:string[],x:string)=>xs.includes(x)?xs.filter(s=>s!==x):[...xs,x];
export default function App(){
 const [manifest,setManifest]=useState<Manifest|null>(null),[rows,setRows]=useState<Evaluation[]>([]),[questions,setQuestions]=useState<Question[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(true);
 const [filters,setFilters]=useState<Filters>(()=>parseFilters(location.search)),[page,setPage]=useState(()=>new URLSearchParams(location.search).get('view')||'overview'),[inspect,setInspect]=useState<string|null>(()=>new URLSearchParams(location.search).get('inspect'));
 const [hover,setHover]=useState<Hover>(null),[advanced,setAdvanced]=useState(false),[shared,setShared]=useState(false),[theme,setTheme]=useState(()=>localStorage.getItem('sec-rag-theme')||'light'),[systemDark,setSystemDark]=useState(()=>matchMedia('(prefers-color-scheme: dark)').matches);
 const dark=theme==='dark'||(theme==='system'&&systemDark);
 const load=useCallback(async()=>{try{const response=await fetch(`${import.meta.env.BASE_URL}data/manifest.json`,{cache:'no-store'});if(!response.ok)throw Error(`Data manifest returned HTTP ${response.status}. Run npm run data or rebuild the site.`);const m:Manifest=await response.json();const responseData=await fetch(`${import.meta.env.BASE_URL}data/${m.data}`);if(!responseData.ok)throw Error(`Evaluation asset returned HTTP ${responseData.status}. Reload after the site finishes publishing.`);const d=await responseData.json();if(!Array.isArray(d.rows)||!Array.isArray(d.questions))throw Error('The normalized data asset is invalid.');setManifest(m);setRows(d.rows);setQuestions(d.questions);setError('');}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setLoading(false);}},[]);
 useEffect(()=>{void load();},[load]);
 useEffect(()=>{const check=async()=>{try{const r=await fetch(`${import.meta.env.BASE_URL}data/manifest.json`,{cache:'no-store'});if(r.ok){const next=await r.json();if(manifest&&next.version!==manifest.version)await load();}}catch{/* Retain the current snapshot during offline periods. */}};const timer=setInterval(()=>{if(!document.hidden)void check();},60000);window.addEventListener('focus',check);return()=>{clearInterval(timer);window.removeEventListener('focus',check);};},[manifest,load]);
 useEffect(()=>{const media=matchMedia('(prefers-color-scheme: dark)');const listener=(e:MediaQueryListEvent)=>setSystemDark(e.matches);media.addEventListener('change',listener);return()=>media.removeEventListener('change',listener);},[]);
 useEffect(()=>{document.documentElement.dataset.theme=dark?'dark':'light';localStorage.setItem('sec-rag-theme',theme);},[dark,theme]);
 useEffect(()=>{const p=filtersQuery(filters);if(page!=='overview')p.set('view',page);if(inspect)p.set('inspect',inspect);const q=p.toString();history.replaceState(null,'',location.pathname+(q?'?'+q:''));},[filters,page,inspect]);
 useEffect(()=>{const pop=()=>{setFilters(parseFilters(location.search));setPage(new URLSearchParams(location.search).get('view')||'overview');setInspect(new URLSearchParams(location.search).get('inspect'));};addEventListener('popstate',pop);return()=>removeEventListener('popstate',pop);},[]);
 const filtered=useMemo(()=>filterRows(rows,filters),[rows,filters]),groups=useMemo(()=>groupRows(filtered),[filtered]),matched=useMemo(()=>matchedComparison(groups),[groups]);
 const selectionRows=useMemo(()=>filterRows(rows,{...filters,categories:[]}),[rows,filters]);
 const selected=useMemo(()=>rows.find(r=>r.id===inspect),[rows,inspect]);const closeDetail=useCallback(()=>setInspect(null),[]);
 const activeCount=Object.values(filters).reduce((n,v)=>n+(Array.isArray(v)?v.length:v!==''?1:0),0);
 const navigate=(next:string)=>{setPage(next);setHover(null);window.scrollTo({top:0,behavior:'smooth'});};
 const openGroup=(g:Group)=>{setFilters(f=>({...f,methods:[g.method],models:[g.model],configs:[g.configuration]}));navigate('questions');};
 const complete=filtered.filter(r=>r.judgeStatus==='completed').length, generated=filtered.filter(r=>r.generated).length, pending=filtered.filter(r=>r.judgeStatus==='pending').length, quality=mean(filtered.map(r=>r.scores.answer_correctness)),avgCost=mean(filtered.map(r=>r.cost)),latency=mean(filtered.map(r=>r.latency));
 const costsN=filtered.filter(r=>r.cost!==null).length,latencyN=filtered.filter(r=>r.latency!==null).length,questionN=new Set(filtered.map(r=>r.questionId)).size;
 const best=matched.n>0?[...matched.groups].sort((a,b)=>(b.scores.answer_correctness??-1)-(a.scores.answer_correctness??-1))[0]:null;
 const findings=useMemo(()=>{
  const insights:{label:string;text:string;group?:Group}[]=[];
  if(best){const tied=matched.groups.filter(g=>g.scores.answer_correctness===best.scores.answer_correctness).length>1;insights.push({label:tied?'Matched quality tie':'Matched quality leader',text:`${best.method}: ${percent(best.scores.answer_correctness)} correctness across ${matched.n} common question/model/settings pairs${tied?' (tied)':''}.`,group:best});}
  else insights.push({label:'Quality comparison pending',text:`${complete} of ${filtered.length} answer judgments are complete. ${groups.length<2?'At least two methods are needed for a strategy comparison.':'Comparable completed scores are needed before identifying a leader.'}`});
  const cheapest=matched.n>0?[...matched.groups].filter(g=>g.cost!==null&&g.costN===matched.n).sort((a,b)=>a.cost!-b.cost!)[0]:null;
  if(cheapest)insights.push({label:'Matched serving cost',text:`${cheapest.method} has the lowest measured mean cost, ${money(cheapest.cost)}, with ${percent(cheapest.scores.answer_correctness)} correctness (n=${matched.n} common pairs).`,group:cheapest});
  else if(costsN)insights.push({label:'Measured serving cost',text:`${money(avgCost)} per evaluation on average (n=${costsN}). This includes model serving and excludes judging.`});
  if(latencyN)insights.push({label:'Time to an answer',text:`${seconds(latency)} on average (n=${latencyN}), using answer-ready timing where available.`});
  return insights.slice(0,3);
 },[best,matched,complete,filtered.length,groups.length,costsN,avgCost,latencyN,latency]);
 const share=async()=>{try{await navigator.clipboard.writeText(location.href);setShared(true);setTimeout(()=>setShared(false),1800);}catch{setShared(false);prompt('Copy this filtered benchmark URL',location.href);}};
 return <div className="app-shell">
   <a className="skip-link" href="#main">Skip to results</a>
   <div className="main-shell">
     <header className="site-header">
       <nav aria-label="Main navigation">{pages.map(p=><button key={p.id} aria-current={page===p.id?'page':undefined} className={page===p.id?'selected':''} onClick={()=>navigate(p.id)}>{p.label}</button>)}</nav>
       <div className="header-actions">
         <button onClick={share}><Share2 size={15}/>{shared?'Link copied':'Share'}</button>
         <select aria-label="Color theme" value={theme} onChange={e=>setTheme(e.target.value)}><option value="light">Light</option><option value="dark">Dark</option><option value="system">System</option></select>
       </div>
     </header>
     <main id="main">
       <header className="page-intro">
         <h1>{page==='questions'?'Questions and answers':page==='judge'?'Judge results':page==='methodology'?'About this benchmark':'SEC Financial RAG benchmark'}</h1>
         <p>{page==='overview'?'Compare answer quality, cost and response time across retrieval methods.':page==='questions'?'Select a question to compare answers and inspect the evidence.':page==='judge'?'Explore correctness, faithfulness and relevance.':'The dataset, evaluation rules and source records behind the results.'}</p>
       </header>
       {loading?<div className="loading" role="status">Loading results…</div>:error?<div className="error-state" role="alert"><h2>We couldn’t load this snapshot.</h2><p>{error}</p><button onClick={()=>{setLoading(true);void load();}}>Retry loading</button></div>:manifest&&<>
         {!rows.length&&<div className="notice"><b>No valid evaluations available.</b><p>Add valid results to judge/final-results/ and rebuild.</p></div>}
         {manifest.warnings.length>0&&<details className="notice"><summary>{manifest.warnings.length} data-validation warning(s)</summary><pre>{manifest.warnings.join('\n')}</pre></details>}
         {page==='overview'&&<p className="dataset-line">{num(manifest.dataset.documents,0)} SEC filings · {manifest.dataset.filing_period} · {manifest.questionCount} questions · {manifest.methods.length} methods</p>}
         {page!=='methodology'&&<>
           <section className="filter-area" aria-label="Global benchmark filters">
             <div className="filter-toolbar">
               <label className="quick-model">Model <select aria-label="Select model" value={filters.models.length===1?filters.models[0]:''} onChange={e=>setFilters(f=>({...f,models:e.target.value?[e.target.value]:[]}))}><option value="">All models</option>{manifest.models.map(m=><option value={m} key={m}>{shortModel(m)}</option>)}</select></label>
               <label className="search-field"><Search size={17}/><input type="search" aria-label="Search questions or ID" placeholder="Search questions…" value={filters.search} onChange={e=>setFilters(f=>({...f,search:e.target.value}))}/></label>
               <button aria-expanded={advanced} onClick={()=>setAdvanced(!advanced)}>Filters{activeCount>0&&<span className="count">{activeCount}</span>}</button>
               <button className="text-button" onClick={()=>{setFilters(initialFilters());setHover(null);}}>Reset Filters</button>
             </div>
             <div className="category-row"><span className="filter-label">Category</span><div className="category-cards">
               <button className={`all-categories ${!filters.categories.length?'selected':''}`} aria-pressed={!filters.categories.length} onClick={()=>setFilters(f=>({...f,categories:[]}))}>All categories</button>
               {manifest.categories.map(c=>{
                 const all=questions.filter(q=>q.category===c),rs=selectionRows.filter(r=>r.category===c),n=rs.filter(r=>r.judgeStatus==='completed').length;
                 const gs=groupRows(rs);
                 return <button key={c} className={`category-card ${filters.categories.includes(c)?'selected':''} ${hover?.category&&hover.category!==c?'faded':''}`} aria-pressed={filters.categories.includes(c)} onMouseEnter={()=>setHover({category:c})} onMouseLeave={()=>setHover(null)} onClick={()=>setFilters(f=>({...f,categories:toggle(f.categories,c)}))} title={`${categoryDescription(c)} ${n}/${rs.length} judgments complete.`}>
                   <span>{readable(c)}</span><small>{all.length||new Set(rs.map(r=>r.questionId)).size}</small>
                   <span role="tooltip" className="category-preview"><strong>{readable(c)}</strong><span>{categoryDescription(c)}</span><span>{n}/{rs.length} judgments completed</span>{gs.map(g=><span key={g.key}>{g.method}: {percent(g.scores.answer_correctness)} · {money(g.cost)} · {seconds(g.latency)}</span>)}</span>
                 </button>;
               })}
             </div></div>
             <div className="method-row"><span className="filter-label">Method</span><div className="method-legend method-list" aria-label="Strategy legend">{manifest.methods.map(m=><button key={m} className={`${filters.methods.includes(m)?'selected':''} ${hover?.method&&hover.method!==m?'faded':''}`} aria-pressed={filters.methods.includes(m)} onMouseEnter={()=>setHover({method:m})} onMouseLeave={()=>setHover(null)} onClick={()=>setFilters(f=>({...f,methods:toggle(f.methods,m)}))}><i style={{background:color(m)}}/>{m}</button>)}</div>{filters.methods.length>0&&<button className="text-button" onClick={()=>setFilters(f=>({...f,methods:[]}))}>Clear Strategy Selection</button>}</div>
             {advanced&&<div className="advanced-filters">
               {filters.categories.length>0&&<button className="text-button clear-categories" onClick={()=>setFilters(f=>({...f,categories:[]}))}>Clear Category Selection</button>}
               {[['models','LLM models',manifest.models],['methods','Retrieval strategies',manifest.methods],['status','Judge status',['completed','pending','skipped','error','missing']],['configs','Configuration hashes',[...new Set(rows.map(r=>r.configuration))]]].map(([key,label,options]:any)=><fieldset key={key}><legend>{label}</legend>{options.map((v:string)=><label className="check" key={v}><input type="checkbox" checked={(filters[key as keyof Filters] as string[]).includes(v)} onChange={()=>setFilters(f=>({...f,[key]:toggle(f[key as keyof Filters] as string[],v)}))}/><span title={v}>{key==='configs'?v.slice(0,12):key==='status'?v==='missing'?'Not Evaluated':readable(v):v}</span></label>)}</fieldset>)}
               <fieldset className="numeric-filters"><legend>Ranges</legend>{[['correctness','Correctness (%)'],['cost','Serving cost (USD)'],['latency','Answer latency (s)']].map(([key,label])=><div className="range-fields" key={key}><span>{label}</span>{['Min','Max'].map(bound=><input key={bound} type="number" step="any" min="0" max={key==='correctness'?100:undefined} aria-label={`${label} ${bound.toLowerCase()}`} placeholder={bound} value={filters[`${key}${bound}` as keyof Filters] as string} onChange={e=>setFilters(f=>({...f,[key+bound]:e.target.value}))}/>)}</div>)}</fieldset>
             </div>}
             {activeCount>0&&<div className="filter-chips" aria-label="Active filters">{Object.entries(filters).flatMap(([key,v])=>Array.isArray(v)?v.map(value=><button key={`${key}:${value}`} onClick={()=>setFilters(f=>({...f,[key]:(f[key as keyof Filters] as string[]).filter(x=>x!==value)}))}>{key==='categories'?readable(value):key==='configs'?`Config ${value.slice(0,8)}`:value}<X size={12}/></button>):v!==''?[<button key={key} onClick={()=>setFilters(f=>({...f,[key]:''}))}>{readable(key)}: {v}<X size={12}/></button>]:[])}</div>}
           </section>
           {filters.categories.length>0&&<div className="spotlight"><div><h3>{filters.categories.map(readable).join(' + ')}</h3><p>{questionN} questions{best?` · ${best.method}: ${percent(best.scores.answer_correctness)} correctness on ${matched.n} matched pairs, ${money(best.cost)} average cost.`:' · Comparable completed judgments are needed to identify a leader.'}</p></div><button onClick={()=>navigate('questions')}>Inspect questions</button></div>}
           {!filtered.length&&rows.length>0&&<p className="empty">No evaluations match this selection. Clear a filter to continue.</p>}
         </>}
         {page==='overview'&&<>
           <Charts rows={filtered} categories={manifest.categories.filter(c=>!filters.categories.length||filters.categories.includes(c))} methods={manifest.methods.filter(m=>!filters.methods.length||filters.methods.includes(m))} dark={dark} hover={hover} setHover={setHover} setFilters={setFilters} openEvaluations={openGroup}/>
           <section className="corpus-summary" aria-label="Corpus at a glance">
             <strong>Corpus at a glance</strong>
             <ul>
               <li>{num(manifest.dataset.documents,0)} filing documents: {num(manifest.dataset.form_counts?.['10-K'],0)} annual (10-K) and {num(manifest.dataset.form_counts?.['10-Q'],0)} quarterly (10-Q), from {manifest.dataset.filing_period}.</li>
               <li>{num(manifest.dataset.section_spans,0)} retained section spans: MD&amp;A and financial statements/notes, rather than complete filings.</li>
               <li>{num(manifest.dataset.chunks,0)} BM25 chunks across {num(manifest.dataset.lexical_shards,0)} shards; the same chunks supply semantic/hybrid vectors. {num(manifest.dataset.body_tokens,0)} body tokens per chunk, with {num(manifest.dataset.overlap_tokens,0)} overlap.</li>
               <li>Average retained filing: about {num(manifest.dataset.documents>0?manifest.dataset.retained_words/manifest.dataset.documents:null,0)} words / {num(manifest.dataset.documents>0?manifest.dataset.source_tokens/manifest.dataset.documents:null,0)} tokens. Total: {manifest.dataset.retained_size}; {manifest.dataset.prepared_size} Parquet.</li>
             </ul>
             <small>Full corpus totals, independent of filters. Words are whitespace-separated; reference answers and evidence stay outside the retrieval index.</small>
           </section>
           <ComparisonMatrix rows={filtered} methods={manifest.methods.filter(m=>!filters.methods.length||filters.methods.includes(m))} hover={hover} setHover={setHover} onOpen={openGroup}/>
           <CategoryBreakdownTable rows={rows} categories={manifest.categories} methods={manifest.methods.filter(m=>!filters.methods.length||filters.methods.includes(m))} manifest={manifest} questions={questions} onSelectCategory={(cat)=>{setFilters(f=>({...f,categories:[cat]}));navigate('questions');}}/>
           {pending>0&&complete===0&&<p className="pending-note">Judgments are pending for {pending} answers. Measured costs and response times are available.</p>}
           <details className="disclosure"><summary>Summary statistics and findings</summary>
             <section className="kpi-grid" aria-label="Filtered key performance indicators"><Kpi label="Answer correctness" value={percent(quality)} detail={`${complete} valid judged / ${filtered.length} evaluations`}/><Kpi label="Average serving cost" value={money(avgCost)} detail={`USD per evaluation · measured n=${costsN}`}/><Kpi label="Average answer latency" value={seconds(latency)} detail={`Answer ready · measured n=${latencyN}`}/><Kpi label="Evaluation coverage" value={`${generated} / ${filtered.length}`} detail={`${questionN} questions · ${pending} pending judgments`}/></section>
             <ul className="findings" aria-label="Data-derived findings">{findings.map((f,i)=><li key={i}><button className="text-button" onClick={()=>f.group?openGroup(f.group):navigate(i===0?'judge':'questions')}><b>{f.label}.</b> {f.text}</button></li>)}</ul>
           </details>
           <details className="disclosure"><summary>Detailed results and matched comparisons</summary><Leaderboard rows={filtered} hover={hover} setHover={setHover} onOpen={openGroup}/></details>
           <p className="explore-link"><button onClick={()=>navigate('questions')}>Browse all questions <ArrowRight size={16}/></button></p>
         </>}
         {page==='questions'&&<Explorer rows={filtered} hover={hover} setHover={setHover} onInspect={r=>setInspect(r.id)} manifest={manifest}/>}
         {page==='judge'&&<><JudgeCharts rows={filtered} dark={dark}/><Explorer rows={filtered} judge hover={hover} setHover={setHover} onInspect={r=>setInspect(r.id)} manifest={manifest}/></>}
         {page==='methodology'&&<Methodology manifest={manifest} rows={rows} questions={questions}/>}
         {page!=='overview'&&page!=='methodology'&&<p className="table-note">{filtered.length} evaluations · {complete} judged · {pending} pending</p>}
         <footer className="page-footer"><span>SEC Financial RAG benchmark</span><span>Data updated {new Date(manifest.publishedAt).toLocaleString()}</span></footer>
       </>}
     </main>
   </div>
   {selected&&manifest&&<QuestionDetail row={selected} manifest={manifest} onClose={closeDetail}/>}
 </div>;
}
function Kpi({label,value,detail}:{label:string;value:string;detail:string}){return <article className="kpi"><span>{label}</span><strong>{value}</strong><p>{detail}</p></article>;}
function categoryDescription(c:string){if(c.includes('multi_document'))return 'Connect evidence across separate filings.';if(c.includes('comparative'))return 'Align and compare financial disclosures.';if(c.includes('reasoning'))return 'Reason from reported financial evidence.';if(c.includes('risk'))return 'Interpret risk and governance disclosures.';if(c.includes('lookup'))return 'Locate a specific disclosed fact.';return 'Explore the source-backed reference questions.';}
