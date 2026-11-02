"""Canonical SEC section rule. Local extraction only; never submits embeddings.

python scripts/prepare_sec_sections.py --output /tmp/sec_sections.parquet
Dependencies: duckdb, tiktoken. Existing source files are never modified.
"""
import argparse
import ast
from decimal import Decimal, ROUND_HALF_UP
from concurrent.futures import ThreadPoolExecutor
import hashlib
import html
import json
import math
from pathlib import Path
import re
import tempfile

RULE_VERSION = 'sec-financial-sections-v1'
_ITEM = re.compile(r'^\s*(?:part\s+[ivx]+[. :–—-]*)?item\s+(\d{1,2}[a-c]?)(?:\b|[.:])', re.I)
_TAG = re.compile(r'<[^>]*>')
_FIN = re.compile(r'^(?:(?:unaudited|audited|condensed|consolidated|combined|financial|interim|index\s+to|statements?\s+of|balance\s+sheets?|and|the|company|of)\s+)*.*(?:financial\s+statements|(?:consolidated|combined)\s+(?:balance\s+sheets|statements))',re.I)


def clean(line):
    line = _TAG.sub(' ', html.unescape(line))
    line = re.sub(r'consolidated\s+condensed', 'Consolidated', line, flags=re.I)
    return re.sub(r'\s+', ' ', re.sub(r'[*_#|`\[\]]', ' ', line)).strip()


def extract_sections(body, form):
    """Return original-text ranges; skip TOC links and fail closed on unknown headings.

    10-K: Item 7 MD&A; Item 8 financials. 10-Q: Part I Items 1 and 2.
    Additional standalone financial blocks cover statements incorporated under Item 15.
    No whole-filing fallback and no arbitrary first-N-token truncation.
    """
    lines=[];offset=0
    for raw in body.splitlines(keepends=True):
        low=raw.lower()
        if any(w in low for w in ('item','management','financial','consolidated','combined','exhibit','signature','part ii','schedule','risk factors','controls and procedures','other key')):
            if len(raw)<900 and '](#' not in raw:
                lines.append((offset,raw,clean(raw)))
        offset+=len(raw)
    items=[];ends=[];standalone=[];bare=[]
    for pos,raw,s in lines:
        m=_ITEM.match(s)
        if m and len(s)<400:
            # A bare Item heading may put its title on the following lines.
            title=s
            if len(s)<24:
                title=clean(body[pos:pos+600].split('\n\n\n')[0])[:500]
            items.append((pos,m.group(1).upper(),title))
        if re.match(r'^\s*##\s+Exhibit\b',raw,re.I) or re.match(r'^SIGNATURES?\s*$',s,re.I):ends.append(pos)
        if not m and not raw.lstrip().startswith('|') and len(s)<200:
            if re.match(r"^management[’']?s discussion and analysis(?:\s|$)",s,re.I):bare.append((pos,'md_and_a'))
            if re.match(r'^financial statements(?: and (?:supplemental|supplementary|notes)|$)',s,re.I):bare.append((pos,'financial_statements_and_notes'))
            if re.match(r'^(?:risk factors(?: and other key information)?|controls and procedures|other key information)$',s,re.I):ends.append(pos)
        if not m and len(s)<180 and ('financial statements' in s.lower() or 'consolidated statement' in s.lower() or 'consolidated balance sheets' in s.lower()):
            # Real standalone headings; avoid prose references and certifications.
            low=s.lower()
            if not any(x in low for x in ('see ','the following','our ','these ','item ','listed','refer','of the ','financial statements and exhibits')) and (not raw.lstrip().startswith('|')):
                if _FIN.match(s):standalone.append((pos,s))
    boundaries=sorted(set([p for p,_,_ in items]+ends+[p for p,_ in bare]+[len(body)]))
    ranges=[]
    for pos,item,title in items:
        lower=title.lower()
        wanted=None
        if form=='10-K' and item=='7' and 'discussion' in lower and 'analysis' in lower:wanted='md_and_a'
        if form=='10-K' and item=='8' and 'financial' in lower and 'statement' in lower:wanted='financial_statements_and_notes'
        if form=='10-Q' and item=='1' and 'financial' in lower and 'statement' in lower:wanted='financial_statements_and_notes'
        if form=='10-Q' and item=='2' and 'discussion' in lower and 'analysis' in lower:wanted='md_and_a'
        if wanted:
            end=next(p for p in boundaries if p>pos)
            if end-pos>=1500:ranges.append({'section':wanted,'start_char':pos,'end_char':end})
    for pos,section in bare:
        end=next(p for p in boundaries if p>pos)
        if end-pos>=1500:ranges.append({'section':section,'start_char':pos,'end_char':end})
    # Some annual reports place the statements after Item 15/16. Include the
    # standalone statements/notes block, bounded by the next SEC item/exhibit.
    for pos,title in standalone:
        if any(r['start_char']<=pos<r['end_char'] for r in ranges):continue
        end=next(p for p in boundaries if p>pos)
        if end-pos>=5000 and ('index to' in title.lower() or 'consolidated statement' in title.lower() or 'consolidated balance' in title.lower() or 'financial statements'==title.lower()):
            ranges.append({'section':'financial_statements_and_notes','start_char':pos,'end_char':end})
    # Union overlapping ranges; preserve offsets rather than reconstructing tables.
    result=[]
    for r in sorted(ranges,key=lambda x:(x['start_char'],x['end_char'])):
        if result and r['start_char']<=result[-1]['end_char']:
            result[-1]['end_char']=max(result[-1]['end_char'],r['end_char'])
            if r['section'] not in result[-1]['section']:result[-1]['section']+='+'+r['section']
        else:result.append(dict(r))
    return result


def evaluate(expression, variables):
    """Evaluate only decimal arithmetic, without executing arbitrary code."""
    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Name):
            return variables[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        raise ValueError(f'Unsupported arithmetic: {expression}')
    return visit(ast.parse(expression, mode='eval'))


def validate_questions(question_file, section_file):
    """Require every passage to be inside the exact section corpus being embedded."""
    import duckdb
    questions=[json.loads(line) for line in Path(question_file).read_text().splitlines() if line.strip()]
    assert len(questions)==50
    assert len({q['id'] for q in questions})==50
    assert len({q['question'].casefold() for q in questions})==50
    assert all(len(q['question'].split())<=12 for q in questions)
    assert {q['category'] for q in questions}=={'disclosure_lookup','comparative_analysis','financial_reasoning','risk_governance','connected_multi_document'}
    hard=[q for q in questions if q['category']=='connected_multi_document'];assert len(hard)>=10
    assert all(len({e['document_id'] for e in q['evidence']})>=2 for q in hard)
    ids=sorted({e['document_id'] for q in questions for e in q['evidence']})
    c=duckdb.connect();cur=c.execute('select * from read_parquet(?) where document_id in ('+','.join('?' for _ in ids)+')',[str(section_file),*ids]);columns=[x[0] for x in cur.description]
    rows={d['document_id']:d for raw in cur.fetchall() for d in [dict(zip(columns,raw))]}
    assert set(rows)==set(ids),('Missing eligible sources',set(ids)-set(rows))
    references=0;calculations=0
    for q in questions:
        assert q['index_rule']==RULE_VERSION
        for e in q['evidence']:
            row=rows[e['document_id']]
            assert row['md5']==e['parsed_md5'] and row['form'] in ('10-K','10-Q'),q['id']
            assert row['source_tokens']>=10000 and row['section_characters']>=16000,q['id']
            a,z=e['start_char'],e['end_char']
            section=next((r for r in row['sections'] if r['start_char']<=a and z<=r['end_char']),None)
            assert section and section['text'][a-section['start_char']:z-section['start_char']]==e['passage'],(q['id'],e['document_id'])
            assert e['section_start_char']==section['start_char'] and e['section_end_char']==section['end_char'],q['id']
            assert e['filed_date'].replace('-','')==row['filing_date'] and e['filed_date']<=q['as_of'],q['id']
            references+=1
        for calc in q.get('calculations',[]):
            variables={}
            for item in calc['inputs']:
                assert item['source_literal'] in q['evidence'][item['evidence_index']]['passage'],(q['id'],item)
                assert Decimal(re.sub(r'[^0-9.]','',item['source_literal']))==abs(Decimal(item['value'])),q['id']
                variables[item['name']]=Decimal(item['value'])
            result=evaluate(calc['expression'],variables).quantize(Decimal(1).scaleb(-calc['decimal_places']),rounding=ROUND_HALF_UP)
            assert result==Decimal(calc['result']),(q['id'],calc['label'],result,calc['result'])
            calculations+=1
    print(json.dumps({'validated_questions':len(questions),'categories':5,'connected_multi_document_questions':len(hard),'source_documents':len(rows),'evidence_references':references,'recorded_calculations_checked':calculations,'all_evidence_inside_indexed_sections':True},indent=2))
    return {'questions':len(questions),'source_documents':len(rows),'evidence_references':references,'calculations':calculations}


def main():
    import duckdb
    import tiktoken
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=Path(__file__).resolve().parents[1]/'data')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--validate-questions',type=Path)
    parser.add_argument('--summary-file',type=Path)
    parser.add_argument('--minimum-section-characters',type=int,default=16000)
    parser.add_argument('--minimum-section-tokens',type=int,default=10000)
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    c=duckdb.connect();c.execute('set threads=1');c.execute("set memory_limit='5GB'")
    c.execute('create table candidates(shard varchar,rownum bigint,document_id varchar,md5 varchar,chars bigint,form varchar,company varchar,filing_date varchar)')
    for file in sorted(args.data_dir.glob('sfd-v1-2025-??.parquet')):
        c.execute(r"""insert into candidates select ?,file_row_number,file_stem,md5,char_count,
        regexp_extract(left(parsed_md,2400),'\*\*CONFORMED SUBMISSION TYPE\*\*: ([^\n]+)',1),
        regexp_extract(left(parsed_md,4000),'COMPANY CONFORMED NAME:\*\* ([^\n]+)',1),
        regexp_extract(left(parsed_md,2400),'\*\*FILED AS OF DATE\*\*: ([0-9]+)',1)
        from read_parquet(?,file_row_number=true) where char_count>=40000 and regexp_extract(left(parsed_md,2400),'\*\*CONFORMED SUBMISSION TYPE\*\*: ([^\n]+)',1) in ('10-K','10-Q')""",[file.name,str(file)])
    c.execute('create table selected as select * from candidates qualify row_number() over(partition by document_id order by chars desc,md5,shard,rownum)=1')
    enc=tiktoken.get_encoding('cl100k_base');summary=[];pool=ThreadPoolExecutor(max_workers=2)
    # Temporary JSONL allows bounded memory and an atomic final Parquet write.
    tmp=tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',suffix='.jsonl',delete=False);tmp_path=Path(tmp.name)
    def prepare(meta,body):
        ranges=extract_sections(body,meta['form'])
        characters=sum(r['end_char']-r['start_char'] for r in ranges)
        if characters<args.minimum_section_characters:return None
        assert hashlib.md5(body.encode()).hexdigest()==meta['md5']
        spans=[{**r,'text':body[r['start_char']:r['end_char']]} for r in ranges]
        tokens=[len(enc.encode_ordinary(r['text'])) for r in spans]
        prefix=f"Company: {meta['company']} | Form: {meta['form']} | Filed: {meta['filing_date']} | Document: {meta['document_id']}\n"
        prefix_tokens=len(enc.encode_ordinary(prefix));chunks=sum(1+math.ceil(max(0,n-800)/700) for n in tokens)
        source_tokens=sum(tokens)
        if source_tokens<args.minimum_section_tokens:return None
        billed=source_tokens+100*(chunks-len(spans))+prefix_tokens*chunks
        return {**meta,'rule_version':RULE_VERSION,'sections':spans,'section_characters':characters,'section_utf8_bytes':sum(len(r['text'].encode()) for r in spans),'source_tokens':source_tokens,'chunks_800_overlap100':chunks,'prefix_tokens':prefix_tokens,'planned_embedding_tokens':billed}
    def save(result):
        if result:
            tmp.write(json.dumps(result,ensure_ascii=False)+'\n')
            summary.append({k:v for k,v in result.items() if k!='sections'})
    for shard in [r[0] for r in c.execute('select distinct shard from selected order by shard').fetchall()]:
        cur=c.execute('select * from selected where shard=? order by rownum',[shard]);cols=[x[0] for x in cur.description];lookup={r[1]:dict(zip(cols,r)) for r in cur.fetchall()}
        c.execute('create or replace temp table picks(rownum bigint)');c.executemany('insert into picks values (?)',[(i,) for i in lookup])
        cur=c.execute('select file_row_number,parsed_md from read_parquet(?,file_row_number=true) p join picks s on p.file_row_number=s.rownum',[str(args.data_dir/shard)])
        pending=[]
        while (row:=cur.fetchone()) is not None:
            i,body=row;pending.append(pool.submit(prepare,lookup[i],body))
            if len(pending)>=4:save(pending.pop(0).result())
        for future in pending:save(future.result())
        tmp.flush();print(shard,len(summary),'eligible section documents',flush=True)
    pool.shutdown();tmp.close()
    assert len(summary)>=10000, 'Rule retained fewer than 10,000 substantial documents'
    destination=args.output.with_suffix('.building.parquet')
    c.execute('copy (select * from read_json_auto(?,maximum_object_size=100000000)) to ? (format parquet,compression zstd)',[str(tmp_path),str(destination)])
    destination.replace(args.output);tmp_path.unlink()
    stats={'rule_version':RULE_VERSION,'candidate_documents':c.execute('select count(*) from selected').fetchone()[0],'documents':len(summary),'source_tokens':sum(r['source_tokens'] for r in summary),'section_utf8_bytes':sum(r['section_utf8_bytes'] for r in summary),'chunks_800_overlap100':sum(r['chunks_800_overlap100'] for r in summary),'planned_embedding_tokens':sum(r['planned_embedding_tokens'] for r in summary),'small_embedding_usd':sum(r['planned_embedding_tokens'] for r in summary)*0.02/1e6,'minimum_section_characters':args.minimum_section_characters,'minimum_section_tokens':args.minimum_section_tokens}
    assert stats['small_embedding_usd']*1.2<=20, 'Embedding estimate plus allowance exceeds $20'
    if args.summary_file:args.summary_file.write_text(json.dumps(stats,indent=2))
    print(json.dumps(stats,indent=2))
    if args.validate_questions:validate_questions(args.validate_questions,args.output)


if __name__=='__main__':main()
