#!/usr/bin/env python3
"""Explicit future launcher; methods run sequentially with concurrent questions."""
import argparse,subprocess,sys
import runtime as rt

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--method',choices=rt.METHODS,action='append')
    p.add_argument('--batch-size','--concurrency',dest='batch_size',type=int,default=5)
    p.add_argument('--model',action='append');p.add_argument('--dry-run',action='store_true')
    p.add_argument('--judge',action='store_true',help='After all generation succeeds, explicitly run the shared judge for these new methods')
    args=p.parse_args()
    if not 1<=args.batch_size<=10:p.error('batch-size must be 1..10')
    if args.judge and args.dry_run:p.error('--judge cannot be combined with --dry-run')
    methods=args.method or rt.METHODS
    for method in methods:
        command=[sys.executable,str(rt.REPO/'lume'/method/'src/eval.py'),'--batch-size',str(args.batch_size),'--defer-metadata']
        for model in args.model or []:command+=['--model',model]
        if args.dry_run:command+=['--dry-run']
        subprocess.run(command,check=True)
    if args.dry_run:return
    for method in methods:
        command=[sys.executable,str(rt.REPO/'lume'/method/'src/eval.py'),'--refresh-metadata']
        for model in args.model or []:command+=['--model',model]
        subprocess.run(command,check=True)
    if args.judge:
        for method in methods:
            subprocess.run([sys.executable,str(rt.REPO/'judge/eval.py'),method,'--mode','concurrent','--concurrency',str(args.batch_size)],check=True)
if __name__=='__main__':main()
