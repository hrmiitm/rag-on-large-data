"""Run all 50 fixture questions through the real checkpoint/resume driver, no API."""
import contextlib, hashlib, json, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import patch
import engine as e

class DriverTests(unittest.TestCase):
    def test_fifty_questions_bounded_pool_schema_checkpoint_resume_and_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);src=root/'src';src.mkdir();db=root/'db';db.mkdir()
            binary=root/'bin';binary.write_text('fixture');helper=root/'helper';helper.write_text('fixture helper')
            questions=[{'id':f'q{i:03d}','question':f'What is filing {i} revenue?','as_of':'2025-06-30'} for i in range(50)]
            qfile=src/'questions.jsonl';qfile.write_text(''.join(json.dumps(q)+'\n' for q in questions))
            config={'binary_sha256':e.sha256(binary),'helper_sha256':e.sha256(helper),'technique':e.METHOD,'alpha':0,'graph':0,'questions_sha256':e.sha256(qfile),'source_sha256':'fixture-source'}
            (db/'config.json').write_text(json.dumps(config))
            # The production driver opens this read-only; retrieval itself is replaced.
            import sqlite3
            sqlite3.connect(db/'chunks.sqlite').close()
            lock=threading.Lock();counts={'active':0,'peak':0,'calls':0,'retrieval_batches':[]}
            def retrieve(qs,*unused):
                counts['retrieval_batches'].append(len(qs))
                hits=[{'file':'filing.txt','line':1,'document_id':'doc','source_hash':'hash','shard':'original','filing_date':20250101,'section':'financial','section_start':0,'section_end':20,'start_char':0,'end_char':20,'title':'Filing','body':'Revenue was 10 USD.','retrieval_score':0.8,'scores':{'cosine':0.8}}]
                return [(hits,{'retrieval_time_ms':1.,'requested_top_k':10,'retrieval_engine_time_ms':1.,'query_scoring_time_ms':1.,'retrieval_batch_size':len(qs),'tool_calls':1,'db_queries':1,'documents_retrieved':1}) for _ in qs]
            def http(base,key,path,payload,model,logger,qid,calls,kind='generation',attempts=3):
                with lock:counts['active']+=1;counts['calls']+=1;counts['peak']=max(counts['peak'],counts['active'])
                time.sleep(0.005)
                data={'id':'fixture-'+qid,'model':model,'provider':'fixture','choices':[{'message':{'role':'assistant','content':'Revenue was 10 USD [1].'},'finish_reason':'stop'}],'usage':{'prompt_tokens':20,'completion_tokens':10,'completion_tokens_details':{'reasoning_tokens':4},'cost':0.001}}
                calls.append({'call_id':'fixture-'+qid,'kind':'generation','stage':'answer','model_requested':model,'attempt':1,'request':{'url':base+path,'body':payload},'http_status':200,'response':data,'raw_response':json.dumps(data),'response_headers':{},'started_at':e.utc_now(),'ended_at':e.utc_now(),'latency_ms':5.,'error':None})
                with lock:counts['active']-=1
                return data
            replacements={'SRC':src,'DB':db,'HOME':root,'BIN':binary,'HELPER':helper}
            with contextlib.ExitStack() as stack:
                for k,v in replacements.items():stack.enter_context(patch.object(e,k,v))
                stack.enter_context(patch.object(e,'database_lock',contextlib.nullcontext))
                stack.enter_context(patch.object(e,'environment',lambda **kw:('https://fixture.invalid','fixture-key',{})))
                stack.enter_context(patch.object(e,'retrieve_batch',retrieve))
                stack.enter_context(patch.object(e,'context',lambda hits,budget:('[1] Revenue was 10 USD.',hits)))
                stack.enter_context(patch.object(e,'http_call',http))
                stack.enter_context(patch.object(e,'collect_metadata',lambda *a,**kw:0))
                with patch.object(sys,'argv',['eval.py','--batch-size','3']):e.main()
                rows=[json.loads(l) for l in (root/'q-a.jsonl').read_text().splitlines()]
                self.assertEqual(len(rows),50);self.assertEqual(counts['retrieval_batches'],[50]);self.assertEqual(counts['peak'],3)
                for r in rows:
                    e.RECORD_VALIDATOR.validate(r)
                    a=next(iter(r['answers'].values()))
                    self.assertEqual(a['metrics']['output_tokens'],10)
                    self.assertEqual(a['metrics']['reasoning_tokens'],4)
                    self.assertEqual(a['citations'][0]['chunk_id'],r['context']['chunk_ids'][0])
                    self.assertEqual(r['retrieval']['chunks'][0]['scores'],{'cosine':0.8})
                before=counts['calls']
                with patch.object(sys,'argv',['eval.py','--batch-size','3']):e.main()
                self.assertEqual(counts['calls'],before)
                with patch.object(sys,'argv',['eval.py','--batch-size','3','--fresh']):e.main()
                self.assertEqual(counts['calls'],100)
                self.assertEqual(len((root/'q-a.jsonl').read_text().splitlines()),50)

if __name__=='__main__':unittest.main()
