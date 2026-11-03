import type {Evaluation,Group} from './types';
import {percent} from './format';

// Descriptions follow recorded adapter identities, never guesses from filenames.
// Discovery remains data-driven; unfamiliar adapters get an explicit fallback.
export function methodDescription(rows:Evaluation[]):{search:string;sent:string;steps?:string[]} {
  const sources=[...new Set(rows.map(row=>row.sourceMethod))];
  const profiles:Record<string,{search:string;steps:string[];sent:string}>={
    bm25:{search:'Finds filing passages that contain the question’s important words. BM25 is a keyword relevance score.',steps:['Search SEC passages for matching words, names and financial terms.','Rank passages by how strongly those words match the question.','Use the highest-ranked passages to write the answer.'],sent:'The question and top retrieved SEC passages with numbered citation markers.'},
    agentic:{search:'Lets the answering model decide what to search for, instead of using only one fixed search.',steps:['The LLM issues and refines BM25 searches over SEC filings.','It reads the returned passages and can search again for missing information.','It writes an answer from the evidence collected within the search and token limits.'],sent:'The question and passages returned by successive read-only search tools.'},
    'semantic-search':{search:'Finds passages with a similar meaning to the question, even when they use different words.',steps:['Turn the question into an embedding: a numeric representation of its meaning.','Compare it with saved SEC passage embeddings using cosine similarity (text-embedding-3-small).','Send the top semantic matches to the answering model.'],sent:'The question and top semantic matches with numbered citation markers.'},
    hybrid:{search:'Combines keyword matches with meaning-based matches to rank SEC passages.',steps:['Score passages for both matching words (BM25) and similar meaning (embedding cosine similarity).','Combine those scores using the recorded native multiplicative fusion: BM25 × (1 + 0.5 × cosine), with a semantic fallback.','Send the highest-ranked combined results to the answering model.'],sent:'The question and top passages from the combined ranking, with numbered citation markers.'},
    'hybrid-rerank':{search:'Searches broadly with hybrid retrieval, then checks which candidate passages best answer the question.',steps:['Use keyword and meaning-based search together to collect 50 candidates.','A local cross-encoder reads the question and each candidate together and gives each pair a relevance score.','Reorder the candidates using those scores and keep the best ten passages.'],sent:'The question and ten reranked SEC passages with numbered citation markers. The reranker is a local MS MARCO MiniLM model.'},
    'semantic-rerank':{search:'Finds passages by meaning, then uses a second model to check their relevance more closely.',steps:['Use saved passage embeddings to retrieve 50 candidates by cosine similarity.','A local cross-encoder reads the question and each passage together to judge relevance.','Reorder the candidates and keep the best ten passages.'],sent:'The question and ten reranked SEC passages with numbered citation markers. The reranker is a local MS MARCO MiniLM model.'},
    rrf:{search:'Combines two search result lists by their ranks, rather than mixing their raw scores. This is reciprocal rank fusion (RRF).',steps:['Retrieve the top 50 keyword matches and top 50 meaning-based matches separately.','Give each passage a vote from each list: higher-ranked passages get more weight. A passage appearing in both lists gets both votes (equal weights, 1 / (60 + rank)).','Add the votes, sort the combined list and keep ten passages.'],sent:'The question and ten passages from the fused ranking, with numbered citation markers.'},
    'rrf-rerank':{search:'Combines keyword and meaning-based result lists, then checks the strongest candidates with a second model.',steps:['Run keyword search (BM25) and meaning-based search separately, then merge their rankings with reciprocal rank fusion (RRF).','Take the best 50 fused candidates. A local cross-encoder reads each passage together with the question to score relevance.','Sort by the new relevance scores and keep the best ten passages for the answer.'],sent:'The question and ten reranked SEC passages with numbered citation markers. The fusion votes help find candidates; the cross-encoder decides their final order.'},
    hyde:{search:'Searches using an example of what a useful answer passage might look like. HyDE means hypothetical document embeddings.',steps:['Ask the LLM to write a hypothetical SEC passage for the question. This is a search aid, not a verified answer.','Embed that hypothetical passage and search the existing SEC passage embeddings for similar meaning.','Keep ten real retrieved passages and answer the original question from those sources.'],sent:'The original question and ten retrieved SEC passages. The hypothetical passage is never supplied as evidence.'},
    'self-reflective-rag':{search:'Checks an initial answer and can do one extra evidence search before producing the final answer.',steps:['Use hybrid search to retrieve evidence and write an initial draft.','Ask the LLM to review whether the draft has enough support in those passages.','Accept the draft, or perform one extra search and revise it. The process stops after that revision.'],sent:'The question and retrieved SEC evidence for drafting and, when requested, revision. This is a bounded prompt-based workflow, not a separately trained Self-RAG model.'},
  };
  if(!rows.length)return {search:'No evaluations for the current filters.',sent:'No supplied context in this selection.'};
  if(sources.length!==1)return {search:'Multiple recorded retrieval techniques in this selection.',sent:'Context stays separate for each model and configuration.'};
  return Object.hasOwn(profiles,sources[0])?profiles[sources[0]]:{search:'Retrieval technique is not documented for this recorded adapter.',sent:'Recorded answer context; inspect a question for details.'};
}

export const methodLabel=(method:string)=>method.replace(/^lume-/, '').replaceAll('-', ' ');
export const chartPalette=['#2563eb','#c2410c','#087f5b','#9333ea','#b45309','#0891b2','#be185d','#4f46e5','#4d7c0f','#a16207'];
// Rank only unambiguous method series; never average across model/settings or
// different retrieval configurations to manufacture a method-level accuracy.
export function accuracyOrder(methods:string[],groups:Group[]) {
 const settings=new Set(groups.map(g=>{const r=g.rows[0];return JSON.stringify([g.model,r.reasoning,r.maxOutput,r.corpusHash,r.questionHash]);}));
 const comparable=settings.size<=1&&methods.every(m=>groups.filter(g=>g.method===m).length<=1);
 const scores=new Map(methods.map(m=>[m,groups.find(g=>g.method===m)?.scores.answer_correctness??null]));
 const ordered=comparable?[...methods].sort((a,b)=>{const av=scores.get(a)??null,bv=scores.get(b)??null;return av===null?(bv===null?methods.indexOf(a)-methods.indexOf(b):1):bv===null?-1:bv-av||methods.indexOf(a)-methods.indexOf(b);}):methods;
 const ranks=new Map<string,string>();let previous:number|null=null,rank=0;
 for(const [i,m] of ordered.entries()){const score=scores.get(m)??null;if(!comparable||score===null){ranks.set(m,'—');continue;}if(previous===null||Math.abs(previous-score)>1e-12)rank=i+1;ranks.set(m,String(rank));previous=score;}
 return {methods:ordered,ranks,scores,comparable};
}
export default function MethodLegend({methods,selected,onSelect,chartColor,ranks,scores,ranked}:{methods:string[];selected:string|null;onSelect:(method:string)=>void;chartColor:(method:string)=>string;ranks:Map<string,string>;scores:Map<string,number|null>;ranked:boolean}) {
  return <div className="chart-method-legend" role="group" aria-label="Chart methods">
    {methods.map(method=><button type="button" key={method} aria-label={method} aria-pressed={selected===method}
      onClick={()=>onSelect(method)} title={method}>
      <span className="chart-method-number" style={{background:chartColor(method)}} aria-hidden="true">{ranks.get(method)??'—'}</span>
      <span><span>{methodLabel(method)}</span><small>{ranked?`${percent(scores.get(method))} correctness`:'Separate model / configuration series'}</small></span>
    </button>)}
  </div>;
}
