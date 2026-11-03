"""Coalesce queued searches; one bounded native reader and sequential shards."""
from __future__ import annotations
from concurrent.futures import Future
import json, queue, sqlite3, subprocess, threading, time, uuid
from pathlib import Path
import runtime as rt

class RetrievalBatcher:
    def __init__(self,config,log,max_queries=64,wait_ms=250,stop=None):
        self.config,self.log,self.max_queries,self.wait=config,log,max_queries,wait_ms/1000
        self.stop=stop
        self.queue=queue.Queue();self.closed=False
        self.thread=threading.Thread(target=self._loop,name='native-retrieval',daemon=True);self.thread.start()
    def submit(self,text,cutoff,technique,vector=None,include_vectors=False):
        if self.closed:raise RuntimeError('Retrieval dispatcher closed')
        future=Future()
        self.queue.put(({'text':text,'cutoff':int(cutoff.replace('-','')),'technique':technique,'vector':vector,'include_vectors':include_vectors},future,time.perf_counter()))
        return future
    def close(self):
        self.closed=True;self.queue.put(None);self.thread.join()
    def _loop(self):
        while True:
            item=self.queue.get()
            if item is None:return
            batch=[item];deadline=time.monotonic()+self.wait;stop=False
            while len(batch)<self.max_queries:
                try:item=self.queue.get(timeout=max(0,deadline-time.monotonic()))
                except queue.Empty:break
                if item is None:stop=True;break
                batch.append(item)
            try:
                if self.stop is not None and self.stop.is_set():raise InterruptedError('Stopped before native search')
                results=self.execute([item[0] for item in batch])
                if len(results)!=len(batch):raise RuntimeError('Native result count mismatch')
                for (_,future,enqueued),result in zip(batch,results):
                    result[1]['retrieval_queue_and_search_time_ms']=(time.perf_counter()-enqueued)*1000
                    future.set_result(result)
            except BaseException as error:
                for _,future,_ in batch:future.set_exception(error)
            if stop:return
    def execute(self,queries):
        started=time.perf_counter();temp=rt.DB/'runtime';temp.mkdir(parents=True,exist_ok=True)
        path=temp/(uuid.uuid4().hex+'.json');path.write_text(json.dumps(queries,allow_nan=False))
        command=[rt.HELPER,'search-batch',rt.DB/'native-config.json',path,str(self.config['candidate_k'])]
        self.log.write('retrieval_request',rt.METHOD,queries=queries)
        try:
            lock_started=time.perf_counter()
            # A flock on an existing read-only descriptor changes no source file bytes.
            with rt.file_lock(rt.SHARED/'native-process.lock',readonly=True):
                wait_ms=(time.perf_counter()-lock_started)*1000
                rt.wait_for_memory(self.stop)
                result=subprocess.run(rt.limited_command(command),env=rt.runtime_env(),capture_output=True,text=True,timeout=1800)
            self.log.write('retrieval_response',rt.METHOD,returncode=result.returncode,stderr=result.stderr,stdout=result.stdout)
            if result.returncode:raise RuntimeError('Bounded native retrieval failed: '+result.stderr[-1500:])
            data=json.loads(result.stdout)['results']
        finally:path.unlink(missing_ok=True)
        output=[]
        with sqlite3.connect(f'file:{rt.SHARED / "chunks.sqlite"}?mode=ro&immutable=1',uri=True) as conn:
            conn.row_factory=sqlite3.Row
            for query,entry in zip(queries,data):
                hits=[]
                for raw in entry['hits']:
                    row=conn.execute('SELECT * FROM chunks WHERE file=? AND line=?',(Path(raw['file']).name,raw['line'])).fetchone()
                    if row is None or row['filing_date']>query['cutoff']:raise RuntimeError('Unmapped source or cutoff violation')
                    hit={**dict(row),'rank':len(hits)+1,'retrieval_score':raw['score'],'scores':raw['scores'],'retrieval_query':query['text']}
                    if query['include_vectors']:hit['_vector']=raw['vector']
                    hits.append(hit)
                output.append((hits,{'retrieval_time_ms':(time.perf_counter()-started)*1000,'retrieval_engine_time_ms':entry['search_ms'],
                    'query_scoring_time_ms':entry['query_scoring_ms'],'native_process_lock_wait_ms':wait_ms,'retrieval_batch_size':len(queries),
                    'retrieval_peak_rss_mb':entry['peak_rss_kib']/1024 if entry.get('peak_rss_kib') is not None else None,
                    'db_queries':entry['shard_queries']+len(hits),'retrieval_db_queries':entry['shard_queries'],'metadata_db_queries':len(hits),
                    'tool_calls':1,'retrieval_tool_calls':1,'documents_retrieved':len(hits),'requested_top_k':self.config['candidate_k']}))
        if len(output)!=len(queries):raise RuntimeError('Missing native batch result')
        return output
