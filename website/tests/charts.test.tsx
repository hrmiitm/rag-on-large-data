import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import fs from 'node:fs';
import path from 'node:path';
import Charts from '../src/Charts';
import {methodDescription} from '../src/MethodLegend';
import {normalize} from '../scripts/normalize.mjs';
import type {Evaluation} from '../src/types';

vi.mock('../src/Plot',()=>({default:({data,onClick}:any)=><div data-testid="chart-series">{data.filter((t:any)=>t.customdata).map((trace:any,i:number)=><button key={i} data-trace={JSON.stringify(trace)} onClick={()=>onClick?.({customdata:trace.customdata[0]})}>{trace.name??i}</button>)}</div>}));
const seed=normalize(JSON.parse(fs.readFileSync(path.resolve('tests/fixtures/presentation-record.json'),'utf8')),'q-a-eval-fixture.jsonl')[0] as Evaluation;
const rows=['bm25','agentic','semantic-search','hybrid'].map((sourceMethod,i)=>({...seed,id:String(i),method:`lume-${sourceMethod}`,sourceMethod,judgeStatus:'completed',scores:{...seed.scores,answer_correctness:.8},cost:.01+i*.01,latency:5+i}));
function mount(data:Evaluation[]=rows){const open=vi.fn(),hover=vi.fn(),filters=vi.fn();render(<Charts rows={data} methods={[...new Set(data.map(r=>r.method))]} categories={[seed.category]} dark={false} hover={null} setHover={hover} setFilters={filters} openEvaluations={open}/>);return {open,hover,filters};}
const traces=()=>within(screen.getByTestId('chart-series')).getAllByRole('button').map(button=>JSON.parse(button.getAttribute('data-trace')!));
afterEach(cleanup);

it('shows every discovered method above the chart while scatter labels appear only in hover details',async()=>{
  mount();const legend=screen.getByRole('group',{name:'Chart methods'});
  for(const row of rows)expect(within(legend).getByRole('button',{name:row.method,exact:true})).toBeTruthy();
  expect(legend.compareDocumentPosition(screen.getByTestId('chart-series'))&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByRole('tooltip')).toBeNull();
  for(const trace of traces()){expect(trace.mode).toBe('markers');expect(trace.text).toBeUndefined();expect(trace.hovertemplate).toContain('Search:');expect(trace.hovertemplate).toContain('LLM receives:');expect(trace.hovertemplate).toContain('Configuration:');}
  expect(traces().find(t=>t.name.startsWith('lume-hybrid')).hovertemplate).toContain('multiplicative fusion');
  await userEvent.selectOptions(screen.getByLabelText('Chart view'),'latency');
  expect(screen.getByRole('group',{name:'Chart methods'})).toBeTruthy();expect(traces().every(t=>t.mode==='markers')).toBe(true);
});

it('method hover and keyboard focus explain the actual technique and context without changing filters',async()=>{
  const {hover,filters}=mount();const legend=screen.getByRole('group',{name:'Chart methods'});const semantic=within(legend).getByRole('button',{name:'lume-semantic-search'});
  await userEvent.hover(semantic);
  expect(screen.getByRole('tooltip').textContent).toContain('text-embedding-3-small');expect(screen.getByRole('tooltip').textContent).toContain('top semantic matches');expect(hover).toHaveBeenLastCalledWith({method:'lume-semantic-search'});
  await userEvent.unhover(semantic);expect(screen.queryByRole('tooltip')).toBeNull();
  const agentic=within(legend).getByRole('button',{name:'lume-agentic'});await userEvent.click(agentic);
  expect(screen.getByRole('tooltip').textContent).toContain('refines BM25 searches');expect(screen.getByRole('tooltip').textContent).toContain('successive read-only search tools');
  expect(agentic.getAttribute('aria-describedby')).toBe(screen.getByRole('tooltip').id);
  await userEvent.keyboard('{Escape}');expect(screen.queryByRole('tooltip')).toBeNull();expect(filters).not.toHaveBeenCalled();
});

it('uses recorded adapter metadata instead of guessing from a filename, and preserves exact series clicks',async()=>{
  const data=[{...rows[0],method:'future-hybrid-v9'},{...rows[0],id:'other-config',method:'future-hybrid-v9',configuration:'b'.repeat(64)}];
  const {open}=mount(data);await userEvent.hover(screen.getByRole('button',{name:'future-hybrid-v9',exact:true}));
  expect(screen.getByRole('tooltip').textContent).toContain('BM25 keyword matching');expect(screen.getByRole('tooltip').textContent).not.toContain('multiplicative');
  await userEvent.click(within(screen.getByTestId('chart-series')).getAllByRole('button')[1]);
  expect(open).toHaveBeenCalledWith(expect.objectContaining({method:'future-hybrid-v9',configuration:'b'.repeat(64)}));
  expect(methodDescription([{...seed,sourceMethod:'constructor'}]).search).toContain('not documented');
  expect(methodDescription([{...seed,sourceMethod:'unknown'}]).search).toContain('not documented');
  expect(methodDescription([rows[0],rows[1]]).search).toContain('Multiple recorded');
});

it('keeps unknown future methods visible with missing quality and escapes their Plotly hover labels',()=>{
  mount([{...seed,method:'future-<hybrid>',sourceMethod:'unknown',scores:{...seed.scores,answer_correctness:null}}]);
  expect(screen.getByRole('button',{name:'future-<hybrid>',exact:true})).toBeTruthy();
  expect(traces()[0].hovertemplate).toContain('future-&lt;hybrid&gt;');expect(traces()[0].hovertemplate).toContain('not documented');expect(traces()[0].y).toEqual([null]);
});
