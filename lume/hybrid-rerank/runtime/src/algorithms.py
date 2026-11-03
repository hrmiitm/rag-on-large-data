"""Deterministic fusion, decomposition merge and diversity selection."""
from __future__ import annotations
import copy, math
from common import chunk_id

def union(ranked_lists,labels):
    rows={}
    for hits,label in zip(ranked_lists,labels):
        for rank,hit in enumerate(hits,1):
            cid=chunk_id(hit)
            if cid not in rows:
                rows[cid]=copy.deepcopy(hit);rows[cid]['occurrences']=[];rows[cid]['ranks']={}
            row=rows[cid];row['ranks'][label]=rank
            row['occurrences'].append({'query_id':label,'rank':rank,'scores':dict(hit.get('scores',{}))})
            for name,value in hit.get('scores',{}).items():
                if value is not None:row.setdefault('scores',{})[name]=value
    return rows

def rrf(ranked_lists,labels,constant=60):
    if constant<=0:raise ValueError('RRF constant must be positive')
    rows=union(ranked_lists,labels)
    for row in rows.values():
        score=sum(1/(constant+rank) for rank in row['ranks'].values())
        row.setdefault('scores',{})['rrf']=score;row['retrieval_score']=score
    return sorted(rows.values(),key=lambda h:(-h['scores']['rrf'],chunk_id(h)))

def balanced_merge(ranked_lists,labels):
    """Round-robin subquestions before original query; retain every unique candidate."""
    rows=union(ranked_lists,labels);order=[];seen=set()
    for rank in range(max(map(len,ranked_lists),default=0)):
        for hits in ranked_lists:
            if rank<len(hits):
                cid=chunk_id(hits[rank])
                if cid not in seen:order.append(rows[cid]);seen.add(cid)
    for rank,row in enumerate(order,1):row['scores']['decomposition_selection_rank']=rank
    return order

def cosine(a,b):
    if len(a)!=len(b) or not a:raise ValueError('Vector dimensions differ')
    dot=sum(x*y for x,y in zip(a,b));na=sum(x*x for x in a);nb=sum(y*y for y in b)
    if not all(math.isfinite(x) for x in (dot,na,nb)) or na<=0 or nb<=0:raise ValueError('Invalid vector')
    return dot/math.sqrt(na*nb)

def mmr(hits,k,weight=.7):
    """Rank-normalized hybrid relevance; vector cosine measures redundancy."""
    if not 0<=weight<=1:raise ValueError('MMR weight outside [0,1]')
    rows=copy.deepcopy(hits);chosen=[];n=len(rows)
    for rank,row in enumerate(rows):
        row['_rel']=1-rank/max(1,n-1)
        if not row.get('_vector'):raise ValueError('MMR candidate vector missing')
    while rows and len(chosen)<k:
        def value(h):
            redundancy=max((cosine(h['_vector'],s['_vector']) for s in chosen),default=0.)
            return weight*h['_rel']-(1-weight)*redundancy
        best=min(rows,key=lambda h:(-value(h),chunk_id(h)))
        best['scores']['mmr']=value(best);chosen.append(best);rows.remove(best)
    for row in chosen+rows:row.pop('_rel',None)
    return chosen+rows
