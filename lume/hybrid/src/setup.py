#!/usr/bin/env python3
"""Run the shared one-pass ingestion and configure both methods."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parents[2]/"semantic-search/src/setup.py"),run_name="__main__")
