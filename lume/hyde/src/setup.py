#!/usr/bin/env python3
"""hyde: isolated evaluation entry point."""
import os,sys
from pathlib import Path
sys.dont_write_bytecode=True
os.environ['LUME_VARIANT']='hyde'
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'hybrid-rerank'/'runtime'/'src'))
from setup_variants import main
if __name__=='__main__':main('hyde')
