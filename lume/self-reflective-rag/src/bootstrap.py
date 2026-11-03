"""Read shared libraries, with output paths scoped to this process and method."""
from pathlib import Path
import os,sys
SRC=Path(__file__).resolve().parent
HOME=SRC.parent
REPO=HOME.parents[1]
SHARED_SRC=REPO/'lume/hybrid-rerank/runtime/src'
sys.dont_write_bytecode=True
sys.path.insert(0,str(SHARED_SRC))
# The shared runtime validates its original method names on import. Configure its
# paths only inside this new evaluator's process; no shared module file is edited.
os.environ['LUME_VARIANT']='hybrid-rerank'
import runtime as rt
rt.METHOD='self-reflective-rag';rt.HOME=HOME;rt.DB=HOME/'db'
os.environ['LUME_VARIANT']=rt.METHOD
import common as c
c.HOME=HOME;c.DB=HOME/'db';c.METHOD=rt.METHOD;c.SRC=SRC
import runner as base
from client import Client,content,embedding,metrics as api_metrics
from retrieval import RetrievalBatcher

def code_identity():
    return rt.digest({'shared':base.code_identity(),'local':{p.name:rt.sha256(p) for p in sorted(SRC.glob('*.py')) if not p.name.startswith('test_')}})
