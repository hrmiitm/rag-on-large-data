import array
import base64
import importlib.util
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup as s


class IngestionTests(unittest.TestCase):
    def test_base64_big_endian_and_invalid_vectors(self):
        blob = struct.pack('<1536f', 1, *([0]*1535))
        encoded = s.vector_wire(blob)
        self.assertEqual(base64.b64decode(encoded), struct.pack('>1536f',1,*([0]*1535)))
        for value in (float('nan'), float('inf'), 0):
            with self.assertRaises(ValueError):
                s.vector_wire(struct.pack('<1536f',value,*([0]*1535)))

    def test_native_vector_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'vectors.bin'
            data=bytearray(struct.pack('<8sHHIQIIII',b'LUMEVEC1',1,0,0x01020304,0,1536,1,1,0))
            for value in ('text-embedding-3-small','document','query'):
                raw=value.encode(); data.extend(struct.pack('<H',len(raw))+raw)
            data.extend(struct.pack('<I',3)+b'abc')
            vector=struct.pack('<1536f',1,*([0]*1535)); data.extend(vector)
            data.extend(struct.pack('<I',1)+b'q'+vector)
            struct.pack_into('<Q',data,16,len(data)); path.write_bytes(data)
            parsed=s.Vectors(path)
            self.assertEqual(parsed.get('abc'),vector)
            self.assertEqual(parsed.query_ids,['q'])
            parsed.close()
            path.write_bytes(data[:-1])
            with self.assertRaises(ValueError): s.Vectors(path)

    def test_metadata_and_source_text_preserved(self):
        row=dict(file='d.txt',line=26,document_id='d',source_hash='hash',shard='original.parquet',filing_date=20250113,
                 section='notes',section_start=1,section_end=100,start_char=10,end_char=15,
                 title='Company: ACME | Form: 10-Q | Filed: 20250113 | Document: d',body='a\n|b|')
        doc=s.document(row,{'id':'abc','native_shard':'shard-0000'},struct.pack('<1536f',1,*([0]*1535)))
        self.assertEqual(doc['body'],row['body'])
        self.assertEqual((doc['company'],doc['form'],doc['filing_date'],doc['chunk_id']),('ACME','10-Q','2025-01-13','d:26'))

    def test_bulk_item_errors_are_not_silently_accepted(self):
        class Client:
            def request(self,*args,**kwargs):
                return {'errors':True,'items':[{'index':{'_id':'d:1','status':400,'error':'bad mapping'}}]}
        with self.assertRaisesRegex(RuntimeError,'Permanent bulk item'):
            s.bulk(Client(),[{'chunk_id':'d:1'}])

    def test_bulk_partial_response_rejected(self):
        class Client:
            def request(self,*args,**kwargs): return {'errors':False,'items':[]}
        with self.assertRaisesRegex(ValueError,'Incomplete bulk'):
            s.bulk(Client(),[{'chunk_id':'d:1'}])

    def test_bulk_retries_only_failed_items_with_stable_ids(self):
        class Client:
            def __init__(self): self.calls=[]
            def request(self,method,path,payload,**kwargs):
                self.calls.append(payload)
                if len(self.calls)==1:
                    return {'items':[{'index':{'_id':'d:1','status':201}}, {'index':{'_id':'d:2','status':429}}]}
                return {'items':[{'index':{'_id':'d:2','status':201}}]}
        client=Client()
        with patch.object(s.time,'sleep'):
            s.bulk(client,[{'chunk_id':'d:1'},{'chunk_id':'d:2'}])
        self.assertEqual(len(client.calls),2)
        self.assertNotIn(b'd:1',client.calls[1])
        self.assertIn(b'd:2',client.calls[1])

    def test_mapping_explicit_no_inference(self):
        mapping=s.mapping({'chunks':1})
        self.assertEqual(mapping['mappings']['dynamic'],'strict')
        self.assertEqual(mapping['mappings']['properties']['embedding']['dims'],1536)
        self.assertNotIn('semantic_text',json.dumps(mapping))


if __name__ == '__main__': unittest.main()
