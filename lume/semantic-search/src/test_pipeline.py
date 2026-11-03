"""Offline paid-work safeguards and actual native search on an isolated fixture."""
import json, math, sqlite3, struct, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import setup as s

def vec(a,b):return struct.pack('<'+'f'*s.DIMS,a,b,*([0.]*(s.DIMS-2)))

class FakeEmbedding:
    calls=0
    def request(self,texts,batch_id):
        self.calls+=1
        return [vec(1,0) for _ in texts],{'model':'text-embedding-3-small','usage':{'prompt_tokens':len(texts),'cost':0.00001}}

class PipelineTests(unittest.TestCase):
    def test_pause_keeps_inflight_response_and_prevents_new_api_calls(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s,'SHARED',Path(d)), patch.object(s,'STOP',__import__('threading').Event()):
            fake=FakeEmbedding();original=fake.request
            def request(texts,batch_id):
                result=original(texts,batch_id);s.STOP.set();return result
            fake.request=request
            s.batch_cache(fake,['body'],['source'],Path(d)/'done.bin')
            self.assertTrue((Path(d)/'done.json').exists())
            with self.assertRaises(s.IngestionPaused):s.batch_cache(fake,['other'],['new'],Path(d)/'new.bin')
            s.STOP.clear();s.batch_cache(fake,['body'],['source'],Path(d)/'done.bin')
            self.assertEqual(fake.calls,1)

    def test_memory_wait_recovers_without_lowering_native_cap(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s,'SHARED',Path(d)), patch.object(s,'available_memory_kib',side_effect=[1024*1024,3000*1024]), patch.object(s.time,'sleep') as sleep:
            command=s.limited_command(['native','validate'],2048)
            sleep.assert_called_once_with(15)
            self.assertIn('--as=2147483648',command)
            self.assertFalse(list(Path(d).glob('resource-wait-*.json')))

    def test_resume_cache_makes_no_new_request_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as d, patch.object(s,'SHARED',Path(d)):
            p=Path(d)/'batch.bin';fake=FakeEmbedding()
            s.batch_cache(fake,['body'],['source'],p)
            s.batch_cache(fake,['body'],['source'],p)
            self.assertEqual(fake.calls,1)
            with self.assertRaises(ValueError):s.batch_cache(fake,['different'],['source'],p)
            p.write_bytes(b'bad')
            with self.assertRaises(ValueError):s.batch_cache(fake,['body'],['source'],p)

    def test_query_text_uses_no_cutoff_syntax(self):
        self.assertEqual(s.clean_query('What is ABC\u2019s 2025 revenue?'),'What is ABC s 2025 revenue')

    def test_native_cosine_hybrid_cutoff_and_missing_query_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);corpus=root/'corpus';corpus.mkdir();index=root/'index';index.mkdir()
            for name,body in [('a','profit profit profit'),('b','quarterly earnings sales'),('c','profit forecast')]:
                (corpus/(name+'.txt')).write_text(body+'\n')
            (corpus/'lume.schema.json').write_text(json.dumps({'filing_date':'integer'}))
            (corpus/'lume.meta.jsonl').write_text(''.join(json.dumps({'path':n+'.txt','fields':{'filing_date':20270101 if n=='c' else 20250101}})+'\n' for n in ('a','b','c')))
            subprocess.run([str(s.BIN),'index',str(corpus),'--db',str(index)],env=s.runtime_env(),check=True,capture_output=True)
            desc=root/'desc.jsonl';s.native('describe',index,desc)
            rows=[json.loads(l) for l in desc.read_text().splitlines()]
            ids=[r['id'] for r in rows];p=root/'batch.bin'
            values=[vec(0.2,math.sqrt(0.96)) if Path(r['file']).name=='a.txt' else vec(1,0) for r in rows]
            p.write_bytes(b''.join(values));s.save(p.with_suffix('.json'),{'ids':ids})
            s.write_vectors(index/'local-vectors.bin',ids,[p],{'profit':vec(1,0)})
            self.assertEqual(json.loads(s.native('validate',index))['chunks'],3)
            old=s.REPO/'lume/bm25/src/native/target/release/lume-bm25-bounded'
            stats=root/'stats.json';subprocess.run([str(old),'stats',str(index),str(stats)],check=True,capture_output=True)
            st=json.loads(stats.read_text());terms={}
            for name,col in [('title_dfs',0),('body_dfs',1)]:
                for word,df in st[name].items():terms.setdefault(word,[0,0])[col]=df
            s.save(root/'global.json',{'num_docs':3,'avg_title_len':st['title_length_sum']/3,'avg_body_len':st['body_length_sum']/3,'terms':terms})
            s.save(root/'filing-dates.json',{'a.txt':20250101,'b.txt':20250101,'c.txt':20270101})
            queries=root/'queries.json';s.save(queries,[{'text':'profit','cutoff':20251231}])
            config={'global_stats':'global.json','shards':[{'index':'index'}],'technique':'semantic-search'}
            s.save(root/'config.json',config)
            pure=json.loads(s.native('search-batch',root/'config.json',queries,'10'))['results'][0]['hits']
            self.assertEqual([Path(h['file']).name for h in pure],['b.txt','a.txt'])
            self.assertAlmostEqual(pure[0]['score'],1.)
            config['technique']='hybrid';s.save(root/'config.json',config)
            hybrid=json.loads(s.native('search-batch',root/'config.json',queries,'10'))['results'][0]['hits']
            self.assertEqual({Path(h['file']).name for h in hybrid},{'a.txt','b.txt'})
            for hit in hybrid:
                scores=hit['scores'];expected=scores['bm25']*(1+0.5*scores['cosine']) if scores['bm25']>0 else scores['cosine']
                self.assertAlmostEqual(expected,hit['score'])
            s.save(queries,[{'text':'not cached','cutoff':20251231}])
            with self.assertRaises(RuntimeError):s.native('search-batch',root/'config.json',queries,'10')

if __name__=='__main__':unittest.main()
