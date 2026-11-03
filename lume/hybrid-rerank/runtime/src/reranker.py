"""CPU ONNX cross-encoder with complete, overlapping passage token windows."""
from __future__ import annotations
import json, math, threading, time
from pathlib import Path
import runtime as rt
MODEL='cross-encoder/ms-marco-MiniLM-L6-v2'

class CrossEncoder:
    def __init__(self,model_dir,batch_size=8,threads=2):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np=np;self.batch_size=batch_size;self.lock=threading.Lock()
        path=Path(model_dir)
        self.manifest=json.loads((path/'manifest.json').read_text())
        for name,expected in self.manifest['files'].items():
            if rt.sha256(path/name)!=expected:raise ValueError('Reranker asset hash mismatch: '+name)
        self.tokenizer=Tokenizer.from_file(str(path/'tokenizer.json'))
        self.tokenizer.no_truncation();self.tokenizer.no_padding()
        options=ort.SessionOptions();options.intra_op_num_threads=threads;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        self.inputs={i.name for i in self.session.get_inputs()}
        self.cls=self.tokenizer.token_to_id('[CLS]');self.sep=self.tokenizer.token_to_id('[SEP]');self.pad=self.tokenizer.token_to_id('[PAD]')
        if None in (self.cls,self.sep,self.pad):raise ValueError('Expected BERT tokenizer special tokens')
    def windows(self,query,passage,max_length=512,overlap=64):
        q=self.tokenizer.encode(query,add_special_tokens=False).ids
        if len(q)>128:raise ValueError('Question exceeds 128 reranker tokens; refusing silent truncation')
        body=self.tokenizer.encode(passage,add_special_tokens=False).ids
        capacity=max_length-len(q)-3
        return [(q,body[start:start+capacity]) for start in window_starts(len(body),capacity,overlap)]
    def score(self,query,hits):
        started=time.perf_counter();entries=[]
        for index,hit in enumerate(hits):
            for q,p in self.windows(query,hit['title']+'\n'+hit['body']):entries.append((index,q,p))
        scores=[[] for _ in hits]
        with self.lock,rt.file_lock(rt.SRC.parent/'db/reranker.lock'):
            for offset in range(0,len(entries),self.batch_size):
                batch=entries[offset:offset+self.batch_size];width=max(len(q)+len(p)+3 for _,q,p in batch)
                ids=[];masks=[];segments=[]
                for _,q,p in batch:
                    seq=[self.cls]+q+[self.sep]+p+[self.sep];padding=width-len(seq)
                    ids.append(seq+[self.pad]*padding);masks.append([1]*len(seq)+[0]*padding)
                    segments.append([0]*(len(q)+2)+[1]*(len(p)+1)+[0]*padding)
                feed={k:self.np.asarray(v,dtype=self.np.int64) for k,v in {'input_ids':ids,'attention_mask':masks,'token_type_ids':segments}.items() if k in self.inputs}
                logits=self.session.run(None,feed)[0].reshape(-1).tolist()
                if len(logits)!=len(batch) or not all(math.isfinite(x) for x in logits):raise ValueError('Invalid cross-encoder scores')
                for (i,_,_),score in zip(batch,logits):scores[i].append(score)
        for hit,windows in zip(hits,scores):
            hit['scores']['cross_encoder']=max(windows);hit['reranker_windows']={'aggregation':'max_logit','scores':windows,'count':len(windows)}
        from common import chunk_id
        ranked=sorted(hits,key=lambda h:(-h['scores']['cross_encoder'],chunk_id(h)))
        return ranked,{'reranking_time_ms':(time.perf_counter()-started)*1000,'reranker_pairs':len(hits),'reranker_windows':len(entries),'reranker_api_calls':0,'reranker_model':self.manifest['model'],'reranker_revision':self.manifest['revision']}

def window_starts(length,capacity,overlap):
    if capacity<=overlap or overlap<0:raise ValueError('Invalid window overlap')
    starts=[0]
    while starts[-1]+capacity<length:starts.append(starts[-1]+capacity-overlap)
    return starts
