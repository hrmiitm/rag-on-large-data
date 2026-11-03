#!/usr/bin/env python3
import os,sys
from pathlib import Path
os.environ["LUME_SEARCH_METHOD"]='semantic-search'
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"semantic-search"/"src"))
from engine import main
if __name__=="__main__":main()
