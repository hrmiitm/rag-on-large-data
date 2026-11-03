import React from 'react';
import {afterEach,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,within,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import fs from 'node:fs';
import path from 'node:path';
import CategoryBreakdownTable from '../src/CategoryBreakdownTable';
import {normalize} from '../scripts/normalize.mjs';
import type {Evaluation,Question} from '../src/types';
const seed=normalize(JSON.parse(fs.readFileSync(path.resolve('tests/fixtures/presentation-record.json'),'utf8')),'q-a-eval-test.jsonl')[0] as Evaluation;
const questions:Question[]=Array.from({length:6},(_,i)=>({id:'q'+i,question:'Example financial question '+i,category:i===5?'risk_governance':'comparative_analysis',asOf:'2025-01-01'}));
const rows:Evaluation[]=[
 {...seed,id:'a1',questionId:'q0',method:'agentic',category:'comparative_analysis',judgeStatus:'completed',scores:{...seed.scores,answer_correctness:.9,faithfulness:.8},cost:10,latency:20},
 {...seed,id:'a2',questionId:'q5',method:'agentic',category:'risk_governance',judgeStatus:'completed',scores:{...seed.scores,answer_correctness:.2,faithfulness:.5},cost:2,latency:4},
 {...seed,id:'b1',questionId:'q0',method:'bm25',category:'comparative_analysis',judgeStatus:'completed',scores:{...seed.scores,answer_correctness:.4,faithfulness:.7},cost:1,latency:3},
 {...seed,id:'b2',questionId:'q5',method:'bm25',category:'risk_governance',judgeStatus:'pending',scores:{...seed.scores,answer_correctness:null,faithfulness:null},cost:null,latency:null},
];
function mount(){const onSelectCategory=vi.fn();render(<CategoryBreakdownTable rows={rows} methods={['agentic','bm25']} categories={['comparative_analysis','risk_governance']} questions={questions} onSelectCategory={onSelectCategory}/>);return onSelectCategory;}
const bodyRows=()=>screen.getAllByRole('row').slice(2);
afterEach(cleanup);
it('preserves grouped headers, badges and inspection while sorting existing rows and whole strategy column groups',async()=>{
 const inspect=mount();
 expect(screen.getByRole('button',{name:'Sort categories by agentic overall correctness'}).closest('th')?.getAttribute('colspan')).toBe('2');
 await userEvent.click(screen.getByRole('button',{name:'Sort categories by agentic cost'}));
 expect(bodyRows()[0].textContent).toContain('Risk Governance');
 await userEvent.click(screen.getByRole('button',{name:'Sort categories by agentic cost'}));
 expect(bodyRows()[0].textContent).toContain('Comparative Analysis');
 await userEvent.click(screen.getByRole('button',{name:'Sort categories by agentic cost'}));
 expect(bodyRows()[0].textContent).toContain('Comparative Analysis');
 await userEvent.click(screen.getByRole('button',{name:'Sort strategies by correctness in Comparative Analysis'}));
 const headers=screen.getAllByRole('columnheader').filter(h=>h.getAttribute('colspan')==='2');
 expect(headers.map(h=>h.textContent)).toEqual([expect.stringContaining('bm25'),expect.stringContaining('agentic')]);
 const cells=within(bodyRows()[0]).getAllByRole('cell');
 expect(cells[1].textContent).toContain('40.0% Correct');
 expect(cells[3].textContent).toContain('90.0% Correct');
 await userEvent.click(screen.getByRole('button',{name:'Explore questions in Comparative Analysis'}));
 expect(inspect).toHaveBeenCalledWith('comparative_analysis');
});
it('opens a scrollable question-only preview on hover and keeps it open while moving into the popup',async()=>{
 mount();const trigger=screen.getByRole('button',{name:'Preview questions in Comparative Analysis'});
 await userEvent.hover(trigger);
 const dialog=screen.getByRole('dialog',{name:'Questions in Comparative Analysis'});
 expect(within(dialog).getAllByRole('listitem')).toHaveLength(5);
 expect(dialog.textContent).toContain('Example financial question 0');
 expect(dialog.textContent).not.toContain('Example financial question 5');
 await userEvent.unhover(trigger);await userEvent.hover(dialog);
 fireEvent.scroll(screen.getByLabelText('Scrollable category questions'));
 expect(screen.getByRole('dialog')).toBeTruthy();
 await userEvent.keyboard('{Escape}');
 expect(screen.queryByRole('dialog')).toBeNull();
});
it('supports click and keyboard preview access and dismisses after pointer leaves',async()=>{
 mount();await userEvent.click(screen.getByRole('button',{name:'Preview questions in Risk Governance'}));
 expect(screen.getByRole('dialog').textContent).toContain('Example financial question 5');
 await userEvent.click(screen.getByRole('button',{name:'Close question preview'}));
 const trigger=screen.getByRole('button',{name:'Preview questions in Comparative Analysis'});
 trigger.focus();expect(await screen.findByRole('dialog')).toBeTruthy();
 await userEvent.hover(trigger);await userEvent.unhover(trigger);
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull());
});
it('keeps missing scores last in both sort directions',async()=>{
 mount();const sort=screen.getByRole('button',{name:'Sort categories by bm25 correctness'});
 await userEvent.click(sort);expect(bodyRows()[0].textContent).toContain('Comparative Analysis');
 await userEvent.click(sort);expect(bodyRows()[0].textContent).toContain('Comparative Analysis');
});
