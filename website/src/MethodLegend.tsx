import type {Evaluation,Group} from './types';
import {money,percent,seconds} from './format';
import {groupRows,matchedComparison,mean,numeric} from './data.mjs';

function methodComparisons(rows:Evaluation[],comparisonRows:Evaluation[]):string[] {
 const selected=groupRows(rows),observations:string[]=[];
 if(selected.length!==1)return observations;
 for(const other of groupRows(comparisonRows).filter(g=>g.method!==selected[0].method&&['bm25','agentic','elasticsearch-agentic'].includes(g.rows[0].sourceMethod))) {
  const matched=matchedComparison([selected[0],other]);if(!matched.n)continue;
  const [a,b]=matched.groups;
  observations.push(`${matched.n} matched questions vs. ${methodLabel(b.method)} (${b.configuration.slice(0,8)}): correctness ${percent(a.scores.answer_correctness)} vs. ${percent(b.scores.answer_correctness)}; average answer time ${seconds(a.latency)} vs. ${seconds(b.latency)}; serving cost ${money(a.cost)} vs. ${money(b.cost)} per answer.`);
 }
 return observations;
}

// Descriptions follow recorded adapter identities, never guesses from filenames.
// Discovery remains data-driven; unfamiliar adapters get an explicit fallback.
export function methodDescription(rows:Evaluation[],comparisonRows:Evaluation[]=[]):{search:string;sent:string;steps?:string[];comparison?:string;performance?:string;observations?:string[]} {
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
  if(sources[0]==='elasticsearch-agentic') {
    const observations=methodComparisons(rows,comparisonRows);
    const retrieval=mean(rows.map(r=>numeric(r.metrics.retrieval_time_ms))),latency=mean(rows.map(r=>r.latency));
    return {
      search:'An LLM researches SEC filings using Elasticsearch: keyword search plus meaning-based search over the existing passage embeddings.',
      steps:[
        'The LLM chooses a search query, keyword or hybrid mode, and company/form filters. Every search respects the question’s filing-date cutoff.',
        'BM25 finds matching words; approximate vector search finds similar meaning. Hybrid merges the two top-50 lists with reciprocal rank fusion (RRF), then returns five passages. It reuses the original question’s saved vector; rewritten queries change only keyword search.',
        'The LLM can refine searches and read neighbouring passages to complete a table or explanation, then calculate and cite its answer within six model turns.',
      ],
      sent:'The question and passages returned by its search/read tools, with numbered citations. Gold answers are excluded; no new embeddings are created.',
      comparison:'It shares BM25 with keyword methods and rank fusion with RRF. Unlike one-shot RRF, the LLM can search again and read neighbours. Lume agentic uses keyword search; this agent adds filtered hybrid search. Elasticsearch uses approximate vector lookup, while the Lume semantic baseline scans vectors exactly. There is no cross-encoder reranker.',
      performance:`The persistent index avoids reloading Lume’s 33 shards for each search; company filters narrow the work. Recorded retrieval averages ${seconds(retrieval===null?null:retrieval/1000)} per question, versus ${seconds(latency)} to prepare an answer (available timings only). Most waiting is in LLM calls. Serving spend pays for all model turns and evidence tokens; judging is separate and excluded from chart cost. Filters, repeated searches and neighbour reads can help find better evidence, but these runs compare whole pipelines and do not isolate the engine’s effect.`,
      observations,
    };
  }
  if(Object.hasOwn(profiles,sources[0])) {
    const notes:Record<string,{comparison:string;cost:string}>={
      bm25:{comparison:'This is keyword-only retrieval, followed by one answering LLM call. It has no semantic vector search, query-planning agent or reranker. Exact names and financial terms help; different wording can hide useful passages.',cost:'Serving spend is mainly the final answering LLM and its evidence tokens. Local keyword search has no embedding or reranking API charge.'},
      agentic:{comparison:'It builds on BM25: the LLM can decompose the question and search again. Unlike Elasticsearch agentic search, its tools use lexical retrieval without vector fusion or neighbouring-passage reads. More searches can fill evidence gaps but can also exhaust the turn budget.',cost:'Multiple LLM turns and repeated evidence tokens add serving cost and waiting time. Native shards load sequentially; batched searches share that work. No embedding or reranking API is used.'},
      'semantic-search':{comparison:'It uses exact cosine similarity over all candidate vectors, with no keyword score. This can find similar meanings but can miss exact company names or numbers. Unlike Elasticsearch’s approximate lookup, the Lume baseline scans vectors exactly.',cost:'Local exact vector scans and shard loading take time. Document vectors and the original question cache are reused; cache setup is separate from per-answer serving cost. The answering LLM receives one retrieved context.'},
      hybrid:{comparison:'This combines BM25 and cosine scores using multiplicative fusion. RRF instead combines independent result ranks. There is no iterative LLM search or cross-encoder reranker; stronger keyword matches still influence the blend.',cost:'Both lexical and exact vector retrieval run locally, using saved embeddings. Serving API spend is mainly one answering LLM call and its context; local scans and shard loading still contribute latency.'},
      'hybrid-rerank':{comparison:'This adds a cross-encoder to the multiplicative hybrid candidate search. The reranker reads each question/passage pair more closely, but it cannot recover relevant evidence missing from the candidate list. It is a general MS MARCO MiniLM model, not a finance-specific judge.',cost:'Local CPU reranking and passage windows add time and RAM, with no reranking API charge. Existing vectors are reused. The final LLM receives ten selected passages rather than all candidates.'},
      'semantic-rerank':{comparison:'This adds a cross-encoder to exact semantic retrieval. There is no BM25 branch; unlike hybrid reranking, candidate discovery depends only on meaning-based matches. Better ordering does not guarantee better financial answers.',cost:'Exact vector scans and local CPU reranking add latency. There is no reranking API charge, and saved document/question vectors are reused. API spend is mainly the final answer and its context.'},
      rrf:{comparison:'This combines independent BM25 and exact cosine rankings with RRF. Unlike multiplicative hybrid, it uses rank votes rather than raw-score magnitudes. It is a fixed retrieval pass, with no LLM-directed follow-up search or cross-encoder.',cost:'Two local candidate lists and exact vector scans contribute retrieval time. Saved vectors are reused; the answering LLM is the main serving API cost. Fusion itself has no API charge.'},
      'rrf-rerank':{comparison:'This adds a cross-encoder after BM25/cosine RRF. Rank fusion finds candidates; the reranker decides the final order. Unlike plain RRF, it reads question/passage pairs, but there is still no agent loop.',cost:'The two searches plus local CPU reranking add time. Reranking has no API charge; serving spend mainly covers the final answering LLM and its selected evidence.'},
      hyde:{comparison:'Unlike ordinary semantic search, HyDE embeds an LLM-written hypothetical passage instead of only the question. This can bridge vocabulary gaps, but invented assumptions can steer retrieval away from the right filing. Only real SEC passages support the final answer.',cost:'A hypothesis-generation LLM call and its query embedding add serving overhead before the final answering call. Existing document embeddings are reused. Hypothesis preparation costs and time belong to this method’s recorded serving metrics.'},
      'self-reflective-rag':{comparison:'This extends hybrid RAG with an LLM review of its draft and at most one extra search/revision. It is a bounded prompt workflow, not a separately trained Self-RAG model or an open-ended search agent. Review can spot missing support but can also accept an incorrect draft.',cost:'Drafting, review and optional revision add LLM calls and repeated context tokens. Reused embeddings avoid a new document embedding pass. The recorded latency and serving spend include these stages.'},
    };
    const note=notes[sources[0]],retrieval=mean(rows.map(r=>numeric(r.metrics.retrieval_time_ms))),latency=mean(rows.map(r=>r.latency)),cost=mean(rows.map(r=>r.cost));
    return {...profiles[sources[0]],comparison:note.comparison,performance:`${note.cost} Recorded averages for the current filters: local retrieval ${seconds(retrieval===null?null:retrieval/1000)} per question; answer-ready time ${seconds(latency)}; serving API cost ${money(cost)} per answer. Each average uses its available measurements. Judging is separate and excluded from serving cost. These are observed pipeline results, not an isolated causal test.`,observations:methodComparisons(rows,comparisonRows)};
  }
  const retrievers=[...new Set(rows.flatMap(r=>r.retrievalProfile?.retriever?[r.retrievalProfile.retriever]:[]))];
  const modes=[...new Set(rows.flatMap(r=>r.retrievalProfile?.modes??[]))];
  const signals=[...new Set(rows.flatMap(r=>r.retrievalProfile?.signals??[]))];
  return {search:retrievers.length||modes.length||signals.length?[
    retrievers.length?`Recorded retriever: ${retrievers.join(', ')}.`:'',
    modes.length?`Recorded search modes: ${modes.join(', ')}.`:'',
    signals.length?`Recorded ranking signals: ${signals.join(', ')}.`:'',
  ].filter(Boolean).join(' '):'Retrieval technique is not documented for this recorded adapter.',sent:'Recorded answer context; inspect a question for its supplied evidence and citations.'};
}

export const methodLabel=(method:string)=>method.replace(/^lume-/, '').replaceAll('-', ' ');
export const chartPalette=['#2563eb','#c2410c','#087f5b','#9333ea','#b45309','#0891b2','#be185d','#4f46e5','#4d7c0f','#a16207'];
// Extend the palette for any number of discovered methods without wrapping at ten.
export function methodColor(method:string,methods:string[]) {
 const index=Math.max(0,methods.indexOf(method));
 return chartPalette[index]??`hsl(${((index-chartPalette.length)*137.508+205)%360}, 65%, 36%)`;
}
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
