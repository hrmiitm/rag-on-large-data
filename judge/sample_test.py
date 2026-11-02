#!/usr/bin/env python3
"""Read-only production snapshots plus optional live judge calibration via Foundry.

Run with the benchmark Python environment; writes only below judge/validation/.
Use --live to submit six sample judgements. No benchmark result is overwritten.
"""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
from pathlib import Path
import time

spec = importlib.util.spec_from_file_location('judge_eval', Path(__file__).with_name('eval.py'))
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
ROOT = Path(__file__).resolve().parent


def samples(model):
    golds = e.read_jsonl(e.REPO/'data/questions.jsonl', 'id')
    snapshots = {}
    selected = []
    source_report = []
    validator = e.Draft202012Validator(json.loads((e.REPO/'lume/bm25/src/benchmark.schema.json').read_text()))
    presentation_validator = e.Draft202012Validator(json.loads((ROOT/'evaluation.schema.json').read_text()))
    settings = e.parser().parse_args(['bm25', '--model', model])
    for method in ('bm25', 'agentic-search'):
        path = e.REPO/'lume'/method/'q-a.jsonl'
        raw = path.read_bytes()
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
        for row in records:
            validator.validate(row)
        originals = {r['question_id']: r for r in records}
        prepared = copy.deepcopy(originals)
        pending = e.prepare(prepared, golds, {}, settings, 'https://offline-validation.invalid')
        compact = [e.presentation_record(r) for r in prepared.values()]
        for row in compact:
            presentation_validator.validate(row)
            original = originals[row['question_id']]
            assert row['gold_evidence'] == golds[row['question_id']]['evidence']
            assert row['metrics'] == original['metrics']
            assert row['retrieval']['metrics'] == original['retrieval']['metrics']
            for answer_model, answer in row['answers'].items():
                original_answer = original['answers'][answer_model]
                assert answer['metrics'] == original_answer['metrics']
                if 'retrieval' in original_answer:
                    assert answer['retrieval']['metrics'] == original_answer['retrieval']['metrics']
                if 'tool_executions' in original_answer:
                    assert [t.get('metrics') for t in answer['tool_executions']] == [
                        t.get('metrics') for t in original_answer['tool_executions']]
                assert not any(k in answer for k in ('api_calls', 'message', 'trace', 'agent_state'))
        for task in pending.values():
            original = originals[task['qid']]
            answer = original['answers'][task['answer_model']]
            sent = json.loads(task['body']['messages'][1]['content'])
            assert sent['context_sent_to_answer_model'] == (answer.get('context') or original['context'])
        projected = ('\n'.join(json.dumps(r, ensure_ascii=False, separators=(',', ':')) for r in compact)+'\n').encode()
        assert len([json.loads(line) for line in projected.splitlines()]) == len(records)
        successful = [r for r in records if r['question_id'] == 'q001' and any(a.get('status') == 'ok' for a in r['answers'].values())]
        if not successful:
            raise ValueError(f'{method} has no completed q001 sample yet; wait for the active run')
        row = copy.deepcopy(successful[0])
        answer_model, answer = next((m, a) for m, a in row['answers'].items() if a.get('status') == 'ok')
        selected.append((f'actual_{method}', row, copy.deepcopy(answer), golds[row['question_id']], []))
        snapshots[method] = row
        source_report.append({'method': method, 'records_in_snapshot': len(records),
            'successful_answers_in_snapshot': sum(a.get('status') == 'ok' for r in records for a in r['answers'].values()),
            'source_bytes': len(raw), 'source_snapshot_sha256': hashlib.sha256(raw).hexdigest(),
            'projected_export_bytes': len(projected),
            'offline_checks': 'All snapshot records pass JSON schemas/roundtrip, full gold evidence, metric preservation and per-model context checks.',
            'sample_question_id': row['question_id'], 'sample_answer_model': answer_model,
            'sample_answer_context_used': 'answers[model].context' if answer.get('context') else 'context'})
    gold = golds['q001']
    base = snapshots['bm25']
    relevant = {'text': '[1] '+gold['evidence'][0]['passage'], 'chunk_ids': ['gold-fixture'], 'citation_map': {'1': 'gold-fixture'}}
    unrelated = {'text': '[1] An unrelated company describes its office equipment. No Alphabet financial figures are provided.',
                 'chunk_ids': ['unrelated-fixture'], 'citation_map': {'1': 'unrelated-fixture'}}
    scenarios = [
        ('control_correct_supported', gold['expected_answer']+' [1].', relevant,
         [('answer_correctness', '>=', .9), ('faithfulness', '>=', .9), ('context_relevance', '>=', .9)]),
        ('control_wrong_contradicted', 'Alphabet revenue in 2024 was $1 trillion [1].', relevant,
         [('answer_correctness', '<=', .2), ('faithfulness', '<=', .2)]),
        ('control_correct_without_context', gold['expected_answer']+'.', unrelated,
         [('answer_correctness', '>=', .9), ('faithfulness', '<=', .2), ('context_relevance', '<=', .2)]),
        ('control_justified_abstention', 'The supplied passage does not provide Alphabet\u2019s 2024 revenue, so I cannot determine it from this context.', unrelated,
         [('answer_correctness', '<=', .2), ('faithfulness', '>=', .8), ('context_relevance', '<=', .2)]),
    ]
    for name, text, context, checks in scenarios:
        row = copy.deepcopy(base)
        answer = copy.deepcopy(next(iter(row['answers'].values())))
        answer.update(final_answer=text, context=copy.deepcopy(context))
        selected.append((name, row, answer, gold, checks))
    args = e.parser().parse_args(['bm25', '--model', model])
    tasks = {}
    for name, row, answer, gold, checks in selected:
        body = e.payload(row, gold, answer, args)
        identity = e.digest({'scenario': name, 'body': body})
        entry = {}
        tasks[identity] = {'id': identity, 'qid': row['question_id'], 'answer_model': name,
            'body': body, 'entry': entry, 'scenario': name, 'candidate_answer': answer['final_answer'],
            'gold_answer': gold['expected_answer'], 'checks': checks}
    return tasks, source_report


def result_report(tasks, sources, mode):
    results = []
    for task in tasks.values():
        details = e.compact_judge(task['entry'].get('judge_details')) or {'status': 'pending'}
        scores = task['entry'].get('judge')
        checks = []
        for metric, operation, threshold in task['checks']:
            observed = (scores or {}).get(metric)
            passed = observed is not None and (observed >= threshold if operation == '>=' else observed <= threshold)
            checks.append({'metric': metric, 'operation': operation, 'threshold': threshold,
                           'observed': observed, 'passed': passed})
        results.append({'scenario': task['scenario'], 'question_id': task['qid'],
            'candidate_answer': task['candidate_answer'], 'gold_answer': task['gold_answer'],
            'judge': scores, 'judge_details': details, 'calibration_checks': checks})
    complete = all(r['judge_details']['status'] == 'completed' for r in results)
    passed = complete and all(c['passed'] for r in results for c in r['calibration_checks'])
    return {'created_at': e.now(), 'model_requested': tasks[next(iter(tasks))]['body']['model'],
        'mode': mode, 'source_access': 'Read-only snapshots; active writers were not locked or interrupted.',
        'sources': sources, 'status': 'passed' if passed else ('pending' if any(r['judge_details']['status'] == 'pending' for r in results) else 'failed'),
        'scope': 'Schema/compaction plus four controlled calibration cases and two real completed answers; not an accuracy benchmark.',
        'results': results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live', action='store_true')
    p.add_argument('--mode', choices=['batch', 'concurrent'], default='batch')
    p.add_argument('--model', default=e.DEFAULT_MODEL)
    p.add_argument('--max-wait-seconds', type=float, default=900)
    args = p.parse_args()
    tasks, sources = samples(args.model)
    directory = ROOT/'validation'
    directory.mkdir(exist_ok=True)
    report_path = directory/f'sample-{args.mode}-report.json'
    def write():
        e.save_json(report_path, result_report(tasks, sources, args.mode))
    if not args.live:
        report = {'source_checks': sources, 'sample_tasks': len(tasks), 'api_calls': 0}
        e.save_json(directory/'offline-snapshot-report.json', report)
        print(json.dumps(report, indent=2))
        return 0
    base, key = e.environment(True)
    client = e.Client(base, key, directory/f'sample-{args.mode}.audit.jsonl')
    if args.mode == 'batch':
        settings = e.parser().parse_args(['bm25', '--model', args.model, '--max-wait-seconds', str(args.max_wait_seconds)])
        # Resume via task fingerprints without ever writing production final-results.
        previous = json.loads(report_path.read_text()) if report_path.exists() else {}
        by_name = {r['scenario']: r for r in previous.get('results', [])}
        for task in tasks.values():
            old = by_name.get(task['scenario']) or {}
            details = old.get('judge_details') or {}
            if details.get('task_fingerprint') == task['id'] and details.get('status') in ('completed', 'error'):
                task['entry'].update(judge=old.get('judge'), judge_details=details)
        pending = {i: t for i, t in tasks.items() if not t['entry']}
        e.run_batch(pending, client, directory/'sample-batch.state.json', write, settings)
    else:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {pool.submit(client.call, '/openrouter/v1/chat/completions', t['body']): t for t in tasks.values()}
            for future in as_completed(futures):
                task = futures[future]
                body, calls = future.result()
                e.apply_result(task, body, calls, calls[-1]['error'] if body is None else None)
                write()
    write()
    report = json.loads(report_path.read_text())
    print(json.dumps({'status': report['status'], 'report': str(report_path),
        'scenarios': [{'scenario': r['scenario'], 'status': r['judge_details']['status'], 'scores': r['judge']} for r in report['results']]}, indent=2))
    return 0 if report['status'] == 'passed' else (2 if report['status'] == 'pending' else 1)


if __name__ == '__main__':
    raise SystemExit(main())
