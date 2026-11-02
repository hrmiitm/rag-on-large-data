import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,render,screen,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import fs from 'node:fs';
import path from 'node:path';
import ComparisonMatrix from '../src/ComparisonMatrix';
import {normalize} from '../scripts/normalize.mjs';
import {scoreKeys} from '../src/data.mjs';
import type {Evaluation} from '../src/types';

const fixture=JSON.parse(fs.readFileSync(path.resolve('tests/fixtures/presentation-record.json'),'utf8'));
const seed=normalize(fixture,'q-a-eval-lexical.jsonl')[0] as Evaluation;
function row(method:string,id:string,changes:Partial<Evaluation>={}):Evaluation {
  return {...seed,id,questionId:id,method,judgeStatus:'completed',scores:{answer_correctness:.8,faithfulness:.9,context_relevance:.7,answer_relevance:.6},cost:.02,latency:10,tokens:110,
    metrics:{input_tokens:100,output_tokens:10,reasoning_tokens:8,tool_calls:1,llm_api_calls:1,db_queries:43,retrieval_time_ms:20,llm_generation_time_ms:1000,retrieval_peak_rss_mb:800},...changes};
}
function mount(rows:Evaluation[],onOpen=vi.fn()) {
  render(<ComparisonMatrix rows={rows} methods={[...new Set(rows.map(r=>r.method))]} hover={null} setHover={vi.fn()} onOpen={onOpen}/>);
  return onOpen;
}
function values(label:string,table=screen.getAllByRole('table')[0]) {
  return within(within(table).getByRole('row',{name:new RegExp('^'+label)})).getAllByRole('cell').map(c=>c.textContent);
}
afterEach(cleanup);

it('puts strategies in columns and quality, cost, latency, token and coverage perspectives in rows',()=>{
  mount([
    row('lexical','q1',{cost:.01,latency:10,tokens:110,scores:{answer_correctness:.25,faithfulness:.2,context_relevance:.4,answer_relevance:.7}}),
    row('lexical','q2',{cost:.03,latency:30,tokens:310,scores:{answer_correctness:.75,faithfulness:1,context_relevance:.8,answer_relevance:.9}}),
    row('future-agentic-search','q1'),
  ]);
  expect(screen.getAllByRole('columnheader').map(c=>c.textContent)).toEqual(['Metric','lexical','future-agentic-search']);
  expect(screen.getAllByRole('rowheader').map(c=>c.textContent)).toEqual(['Answer correctness','Faithfulness','Context relevance','Answer relevance','Avg. API cost','Avg. answer latency','Avg. total tokens','Judged answers']);
  expect(values('Answer correctness')).toEqual(['50.0%','80.0%']);
  expect(values('Faithfulness')).toEqual(['60.0%','90.0%']);
  expect(values('Avg. API cost')).toEqual(['$0.0200','$0.0200']);
  expect(values('Avg. answer latency')).toEqual(['20.00 s','10.00 s']);
  expect(values('Avg. total tokens')).toEqual(['210','110']);
  expect(values('Judged answers')).toEqual(['2 / 2','1 / 1']);
});
it('keeps unavailable measurements distinct and reports the denominator for each metric',()=>{
  mount([row('lexical','q1'),row('lexical','q2',{judgeStatus:'pending',scores:Object.fromEntries(scoreKeys.map(k=>[k,null])),cost:null,latency:null,tokens:null}),row('pending-method','q1',{judgeStatus:'pending',scores:Object.fromEntries(scoreKeys.map(k=>[k,null])),cost:null,latency:null,tokens:null})]);
  expect(values('Answer correctness')).toEqual(['80.0%','Not Evaluated']);
  expect(values('Avg. API cost')).toEqual(['$0.0200','N/A']);
  expect(values('Avg. answer latency')).toEqual(['10.00 s','N/A']);
  expect(values('Judged answers')).toEqual(['1 / 2','0 / 1']);
  expect(screen.getByRole('button',{name:/^Inspect avg. api cost for lexical/}).title).toContain('Measured n=1 of 2 evaluations');
});
it('opens the exact strategy, model and configuration from any metric cell',async()=>{
  const onOpen=mount([row('lexical','q1'),row('agentic','q1',{configuration:'b'.repeat(64)})]);
  await userEvent.click(screen.getByRole('button',{name:/^Inspect avg. answer latency for agentic/}));
  expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({method:'agentic',model:seed.model,configuration:'b'.repeat(64),n:1,latency:10}));
});
it('separates models and retains multiple configuration values instead of averaging them',()=>{
  mount([row('lexical','q1'),row('lexical','q2',{configuration:'b'.repeat(64),scores:{...seed.scores,answer_correctness:.4},judgeStatus:'completed'}),row('lexical','q1',{model:'fixture/other-model',cost:.5})]);
  expect(screen.getAllByRole('table').length).toBe(2);
  const table=screen.getAllByRole('table').find(t=>t.getAttribute('aria-label')?.includes('gemini')||t.textContent?.includes('Config bbbbbbbb'))!;
  const correctness=within(table).getByRole('row',{name:/^Answer correctness/});
  expect(within(correctness).getAllByRole('button').length).toBe(2);
  expect(correctness.textContent).toContain('80.0%');
  expect(correctness.textContent).toContain('40.0%');
  expect(correctness.textContent).not.toContain('60.0%');
});
it('reveals additional recorded metrics on demand and does not add reasoning tokens twice',async()=>{
  mount([row('lexical','q1')]);
  expect(screen.queryByRole('rowheader',{name:'Avg. reasoning tokens'})).toBeNull();
  await userEvent.click(screen.getByRole('button',{name:'More metrics'}));
  expect(values('Avg. input tokens')).toEqual(['100']);
  expect(values('Avg. output tokens')).toEqual(['10']);
  expect(values('Avg. reasoning tokens')).toEqual(['8']);
  expect(values('Avg. total tokens')).toEqual(['110']);
  expect(values('Avg. DB queries')).toEqual(['43']);
  await userEvent.click(screen.getByRole('button',{name:'Fewer metrics'}));
  expect(screen.queryByRole('rowheader',{name:'Avg. reasoning tokens'})).toBeNull();
});
