#!/usr/bin/env python3
"""hybrid-rerank: isolated evaluation entry point."""
import os,sys
from pathlib import Path
sys.dont_write_bytecode=True
os.environ['LUME_VARIANT']='hybrid-rerank'
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'hybrid-rerank'/'runtime'/'src'))
from runner import main
if __name__=='__main__':main()
