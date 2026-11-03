#!/usr/bin/env python3
"""Temporarily pause a contending desktop extractor, then restore it automatically."""
import argparse
from contextlib import contextmanager
import datetime
import fcntl
import json
import os
from pathlib import Path
import signal
import threading
import time

from setup import SHARED, save


def identity(pid):
    try:
        root=Path('/proc')/str(pid)
        fields=(root/'stat').read_text().rsplit(')',1)[1].split()
        return {'name':(root/'comm').read_text().strip(),'start_ticks':fields[19],'state':fields[0]}
    except (OSError,IndexError):return None


@contextmanager
def paused_indexer(pid):
    original=identity(pid)
    if not original or original['name']!='baloo_file_extr':raise ValueError('Expected the identified desktop file extractor')
    if original['state'] in ('T','t'):raise ValueError('Extractor was already paused; leave its state alone')
    os.kill(pid,signal.SIGSTOP)
    try:yield original
    finally:
        current=identity(pid)
        if current and (current['name'],current['start_ticks'])==(original['name'],original['start_ticks']):
            os.kill(pid,signal.SIGCONT)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--indexer-pid',required=True,type=int)
    parser.add_argument('--supervisor-pid',required=True,type=int)
    parser.add_argument('--maximum-seconds',type=int,default=5400)
    args=parser.parse_args()
    if not 1<=args.maximum_seconds<=5400:parser.error('Lease must last 1..5400 seconds')
    state=json.loads((SHARED/'pipeline-state.json').read_text())
    parent=identity(args.supervisor_pid)
    cmd=Path(f'/proc/{args.supervisor_pid}/cmdline').read_bytes()
    if state['supervisor_pid']!=args.supervisor_pid or b'semantic-search/src/run_all.py' not in cmd or state['stage'] not in ('ingestion','ingestion_resume') or state['status'] not in ('running','waiting_for_gateway'):
        raise ValueError('Expected the active ingestion supervisor')
    stop=threading.Event()
    for signum in (signal.SIGTERM,signal.SIGINT):signal.signal(signum,lambda *_:stop.set())
    with (SHARED/'resource-lease.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        started=time.monotonic();record={'pid':os.getpid(),'supervisor_pid':args.supervisor_pid,'indexer_pid':args.indexer_pid,
            'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'maximum_seconds':args.maximum_seconds}
        try:
            with paused_indexer(args.indexer_pid) as original:
                record.update(status='active',original_identity=original);save(SHARED/'resource-lease.json',record)
                while not stop.wait(5):
                    state=json.loads((SHARED/'pipeline-state.json').read_text());current=identity(args.supervisor_pid)
                    if not current or current['start_ticks']!=parent['start_ticks'] or state['supervisor_pid']!=args.supervisor_pid:break
                    if state['status'] in ('paused','failed','complete') or state['stage'] not in ('ingestion','ingestion_resume'):break
                    if time.monotonic()-started>=args.maximum_seconds:break
        finally:
            record.update(status='released',released_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
            save(SHARED/'resource-lease.json',record)


if __name__=='__main__':main()
