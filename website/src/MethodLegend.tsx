import type {Evaluation} from './types';

// Descriptions follow recorded adapter identities, never guesses from filenames.
// Discovery remains data-driven; unfamiliar adapters get an explicit fallback.
export function methodDescription(rows:Evaluation[]) {
  const sources=[...new Set(rows.map(row=>row.sourceMethod))];
  const profiles:Record<string,{search:string;sent:string}>={
    bm25:{search:'BM25 keyword matching over SEC filing chunks.',sent:'The question and top retrieved SEC passages with citation markers.'},
    agentic:{search:'The LLM issues and refines BM25 searches over SEC filings.',sent:'The question and passages returned by successive read-only search tools.'},
    'semantic-search':{search:'Cosine similarity over SEC chunks embedded with text-embedding-3-small.',sent:'The question and top semantic matches with citation markers.'},
    hybrid:{search:'BM25 keyword scores and embedding cosine similarity, using native multiplicative fusion.',sent:'The question and top passages from the combined ranking, with citation markers.'},
    'hybrid-rerank':{search:'Native hybrid retrieval selects 50 candidates, then a local MS MARCO MiniLM cross-encoder reranks them.',sent:'The question and ten reranked SEC passages with citation markers.'},
    'semantic-rerank':{search:'Cosine retrieval selects 50 candidates, then a local MS MARCO MiniLM cross-encoder reranks them.',sent:'The question and ten reranked SEC passages with citation markers.'},
    rrf:{search:'Reciprocal rank fusion combines the top 50 BM25 and top 50 semantic results with equal weights and rank constant 60.',sent:'The question and ten passages from the fused ranking, with citation markers.'},
    'rrf-rerank':{search:'Reciprocal rank fusion combines BM25 and semantic results; a local cross-encoder reranks the best 50 fused candidates.',sent:'The question and ten reranked SEC passages with citation markers.'},
    hyde:{search:'The LLM writes a hypothetical SEC passage; its embedding searches the existing semantic index.',sent:'The original question and ten retrieved SEC passages. The hypothetical passage is never supplied as evidence.'},
    'self-reflective-rag':{search:'A bounded prompt-based review checks a hybrid-grounded draft, then accepts it or requests one extra search and revision.',sent:'The question and retrieved SEC evidence for drafting and, when requested, revision. This is not a separately trained Self-RAG model.'},
  };
  if(!rows.length)return {search:'No evaluations for the current filters.',sent:'No supplied context in this selection.'};
  if(sources.length!==1)return {search:'Multiple recorded retrieval techniques in this selection.',sent:'Context stays separate for each model and configuration.'};
  return Object.hasOwn(profiles,sources[0])?profiles[sources[0]]:{search:'Retrieval technique is not documented for this recorded adapter.',sent:'Recorded answer context; inspect a question for details.'};
}

export const methodLabel=(method:string)=>method.replace(/^lume-/, '').replaceAll('-', ' ');
export const chartPalette=['#2563eb','#c2410c','#087f5b','#9333ea','#b45309','#0891b2','#be185d','#4f46e5','#4d7c0f','#a16207'];
export default function MethodLegend({methods,selected,onSelect,chartColor}:{methods:string[];selected:string|null;onSelect:(method:string)=>void;chartColor:(method:string)=>string}) {
  return <div className="chart-method-legend" role="group" aria-label="Chart methods">
    {methods.map((method,i)=><button type="button" key={method} aria-label={method} aria-pressed={selected===method}
      onClick={()=>onSelect(method)} title={method}>
      <span className="chart-method-number" style={{background:chartColor(method)}} aria-hidden="true">{i+1}</span>
      <span>{methodLabel(method)}</span>
    </button>)}
  </div>;
}
