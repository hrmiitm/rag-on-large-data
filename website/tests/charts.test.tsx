import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import fs from 'node:fs';
import path from 'node:path';
import Charts,{paretoFrontiers} from '../src/Charts';
import {groupRows} from '../src/data.mjs';
import {methodDescription,accuracyOrder,methodColor} from '../src/MethodLegend';
import {normalize} from '../scripts/normalize.mjs';
import type {Evaluation} from '../src/types';

vi.mock('../src/Plot',()=>({default:({data,onClick,log,revision}:any)=><div data-testid="chart-series" data-log={String(log)} data-revision={revision} data-series={JSON.stringify(data)}>{data.filter((t:any)=>t.customdata).map((trace:any,i:number)=><button key={i} data-trace={JSON.stringify(trace)} onClick={()=>onClick?.({customdata:trace.customdata[0]})}>{trace.name??i}</button>)}</div>}));
const seed=normalize(JSON.parse(fs.readFileSync(path.resolve('tests/fixtures/presentation-record.json'),'utf8')),'q-a-eval-fixture.jsonl')[0] as Evaluation;
const rows=['bm25','agentic','semantic-search','hybrid'].map((sourceMethod,i)=>({...seed,id:String(i),method:`lume-${sourceMethod}`,sourceMethod,judgeStatus:'completed',scores:{...seed.scores,answer_correctness:.8},cost:.01+i*.01,latency:5+i}));
function mount(data:Evaluation[]=rows){const open=vi.fn(),hover=vi.fn(),filters=vi.fn();render(<Charts rows={data} methods={[...new Set(data.map(r=>r.method))]} categories={[seed.category]} dark={false} hover={null} setHover={hover} setFilters={filters} openEvaluations={open}/>);return {open,hover,filters};}
const traces=()=>within(screen.getByTestId('chart-series')).getAllByRole('button').map(button=>JSON.parse(button.getAttribute('data-trace')!));
afterEach(cleanup);

it('uses numbered, distinct method controls and concise scatter hovers without overlay tooltips',async()=>{
  mount();const legend=screen.getByRole('group',{name:'Chart methods'});
  for(const row of rows)expect(within(legend).getByRole('button',{name:row.method,exact:true})).toBeTruthy();
  expect(screen.queryByRole('tooltip')).toBeNull();
  expect(new Set(traces().map(t=>t.marker.color)).size).toBe(4);
  for(const trace of traces()){expect(trace.mode).toBe('markers+text');expect(trace.text).toEqual(['1']);expect(trace.hovertemplate).toContain('Configuration:');expect(trace.hovertemplate).not.toContain('LLM receives:');}
  expect(screen.getByLabelText('Cost axis')).toHaveProperty('value','log');expect(screen.getByRole('checkbox',{name:'Show Pareto frontier'})).toHaveProperty('checked',true);await userEvent.click(screen.getByRole('checkbox',{name:'Show Pareto frontier'}));expect(screen.getByRole('checkbox',{name:'Show Pareto frontier'})).toHaveProperty('checked',false);
  await userEvent.selectOptions(screen.getByLabelText('Chart view'),'latency');
  expect(traces()).toHaveLength(4);expect(screen.getByLabelText('Chart quality metric')).toBeTruthy();
});

it('pins readable details on click, leaves other points visible, supports clear and Escape without filtering',async()=>{
  const {open,filters}=mount();const semantic=within(screen.getByRole('group',{name:'Chart methods'})).getByRole('button',{name:'lume-semantic-search'});
  await userEvent.hover(semantic);expect(screen.queryByRole('tooltip')).toBeNull();
  await userEvent.click(semantic);await userEvent.unhover(semantic);
  const panel=screen.getByLabelText('Selected chart series');
  expect(panel.textContent).toContain('text-embedding-3-small');expect(panel.textContent).toContain('top semantic matches');
  expect(semantic.getAttribute('aria-pressed')).toBe('true');expect(traces().every(t=>t.marker.opacity>=.65)).toBe(true);
  expect(open).not.toHaveBeenCalled();expect(filters).not.toHaveBeenCalled();
  await userEvent.keyboard('{Escape}');expect(semantic.getAttribute('aria-pressed')).toBe('false');expect(panel.textContent).not.toContain('text-embedding-3-small');
  await userEvent.click(semantic);await userEvent.click(screen.getByRole('button',{name:'Clear selection'}));expect(semantic.getAttribute('aria-pressed')).toBe('false');
});

it('keeps configurations separate and inspects only the explicitly selected series',async()=>{
  const data=[{...rows[0],method:'future-hybrid-v9'},{...rows[0],id:'other-config',method:'future-hybrid-v9',configuration:'b'.repeat(64),cost:.09}];
  const {open}=mount(data);await userEvent.click(within(screen.getByTestId('chart-series')).getAllByRole('button')[1]);
  expect(open).not.toHaveBeenCalled();const panel=screen.getByLabelText('Selected chart series');
  expect(panel.textContent).toContain('BM25 is a keyword relevance score');expect(panel.textContent).not.toContain('multiplicative');expect(panel.textContent).toContain('$0.0900');
  expect(within(screen.getByLabelText('Selected method series')).getAllByRole('option')).toHaveLength(2);
  await userEvent.click(screen.getByRole('button',{name:'Inspect answers →'}));expect(open).toHaveBeenCalledWith(expect.objectContaining({method:'future-hybrid-v9',configuration:'b'.repeat(64)}));
  await userEvent.selectOptions(screen.getByLabelText('Selected method series'),traces()[0].customdata[0]);
  expect(panel.textContent).toContain('$0.0100');
});

it('updates the selected quality measure, exposes missing measurements and keeps denominators distinct',async()=>{
  mount([{...rows[0],scores:{...rows[0].scores,faithfulness:.6}},{...rows[0],id:'missing',cost:null,latency:null,scores:{...rows[0].scores,answer_correctness:null,faithfulness:null}}]);
  await userEvent.selectOptions(screen.getByLabelText('Chart quality metric'),'faithfulness');expect(traces()[0].y).toEqual([60]);
  await userEvent.click(within(screen.getByTestId('chart-series')).getAllByRole('button')[0]);
  const panel=screen.getByLabelText('Selected chart series');expect(panel.textContent).toContain('60.0%');expect(panel.textContent).toContain('1 / 2 scored');expect(panel.textContent).toContain('1 measured answers');
  await userEvent.click(screen.getByText(/Exact values ·/));expect(screen.getByRole('table').textContent).toContain('60.0%');
});

it('documents all ten adapters from recorded identities and keeps unknown adapters explicit',()=>{
  for(const sourceMethod of ['bm25','agentic','semantic-search','hybrid','hybrid-rerank','semantic-rerank','rrf','rrf-rerank','hyde','self-reflective-rag'])expect(methodDescription([{...seed,sourceMethod}]).search).not.toContain('not documented');
  expect(methodDescription([{...seed,sourceMethod:'hyde'}]).sent).toContain('never supplied as evidence');
  expect(methodDescription([{...seed,sourceMethod:'self-reflective-rag'}]).search).toContain('one extra evidence search');
  expect(methodDescription([{...seed,sourceMethod:'constructor',retrievalProfile:undefined}]).search).toContain('not documented');
  expect(methodDescription([rows[0],rows[1]]).search).toContain('Multiple recorded');
});

it('keeps future methods with missing quality available through controls and exact values, escaping Plotly labels',async()=>{
  mount([{...seed,method:'future-<hybrid>',sourceMethod:'unknown',scores:{...seed.scores,answer_correctness:null}}]);
  await userEvent.click(screen.getByRole('button',{name:'future-<hybrid>',exact:true}));
  expect(screen.getByLabelText('Selected chart series').textContent).toContain('Recorded ranking signals');
  expect(traces()[0].hovertemplate).toContain('future &lt;hybrid&gt;');expect(traces()[0].y).toEqual([null]);
  await userEvent.click(screen.getByText(/Exact values ·/));expect(screen.getByRole('table').textContent).toContain('Not Evaluated');
});

it('clears stale details when global filters remove the selected series',async()=>{
  const props={methods:rows.map(r=>r.method),categories:[seed.category],dark:false,hover:null,setHover:vi.fn(),setFilters:vi.fn(),openEvaluations:vi.fn()};
  const {rerender}=render(<Charts {...props} rows={rows}/>);await userEvent.click(screen.getByRole('button',{name:'lume-bm25',exact:true}));
  rerender(<Charts {...props} rows={rows.slice(1)}/>);expect(screen.queryByRole('button',{name:'Inspect answers →'})).toBeNull();
});

it('keeps heatmap configurations separate and drills down with the exact model and configuration',async()=>{
  const other={...rows[0],id:'second',configuration:'c'.repeat(64),scores:{...rows[0].scores,answer_correctness:.4}};
  const {filters}=mount([rows[0],other]);await userEvent.selectOptions(screen.getByLabelText('Chart view'),'heatmap');
  const cells=screen.getAllByRole('button',{name:`Filter ${seed.category.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase())} and lume-bm25`});
  expect(cells).toHaveLength(2);expect(cells[0].textContent).toContain('80.0%');expect(cells[1].textContent).toContain('40.0%');
  await userEvent.click(cells[1]);expect(filters.mock.calls.at(-1)![0]({})).toEqual(expect.objectContaining({methods:['lume-bm25'],models:[other.model],configs:[other.configuration]}));
});

it('computes frontiers with tied costs, dominated points, missing data and incompatible settings kept separate',()=>{
 const point=(i:number,cost:number,score:number,extra:Partial<Evaluation>={})=>({...rows[0],id:String(i),method:`m${i}`,cost,latency:cost*100,scores:{...rows[0].scores,answer_correctness:score},...extra});
 const fixture=[point(1,.01,.5),point(2,.01,.6),point(3,.02,.55),point(4,.03,.8),point(5,.03,.8),point(6,.001,1,{model:'other-model'}),point(7,.001,1,{questionId:'other-question'}),point(8,.001,1,{corpusHash:null}),point(9,.001,1,{reasoning:'LOW'}),point(10,.001,1,{judgeStatus:'pending'}),point(11,.001,1,{cost:null})];
 for(const x of ['cost','medianLatency'] as const){const groups=groupRows(fixture.filter(r=>x==='cost'||r.cost!==null));const result=paretoFrontiers(groups,'answer_correctness',x).filter(points=>points.length>1);expect(result).toHaveLength(1);expect(result[0].map(g=>[g.cost,g.scores.answer_correctness])).toEqual([[.01,.6],[.03,.8],[.03,.8]]);}
});

it('draws the default frontier behind points and recomputes it when toggled or the quality metric changes',async()=>{
 mount([{...rows[0],scores:{...rows[0].scores,answer_correctness:.6,faithfulness:.8}},{...rows[1],scores:{...rows[1].scores,answer_correctness:.8,faithfulness:.6}}]);
 const all=()=>JSON.parse(screen.getByTestId('chart-series').getAttribute('data-series')!);
 expect(all()[0]).toEqual(expect.objectContaining({mode:'lines',x:[.01,.02],y:[60,80],hoverinfo:'skip',line:expect.objectContaining({shape:'hv',simplify:false})}));
 await userEvent.click(screen.getByRole('checkbox',{name:'Show Pareto frontier'}));expect(all().some((t:any)=>t.mode==='lines')).toBe(false);
 await userEvent.click(screen.getByRole('checkbox',{name:'Show Pareto frontier'}));expect(all()[0].mode).toBe('lines');
 await userEvent.selectOptions(screen.getByLabelText('Chart quality metric'),'faithfulness');expect(all().some((t:any)=>t.mode==='lines')).toBe(false);
});

it('orders controls and point numbers by correctness, shares ties, and keeps rank independent of the selected chart metric',async()=>{
 const data=rows.map((r,i)=>({...r,scores:{...r.scores,answer_correctness:[.3,.8,.8,null][i],faithfulness:[.9,.1,.2,.7][i]}}));
 mount(data);const legend=screen.getByRole('group',{name:'Chart methods'});const buttons=within(legend).getAllByRole('button');
 expect(buttons.map(b=>b.getAttribute('aria-label'))).toEqual(['lume-agentic','lume-semantic-search','lume-bm25','lume-hybrid']);
 expect(buttons.map(b=>b.querySelector('.chart-method-number')!.textContent)).toEqual(['1','1','3','—']);
 expect(traces().map(t=>t.text)).toEqual([['3'],['1'],['1'],['—']]);const colors=traces().map(t=>t.marker.color);
 await userEvent.selectOptions(screen.getByLabelText('Chart quality metric'),'faithfulness');expect(traces().map(t=>t.text)).toEqual([['3'],['1'],['1'],['—']]);expect(traces().map(t=>t.marker.color)).toEqual(colors);
 await userEvent.click(within(legend).getByRole('button',{name:'lume-bm25'}));
 const panel=screen.getByLabelText('Selected chart series');expect(panel.querySelector('.chart-method-number')!.textContent).toBe('3');expect(within(panel).getAllByRole('listitem')).toHaveLength(3);
});

it('recomputes accuracy rank from filtered rows without averaging across models or configurations',()=>{
 const data=[{...rows[0],scores:{...rows[0].scores,answer_correctness:.4}},{...rows[1],scores:{...rows[1].scores,answer_correctness:.9}}];
 const methods=data.map(r=>r.method);expect(accuracyOrder(methods,groupRows(data)).ranks.get(data[0].method)).toBe('2');
 expect(accuracyOrder(methods,groupRows(data.slice(0,1))).ranks.get(data[0].method)).toBe('1');
 for(const extra of [{model:'other-model'},{reasoning:'LOW'},{maxOutput:4096},{corpusHash:'different'}]){const ranked=accuracyOrder(methods,groupRows([data[0],{...data[1],...extra}]));expect(ranked.comparable).toBe(false);expect([...ranked.ranks.values()]).toEqual(['—','—']);}
 const configs=accuracyOrder(methods,groupRows([...data,{...data[0],id:'config2',configuration:'other-config'}]));expect(configs.comparable).toBe(false);expect([...configs.ranks.values()]).toEqual(['—','—']);
});

it('uses discovered filenames for Elasticsearch and future frontier membership, and resets filtered chart coordinates',async()=>{
 const raw=JSON.parse(fs.readFileSync(path.resolve('tests/fixtures/presentation-record.json'),'utf8'));
 const point=(filename:string,cost:number,score:number)=>({...normalize(raw,filename)[0],judgeStatus:'completed',cost,latency:cost*100,scores:{...seed.scores,answer_correctness:score}} as Evaluation);
 const baseline=point('q-a-eval-baseline.jsonl',.01,.5),elastic=point('q-a-eval-elasticsearch.jsonl',.03,.9),future=point('q-a-eval-future-method-with-hyphens.jsonl',.02,.95);
 const props={methods:[baseline.method,elastic.method,future.method],categories:[seed.category],dark:false,hover:null,setHover:vi.fn(),setFilters:vi.fn(),openEvaluations:vi.fn()};
 const {rerender}=render(<Charts {...props} rows={[baseline,elastic]}/>);
 const all=()=>JSON.parse(screen.getByTestId('chart-series').getAttribute('data-series')!);
 expect(screen.getByTestId('chart-series').getAttribute('data-log')).toBe('true');
 expect(all()[0].x).toEqual([.01,.03]);expect(all()[0].line.shape).toBe('hv');
 expect(screen.getByLabelText('Pareto frontier methods').textContent).toContain('elasticsearch');
 const revision=screen.getByTestId('chart-series').getAttribute('data-revision');
 rerender(<Charts {...props} rows={[baseline,elastic,future]}/>);
 expect(all()[0].x).toEqual([.01,.02]);
 expect(screen.getByTestId('chart-series').getAttribute('data-revision')).not.toBe(revision);
 const summary=screen.getByLabelText('Pareto frontier methods');expect(summary.textContent).toContain('future method with hyphens');expect(summary.textContent).not.toContain('elasticsearch');
 expect(traces().find(t=>t.name.startsWith('elasticsearch')).marker.line.width).toBe(1.5);
 expect(traces().find(t=>t.name.startsWith('future-method')).hovertemplate).toContain('On Pareto frontier');
 await userEvent.click(within(summary).getByRole('button',{name:/Inspect Pareto method future-method/}));
 expect(screen.getByLabelText('Selected chart series').textContent).toContain('future method with hyphens');
 rerender(<Charts {...props} rows={[elastic]}/>);
 expect(all().some((t:any)=>t.mode==='lines')).toBe(false);
 expect(screen.getByLabelText('Pareto frontier methods').textContent).toContain('elasticsearch');
 expect(traces()[0].marker.line.width).toBe(3);
});

it('keeps zero costs exact and linear-plottable without supplying invalid log coordinates',async()=>{
 mount([{...rows[0],cost:0,scores:{...rows[0].scores,answer_correctness:.5}},{...rows[1],cost:.02,scores:{...rows[1].scores,answer_correctness:.8}}]);
 expect(traces()[0].x).toEqual([null]);expect(screen.getByText(/Log scale shows positive costs/)).toBeTruthy();
 await userEvent.selectOptions(screen.getByLabelText('Cost axis'),'linear');
 expect(screen.getByTestId('chart-series').getAttribute('data-log')).toBe('false');expect(traces()[0].x).toEqual([0]);
 const all=JSON.parse(screen.getByTestId('chart-series').getAttribute('data-series')!);expect(all[0].x).toEqual([0,.02]);
});

it('preserves all methods tied on the frontier but deduplicates line coordinates',()=>{
 const data=[{...rows[0],cost:.01,scores:{...seed.scores,answer_correctness:.6}},{...rows[1],cost:.02,scores:{...seed.scores,answer_correctness:.8}},{...rows[2],cost:.02,scores:{...seed.scores,answer_correctness:.8}}];
 mount(data);const all=JSON.parse(screen.getByTestId('chart-series').getAttribute('data-series')!);
 expect(all[0].x).toEqual([.01,.02]);expect(traces().every(t=>t.marker.line.width===3)).toBe(true);
 expect(within(screen.getByLabelText('Pareto frontier methods')).getAllByRole('button')).toHaveLength(3);
});

it('extends distinct method colors past ten and describes unknown retrieval from exported fields',()=>{
 const methods=Array.from({length:25},(_,i)=>`discovered-${i}`);expect(new Set(methods.map(m=>methodColor(m,methods))).size).toBe(25);
 const row={...seed,sourceMethod:'new-unregistered-adapter',retrievalProfile:{retriever:'saved-retriever-v2',modes:['keyword','hybrid'],signals:['bm25','elasticsearch_knn','rrf']}};
 const description=methodDescription([row]);expect(description.search).toContain('saved-retriever-v2');expect(description.search).toContain('keyword, hybrid');expect(description.search).toContain('bm25, elasticsearch_knn, rrf');
});

it('draws the live discovered dataset frontier from its individual exported evaluations',async()=>{
 const base=path.resolve('public/data'),manifest=JSON.parse(fs.readFileSync(path.join(base,'manifest.json'),'utf8'));
 const data=JSON.parse(fs.readFileSync(path.join(base,manifest.data),'utf8')).rows as Evaluation[];
 const groups=groupRows(data);
 // Independent ascending-cost scan for this snapshot's fully matched settings/question sets.
 const settings=(g:any)=>JSON.stringify([g.model,g.rows[0].reasoning,g.rows[0].maxOutput,g.rows[0].corpusHash,g.rows[0].questionHash,g.rows.map((r:Evaluation)=>[r.questionId,r.asOf]).sort()]);
 const eligible=groups.filter((g:any)=>g.rows[0].corpusHash&&g.rows[0].questionHash&&g.rows.every((r:Evaluation)=>r.judgeStatus==='completed'&&r.cost!==null&&r.scores.answer_correctness!==null));
 const buckets=[...new Set(eligible.map(settings))].map(key=>eligible.filter((g:any)=>settings(g)===key));
 const expected=buckets.map(bucket=>{
  let best=-Infinity;const frontier:any[]=[];
  for(const g of [...bucket].sort((a,b)=>a.cost-b.cost||b.scores.answer_correctness-a.scores.answer_correctness))if(g.scores.answer_correctness>best){frontier.push(g);best=g.scores.answer_correctness;}
  return frontier;
 });
 mount(data);
 expect(traces()).toHaveLength(groups.length);expect(new Set(traces().map(t=>t.marker.color)).size).toBe(manifest.methods.length);
 const lines=JSON.parse(screen.getByTestId('chart-series').getAttribute('data-series')!).filter((t:any)=>t.mode==='lines');
 expect(lines.map((t:any)=>t.x)).toEqual(expected.filter(p=>p.length>1).map(p=>p.map(g=>g.cost)));
 expect(lines.map((t:any)=>t.y)).toEqual(expected.filter(p=>p.length>1).map(p=>p.map(g=>g.scores.answer_correctness*100)));
 const elastic=data.find(r=>r.method==='elasticsearch');
 if(elastic){await userEvent.click(screen.getByRole('button',{name:'elasticsearch',exact:true}));const panel=screen.getByLabelText('Selected chart series');expect(panel.textContent).toContain('approximate vector search');expect(panel.textContent).toContain('reciprocal rank fusion');expect(panel.textContent).toContain('no new embeddings');}
});

it('explains Elasticsearch simply and computes comparison text from matched filtered records',()=>{
 const elastic={...rows[0],method:'elasticsearch',sourceMethod:'elasticsearch-agentic',latency:20,cost:.03,metrics:{retrieval_time_ms:1000},scores:{...seed.scores,answer_correctness:.9}};
 const baseline={...rows[0],latency:10,cost:.01,scores:{...seed.scores,answer_correctness:.5}};
 const extra={...elastic,id:'extra',questionId:'unmatched',latency:1000,cost:1};
 const description=methodDescription([elastic,extra],[elastic,extra,baseline,{...baseline,method:'other-model',model:'different-model'}]);
 expect(description.steps).toHaveLength(3);expect(description.steps!.join(' ')).toContain('saved vector');expect(description.steps!.join(' ')).toContain('neighbouring passages');
 expect(description.comparison).toContain('no cross-encoder');expect(description.performance).toContain('1.00 s per question');expect(description.performance).toContain('judging is separate');
 expect(description.observations).toHaveLength(1);expect(description.observations![0]).toContain('1 matched questions');expect(description.observations![0]).toContain('90.0% vs. 50.0%');expect(description.observations![0]).toContain('20.00 s vs. 10.00 s');expect(description.observations![0]).toContain('$0.0300 vs. $0.0100');
 const filtered=methodDescription([elastic],[{...baseline,reasoning:'LOW'}]);expect(filtered.observations).toHaveLength(0);
});
