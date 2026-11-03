import Table from './Table';
import {useMemo} from 'react';
import {mean,readable} from './data.mjs';
import {money,percent,seconds} from './format';
import type {Evaluation,Manifest,Question} from './types';

export default function CategoryBreakdownTable({
  rows,
  categories,
  methods,
  manifest,
  questions,
  onSelectCategory,
}:{
  rows:Evaluation[];
  categories:string[];
  methods:string[];
  manifest?:Manifest|null;
  questions:Question[];
  onSelectCategory:(cat:string)=>void;
}){
  const categoryStats=useMemo(()=>categories.map(category=>({
    category,
    qCount:questions.filter(q=>q.category===category).length||new Set(rows.filter(r=>r.category===category).map(r=>r.questionId)).size,
  })),[categories,rows,questions]);

  type CategoryRow=typeof categoryStats[number];
  const series=[...new Map(rows.map(r=>[JSON.stringify([r.method,r.model,r.configuration,r.reasoning,r.maxOutput,r.corpusHash,r.questionHash]),r])).values()];
  const columns:any[]=[
    {accessorKey:'category',header:'Question Category',cell:({getValue}:any)=><strong>{readable(getValue())}</strong>},
    {accessorKey:'qCount',header:'Questions'},
    ...series.flatMap(sample=>{
      const multi=series.filter(s=>s.method===sample.method).length>1;
      const name=sample.method+(multi?` · ${sample.model} · ${sample.configuration.slice(0,8)} · ${String(sample.reasoning??'N/A')} · max ${sample.maxOutput??'N/A'} · corpus ${sample.corpusHash?.slice(0,8)??'N/A'} · questions ${sample.questionHash?.slice(0,8)??'N/A'}`:'');
      const matching=(cat:string)=>rows.filter(r=>r.category===cat&&r.method===sample.method&&r.model===sample.model&&r.configuration===sample.configuration&&r.reasoning===sample.reasoning&&r.maxOutput===sample.maxOutput&&r.corpusHash===sample.corpusHash&&r.questionHash===sample.questionHash);
      return [
        {key:'correctness',label:'Correctness',value:(r:Evaluation)=>r.judgeStatus==='completed'?r.scores.answer_correctness:null,format:percent},
        {key:'faithfulness',label:'Faithfulness',value:(r:Evaluation)=>r.judgeStatus==='completed'?r.scores.faithfulness:null,format:percent},
        {key:'cost',label:'API cost',value:(r:Evaluation)=>r.cost,format:money},
        {key:'latency',label:'Latency',value:(r:Evaluation)=>r.latency,format:seconds},
      ].map(metric=>({id:JSON.stringify([name,metric.key]),header:`${name} · ${metric.label}`,accessorFn:(cat:CategoryRow)=>mean(matching(cat.category).map(metric.value)),cell:({getValue}:any)=>metric.format(getValue())}));
    }),
  ];
  return <section className="category-breakdown-section" aria-labelledby="category-breakdown-title">
    <h2 id="category-breakdown-title">Strategy Scores by Question Category</h2>
    <p className="table-note">Tap any header to sort categories. Each metric, model and configuration has its own column. Select a category to explore its questions.</p>
    <Table data={categoryStats} columns={columns} onRow={r=>onSelectCategory(r.category)} filename="category-comparison" controls={false} paginationLabel="category"/>
  </section>;

}
