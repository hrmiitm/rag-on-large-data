#!/usr/bin/env python3
"""Build the isolated adapter from this workspace's pinned Lume source, offline."""
import os,shutil,subprocess
from pathlib import Path
import runtime as rt

def main():
    original=rt.REPO/'lume/semantic-search/src'
    source=original/'native/vendor/lume';target=rt.SRC/'native/vendor/lume'
    if not source.exists():raise SystemExit('Restore the pinned Lume source specified in README first')
    if not target.exists():
        target.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['cp','-a','--reflink=auto',str(source),str(target)],check=True)
    file=target/'src/local_vectors.rs';text=file.read_text();addition=(rt.SRC/'native/query-adapter.rs.inc').read_text()
    if addition not in text:
        if 'pub fn inject_query' in text:raise ValueError('Unexpected pre-existing vector adapter')
        needle='    pub fn search(\n'
        if text.count(needle)!=1:raise ValueError('Pinned LocalVectors source layout changed')
        file.write_text(text.replace(needle,addition+needle))
    cargo=rt.SRC/'.cargo'
    if not cargo.exists():subprocess.run(['cp','-a','--reflink=auto',str(original/'.cargo'),str(cargo)],check=True)
    env={**os.environ,'CARGO_HOME':str(cargo),'RUSTUP_HOME':str(original/'.rustup'),'CARGO_BUILD_JOBS':'1'}
    subprocess.run([str(cargo/'bin/cargo'),'build','--offline','--release','--manifest-path',str(rt.SRC/'native/Cargo.toml')],env=env,check=True)
if __name__=='__main__':main()
