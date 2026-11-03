import {Fragment,useMemo} from 'react';
import {ArrowUpRight,Clock,DollarSign,FileCode2,Sparkles,Trophy} from 'lucide-react';
import {mean,readable} from './data.mjs';
import {color,money,percent,seconds} from './format';
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
  const methodFileMap=useMemo(()=>{
    const map=new Map<string,string>();
    if(manifest?.sources){
      for(const s of manifest.sources){
        map.set(s.method,s.file);
      }
    }
    return map;
  },[manifest]);

  const getMethodFile=(m:string)=>methodFileMap.get(m)??`q-a-eval-${m}.jsonl`;

  const categoryStats=useMemo(()=>{
    return categories.map(cat=>{
      const catQuestions=questions.filter(q=>q.category===cat);
      const qCount=catQuestions.length||new Set(rows.filter(r=>r.category===cat).map(r=>r.questionId)).size;
      const byMethod:Record<string,{
        correctness:number|null;
        faithfulness:number|null;
        cost:number|null;
        latency:number|null;
        judged:number;
        total:number;
      }>={};

      for(const m of methods){
        const matching=rows.filter(r=>r.category===cat&&r.method===m);
        const judgedMatching=matching.filter(r=>r.judgeStatus==='completed');
        const corrScores=judgedMatching.map(r=>r.scores.answer_correctness).filter((v):v is number=>v!==null);
        const faithScores=judgedMatching.map(r=>r.scores.faithfulness).filter((v):v is number=>v!==null);
        const costs=matching.map(r=>r.cost).filter((v):v is number=>v!==null);
        const latencies=matching.map(r=>r.latency).filter((v):v is number=>v!==null);

        byMethod[m]={
          correctness:corrScores.length?mean(corrScores):null,
          faithfulness:faithScores.length?mean(faithScores):null,
          cost:costs.length?mean(costs):null,
          latency:latencies.length?mean(latencies):null,
          judged:judgedMatching.length,
          total:matching.length,
        };
      }

      // Compute category leader
      let leaderText='';
      if(methods.length>=2){
        const s1=byMethod[methods[0]],s2=byMethod[methods[1]];
        if(s1?.correctness!==null&&s2?.correctness!==null){
          if(s1.correctness>s2.correctness){
            leaderText=`${methods[0]} (+${Math.round((s1.correctness-s2.correctness)*100)}%)`;
          }else if(s2.correctness>s1.correctness){
            leaderText=`${methods[1]} (+${Math.round((s2.correctness-s1.correctness)*100)}%)`;
          }else{
            leaderText='Tied in accuracy';
          }
        }else if(s1?.latency!==null&&s2?.latency!==null&&s1.latency>0&&s2.latency>0){
          if(s1.latency<s2.latency){
            leaderText=`${methods[0]} ${(s2.latency/s1.latency).toFixed(1)}x faster`;
          }else{
            leaderText=`${methods[1]} ${(s1.latency/s2.latency).toFixed(1)}x faster`;
          }
        }
      }

      return {
        category:cat,
        qCount,
        description:categoryDescription(cat),
        byMethod,
        leaderText,
      };
    });
  },[categories,methods,rows,questions]);

  return <section className="category-breakdown-section" aria-labelledby="category-breakdown-title">
    <div className="section-title-wrap">
      <div className="section-heading-content">
        <span className="eyebrow"><Sparkles size={13}/> CATEGORY BREAKDOWN</span>
        <h2 id="category-breakdown-title">Strategy Scores by Question Category</h2>
        <p className="section-subtext">Overall score and efficiency of each search strategy across distinct financial question categories.</p>
      </div>
    </div>

    <div className="matrix-scroll">
      <table className="category-breakdown-table">
        <thead>
          <tr className="matrix-header-super">
            <th className="th-cat" rowSpan={2}>Question Category</th>
            {methods.map(m=><th key={m} colSpan={2} className="th-strategy-group">
              <div className="strategy-header-box">
                <span className="file-pill mono" title={`Source file: ${getMethodFile(m)}`}>
                  <FileCode2 size={12}/> {getMethodFile(m)}
                </span>
                <div className="strategy-title">
                  <i style={{background:color(m)}}/>
                  <strong>{m}</strong>
                </div>
              </div>
            </th>)}
            {methods.length>=2&&<th className="th-leader" rowSpan={2}>Category Leader</th>}
            <th className="th-action" rowSpan={2}>Explore</th>
          </tr>
          <tr className="matrix-header-sub">
            {methods.map(m=><Fragment key={m}>
              <th className="th-col-quality">Quality (Correctness & Faithfulness)</th>
              <th className="th-col-metrics">Cost & Time Taken (Latency)</th>
            </Fragment>)}
          </tr>
        </thead>
        <tbody>
          {categoryStats.map(stat=><tr key={stat.category} className="matrix-row">
            <td className="td-category-info">
              <div className="category-cell-wrap">
                <div className="inline">
                  <strong className="category-name">{readable(stat.category)}</strong>
                  <span className="q-count-badge">{stat.qCount} questions</span>
                </div>
                <p className="category-desc">{stat.description}</p>
              </div>
            </td>

            {methods.map(m=>{
              const s=stat.byMethod[m];
              if(!s||!s.total){
                return <Fragment key={m}>
                  <td className="td-quality td-empty"><span className="unavailable">N/A</span></td>
                  <td className="td-metrics td-empty"><span className="unavailable">N/A</span></td>
                </Fragment>;
              }

              const corr=s.correctness,faith=s.faithfulness;
              return <Fragment key={m}>
                <td className="td-quality">
                  <div className="quality-cell-content">
                    {corr!==null?<span className={`score-badge ${corr>=0.8?'score-high':corr>=0.5?'score-mid':'score-low'}`}>{percent(corr)} Correct</span>:<span className="score-badge score-pending">{s.judged}/{s.total} Judged</span>}
                    {faith!==null&&<span className="sub-stat">Faith: <b>{percent(faith)}</b></span>}
                  </div>
                </td>
                <td className="td-metrics">
                  <div className="metrics-cell-content">
                    <div className="metric-pill latency-pill" title={`Avg Latency: ${seconds(s.latency)}`}>
                      <Clock size={12}/>
                      <span>{seconds(s.latency)}</span>
                    </div>
                    <div className="metric-pill cost-pill" title={`Avg Serving Cost: ${money(s.cost)}`}>
                      <DollarSign size={12}/>
                      <span>{money(s.cost)}</span>
                    </div>
                  </div>
                </td>
              </Fragment>;
            })}

            {methods.length>=2&&<td className="td-advantage">
              {stat.leaderText?<span className="adv-pill score-adv">
                <Trophy size={11}/> {stat.leaderText}
              </span>:<span className="unavailable">—</span>}
            </td>}

            <td className="td-action">
              <button
                className="inspect-btn"
                onClick={()=>onSelectCategory(stat.category)}
                aria-label={`Explore questions in ${readable(stat.category)}`}
                title={`Filter questions to ${readable(stat.category)}`}
              >
                Inspect <ArrowUpRight size={13}/>
              </button>
            </td>
          </tr>)}
        </tbody>
      </table>
    </div>
  </section>;
}

function categoryDescription(c:string){
  if(c.includes('multi_document'))return 'Connect evidence across separate filings.';
  if(c.includes('comparative'))return 'Align and compare financial disclosures.';
  if(c.includes('reasoning'))return 'Reason from reported financial evidence.';
  if(c.includes('risk'))return 'Interpret risk and governance disclosures.';
  if(c.includes('lookup'))return 'Locate a specific disclosed fact.';
  return 'Explore reference questions in this category.';
}
