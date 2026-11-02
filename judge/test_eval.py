"""Offline integration tests: never contacts an external API."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('judge_eval', Path(__file__).with_name('eval.py'))
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


def record(qid='q001'):
    return {'schema_version': 'rag-benchmark/1.0', 'method': 'fixture', 'run_id': 'fixture',
            'question_id': qid, 'question': 'What is revenue?', 'as_of': '2025-01-01', 'status': 'pending',
            'configuration_hash': 'fixture', 'requested_models': ['answer-model'],
            'retrieval': {'queries': [], 'chunks': [], 'metrics': {}},
            'context': {'text': '[1] Revenue was $10 million.', 'chunk_ids': ['chunk1'], 'citation_map': {'1': 'chunk1'}},
            'answers': {'answer-model': {'model_requested': 'answer-model', 'model_returned': 'answer-model',
                'provider': 'fixture', 'final_answer': '$10 million [1]', 'status': 'ok', 'api_calls': [],
                'metrics': {}, 'errors': []}}, 'metrics': {}, 'errors': [], 'trace': [], 'provenance': {}}


def gold(qid='q001'):
    return {'id': qid, 'category': 'financial_inference', 'question': 'What is revenue?',
            'as_of': '2025-01-01', 'expected_answer': '$10 million',
            'evidence': [{'document_id': 'filing1', 'passage': 'Revenue was $10 million.', 'start_char': 10, 'end_char': 34}],
            'calculations': {'formula': '10'}, 'required_answer_points': ['$10 million']}


def response(score=1):
    return {'id': 'gen-fixture', 'model': e.DEFAULT_MODEL, 'provider': 'Anthropic',
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                'judge': {s: score for s in e.SCORES}, 'explanations': {s: 'Supported by [1].' for s in e.SCORES}})}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'cost': .001,
                      'completion_tokens_details': {'reasoning_tokens': 2}}}


class FakeClient:
    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []

    def call(self, path, body=None, attempts=3):
        self.calls.append((path, body))
        value = self.batches.pop(0)
        if callable(value):
            value = value(body)
        return value, [{'http_status': 200 if value else 503, 'error': None if value else {'type': 'timeout'},
                        'latency_ms': 1, 'response': value}]


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.args = e.parser().parse_args(['bm25', '--max-wait-seconds', '0'])
        self.rows = {'q001': record()}
        self.golds = {'q001': gold()}
        self.tasks = e.prepare(self.rows, self.golds, {}, self.args, 'https://foundry.test')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'output.jsonl'
        self.state = self.path.with_suffix('.state.json')
        self.write = e.output_writer(self.path, self.rows, 'SECRET')

    def task(self):
        return next(iter(self.tasks.values()))

    def completed(self, request):
        return {'id': 'batch_fixture', 'status': 'completed', 'provider': 'Anthropic', 'usage': {'cost': .02},
                'results': [{'custom_id': r['custom_id'], 'response': {'status_code': 200, 'request_id': 'req-fixture',
                    'body': response()}, 'error': None} for r in reversed(request['requests'])]}

    def test_defaults(self):
        self.assertEqual(self.args.model, 'anthropic/claude-sonnet-5.5')
        self.assertEqual(self.args.temperature, 0)
        self.assertEqual(self.args.reasoning_effort, 'low')
        self.assertEqual(self.args.mode, 'batch')

    def test_gold_and_exact_context_only(self):
        data = json.loads(self.task()['body']['messages'][1]['content'])
        self.assertEqual(data['gold_answer'], gold()['expected_answer'])
        self.assertEqual(data['gold_evidence'], gold()['evidence'])
        self.assertEqual(data['context_sent_to_answer_model'], record()['context'])
        self.assertNotIn('retrieval', data)
        self.assertNotIn('answer-model', json.dumps(data))
        self.assertIn('required_answer_points', data['gold_details'])

    def test_gold_join_errors(self):
        for changed in ({}, {'q001': {**gold(), 'question': 'Wrong'}}, {'q001': {**gold(), 'evidence': []}}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                e.prepare({'q001': record()}, changed, {}, self.args, 'https://foundry.test')

    def test_presentation_preserves_gold_and_metrics(self):
        e.apply_result(self.task(), response(), [])
        self.write()
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved['schema_version'], 'rag-presentation/1.0')
        self.assertEqual(saved['source_schema_version'], 'rag-benchmark/1.0')
        self.assertEqual(saved['metrics'], record()['metrics'])
        self.assertEqual(saved['gold_evidence'], gold()['evidence'])
        self.assertEqual(saved['gold_details']['calculations'], gold()['calculations'])
        self.assertNotIn('gold_reference', saved)
        self.assertEqual(saved['question_category'], 'financial_inference')
        self.assertEqual(saved['judge']['faithfulness'], 1)

    def test_multi_model_no_ambiguous_top_alias(self):
        self.rows['q001']['answers']['other-model'] = copy.deepcopy(record()['answers']['answer-model'])
        e.prepare(self.rows, self.golds, {}, self.args, 'https://foundry.test')
        self.write()
        self.assertIsNone(json.loads(self.path.read_text())['judge'])

    def test_score_validation(self):
        for score in (1.01, -.1, True, float('nan')):
            with self.subTest(score=score):
                e.apply_result(self.task(), response(score), [])
                self.assertIsNone(self.task()['entry']['judge'])
                self.assertEqual(self.task()['entry']['judge_details']['status'], 'error')
        body = response(); body['choices'][0]['finish_reason'] = 'length'
        e.apply_result(self.task(), body, [])
        self.assertIsNone(self.task()['entry']['judge'])

    def test_resume_and_invalidation(self):
        e.apply_result(self.task(), response(), [])
        self.write()
        previous = e.read_jsonl(self.path, 'question_id')
        for mutation in ('none', 'answer', 'context', 'gold', 'model', 'temperature'):
            args = copy.copy(self.args); rows = {'q001': record()}; golds = {'q001': gold()}
            if mutation == 'answer': rows['q001']['answers']['answer-model']['final_answer'] = '$11 million'
            if mutation == 'context': rows['q001']['context']['text'] = 'New context'
            if mutation == 'gold': golds['q001']['expected_answer'] = '$11 million'
            if mutation == 'model': args.model = 'another-judge'
            if mutation == 'temperature': args.temperature = .2
            tasks = e.prepare(rows, golds, previous, args, 'https://foundry.test')
            self.assertEqual(len(tasks), 0 if mutation == 'none' else 1, mutation)

    def test_skip_unavailable_answers(self):
        for status, answer in [('error', '$10 million'), ('ok', None), ('ok', '')]:
            rows = {'q001': record()}; rows['q001']['answers']['answer-model'].update(status=status, final_answer=answer)
            self.assertEqual(e.prepare(rows, self.golds, {}, self.args, 'https://foundry.test'), {})
            self.assertEqual(rows['q001']['answers']['answer-model']['judge_details']['status'], 'skipped')

    def test_retry_errors_and_history(self):
        e.apply_result(self.task(), None, [], error={'type': 'fixture'})
        previous = copy.deepcopy(self.rows)
        self.assertEqual(e.prepare({'q001': record()}, self.golds, previous, self.args, 'https://foundry.test'), {})
        self.args.retry_errors = True
        tasks = e.prepare({'q001': record()}, self.golds, previous, self.args, 'https://foundry.test')
        task = next(iter(tasks.values()))
        e.apply_result(task, response(), [])
        self.assertEqual(task['entry']['judge_details']['attempt_history'][0]['error']['type'], 'fixture')

    def test_batch_submission_and_shuffled_matching(self):
        self.rows['q002'] = record('q002'); self.golds['q002'] = gold('q002')
        self.tasks = e.prepare(self.rows, self.golds, {}, self.args, 'https://foundry.test')
        client = FakeClient([self.completed])
        e.run_batch(self.tasks, client, self.state, self.write, self.args)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][0], '/openrouter/v1/batches')
        for task in self.tasks.values():
            details = task['entry']['judge_details']
            self.assertEqual(details['status'], 'completed')
            self.assertEqual(details['batch_result']['response']['request_id'], 'req-fixture')
            self.assertEqual(details['metrics']['api_cost_usd'], .001)
            self.assertEqual(details['batch_usage']['cost'], .02)
            self.assertIsNone(details['metrics']['llm_api_calls'])
        self.assertTrue(json.loads(self.state.read_text())['submissions'][0]['processed'])

    def test_pending_batch_resumes_without_resubmit(self):
        client = FakeClient([{'id': 'batch_fixture', 'status': 'in_progress'},
                             {'id': 'batch_fixture', 'status': 'in_progress'}])
        e.run_batch(self.tasks, client, self.state, self.write, self.args)
        request = client.calls[0][1]
        resumed = FakeClient([self.completed(request)])
        e.run_batch(self.tasks, resumed, self.state, self.write, self.args)
        self.assertEqual([p for p, _ in resumed.calls], ['/openrouter/v1/batches/batch_fixture'])

    def test_ambiguous_submission_never_retried(self):
        client = FakeClient([None])
        with self.assertRaises(ValueError):
            e.run_batch(self.tasks, client, self.state, self.write, self.args)
        with self.assertRaises(ValueError):
            e.run_batch(self.tasks, FakeClient([]), self.state, self.write, self.args)
        self.assertEqual(len(client.calls), 1)

    def test_active_batch_changed_settings_blocked(self):
        e.save_json(self.state, {'submissions': [{'task_ids': ['other-input'], 'processed': False,
                                                  'batch': {'id': 'batch_old', 'status': 'in_progress'}}]})
        with self.assertRaises(ValueError):
            e.run_batch(self.tasks, FakeClient([]), self.state, self.write, self.args)

    def test_partial_batch_and_missing_results(self):
        def partial(request):
            batch = self.completed(request)
            batch['results'][0]['response'] = None
            batch['results'][0]['error'] = {'type': 'provider_failure'}
            return batch
        e.run_batch(self.tasks, FakeClient([partial]), self.state, self.write, self.args)
        self.assertIsNone(self.task()['entry']['judge'])
        self.assertEqual(self.task()['entry']['judge_details']['error']['type'], 'provider_failure')

    def test_duplicate_result_rejected(self):
        def duplicate(request):
            batch = self.completed(request); batch['results'] *= 2
            return batch
        with self.assertRaises(ValueError):
            e.run_batch(self.tasks, FakeClient([duplicate]), self.state, self.write, self.args)

    def test_duplicate_question_id_rejected(self):
        self.path.write_text(json.dumps(record())+'\n'+json.dumps(record())+'\n')
        with self.assertRaises(ValueError):
            e.read_jsonl(self.path, 'question_id')

    def test_secret_redaction_and_route_guard(self):
        self.rows['q001']['trace'] = ['SECRET']
        self.write()
        self.assertNotIn('SECRET', self.path.read_text())
        client = e.Client('https://foundry.test', 'SECRET', self.path)
        self.assertEqual(client.clean({'value': 'SECRET'}), {'value': '[REDACTED]'})
        self.assertNotIn('authorization', client.safe_headers({'Authorization': 'SECRET'}))
        with self.assertRaises(ValueError):
            client.call('/openai/v1/chat/completions', {})
        with patch.dict('os.environ', {'LLMFOUNDRY_BASE_URL': 'https://openrouter.ai', 'LLM_PROVIDER': 'llmfoundry'}):
            with self.assertRaises(ValueError): e.environment(False)

    def test_reasoning_not_double_counted(self):
        body = response(); calls = [{'response': body, 'latency_ms': 10}]
        metrics = e.usage_metrics(calls, body)
        self.assertEqual(metrics['output_tokens'], 5)
        self.assertEqual(metrics['reasoning_tokens'], 2)
        self.assertIsNone(metrics['time_to_first_token_ms'])
        self.assertFalse(e.usage_metrics([{'response': {}, 'latency_ms': 2}], None)['cost_complete'])

    def integration_files(self):
        root = Path(self.temp.name)
        judge = root/'judge'; method = root/'lume/fixture'
        judge.mkdir(parents=True); method.mkdir(parents=True)
        (root/'lume/bm25/src').mkdir(parents=True)
        (root/'data').mkdir()
        (root/'lume/bm25/src/benchmark.schema.json').write_text((e.REPO/'lume/bm25/src/benchmark.schema.json').read_text())
        (judge/'evaluation.schema.json').write_text((e.HERE/'evaluation.schema.json').read_text())
        source = method/'q-a.jsonl'
        source.write_text(json.dumps(record())+'\n')
        (root/'data/questions.jsonl').write_text(json.dumps(gold())+'\n')
        return root, judge, source

    def test_concurrent_cli_and_resume_preserve_input(self):
        root, judge, source = self.integration_files()
        original = source.read_bytes()
        client = FakeClient([response()])
        with patch.object(e, 'REPO', root), patch.object(e, 'HERE', judge), \
             patch.object(e, 'environment', return_value=('https://foundry.test', 'SECRET')), \
             patch.object(e, 'Client', return_value=client):
            self.assertEqual(e.main(['fixture', '--mode', 'concurrent']), 0)
            self.assertEqual(e.main(['fixture', '--mode', 'concurrent']), 0)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(json.loads((judge/'final-results/q-a-eval-lume-fixture.jsonl').read_text())['judge']['faithfulness'], 1)

    def test_native_cli_and_resume(self):
        root, judge, source = self.integration_files()
        original = source.read_bytes()
        client = FakeClient([self.completed])
        with patch.object(e, 'REPO', root), patch.object(e, 'HERE', judge), \
             patch.object(e, 'environment', return_value=('https://foundry.test', 'SECRET')), \
             patch.object(e, 'Client', return_value=client):
            self.assertEqual(e.main(['fixture']), 0)
            self.assertEqual(e.main(['fixture']), 0)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(source.read_bytes(), original)

        results = judge/'final-results'
        self.assertEqual([p.name for p in results.iterdir()], ['q-a-eval-lume-fixture.jsonl'])
        self.assertTrue((judge/'q-a-eval-lume-fixture.state.json').exists())
        self.assertTrue((judge/'q-a-eval-lume-fixture.lock').exists())

    def test_dry_run_writes_nothing(self):
        root, judge, _ = self.integration_files()
        with patch.object(e, 'REPO', root), patch.object(e, 'HERE', judge), \
             patch.object(e, 'environment', return_value=('https://foundry.test', '')), \
             patch.object(e, 'Client') as client:
            self.assertEqual(e.main(['fixture', '--dry-run']), 0)
            client.assert_not_called()
        self.assertFalse(list(judge.rglob('q-a-eval-*')))

    def test_compaction_removes_payloads_preserves_all_metrics(self):
        row = self.rows['q001']
        row['metrics'] = {'cost': .1, 'latency': 100, 'custom_new_metric': 42}
        row['retrieval']['metrics'] = {'rss': 333}
        row['retrieval']['chunks'] = [{'text': 'UNNECESSARY_CONTEXT', 'chunk_id': 'chunk1',
            'document_id': 'doc1', 'rank': 1, 'scores': {'bm25': 2},
            'source': {'hash': 'abc', 'start_char': 1, 'end_char': 4, 'section': 'financial'}, 'metadata': {}}]
        row['context']['text'] = 'UNNECESSARY_CONTEXT'
        answer = row['answers']['answer-model']
        answer['metrics'] = {'tokens': 100, 'db_operations': 43}
        answer['message'] = {'reasoning': 'UNNECESSARY_REASONING'}
        answer['api_calls'] = [{'request': 'UNNECESSARY_REQUEST', 'raw_response': 'UNNECESSARY_RESPONSE'}]
        answer['tool_executions'] = [{'metrics': {'search_ms': 12}, 'response': 'UNNECESSARY_TOOL_RESULT'}]
        answer['context'] = copy.deepcopy(row['context'])
        answer['retrieval'] = copy.deepcopy(row['retrieval'])
        answer['generation_metadata'] = {'data': {'total_cost': .1, 'generation_time': 222}}
        e.apply_result(self.task(), response(), [])
        answer['judge_details']['metrics']['another_custom_metric'] = 11
        row['trace'] = ['UNNECESSARY_TRACE']
        original = copy.deepcopy(row)
        compact = e.presentation_record(row)
        text = json.dumps(compact)
        self.assertNotIn('UNNECESSARY_', text)
        self.assertEqual(row, original)
        self.assertEqual(compact['metrics'], row['metrics'])
        self.assertEqual(compact['retrieval']['metrics'], row['retrieval']['metrics'])
        out = compact['answers']['answer-model']
        self.assertEqual(out['metrics'], answer['metrics'])
        self.assertEqual(out['retrieval']['metrics'], answer['retrieval']['metrics'])
        self.assertEqual(out['judge_details']['metrics'], answer['judge_details']['metrics'])
        self.assertEqual(out['tool_executions'][0]['metrics'], {'search_ms': 12})
        self.assertEqual(out['generation_statistics']['generation_time'], 222)
        self.assertEqual(compact['gold_evidence'], gold()['evidence'])

    def test_export_only_preserves_judgements_with_another_model(self):
        root, judge, source = self.integration_files()
        original = source.read_bytes()
        client = FakeClient([response()])
        with patch.object(e, 'REPO', root), patch.object(e, 'HERE', judge), \
             patch.object(e, 'environment', return_value=('https://foundry.test', 'SECRET')), \
             patch.object(e, 'Client', return_value=client):
            self.assertEqual(e.main(['fixture', '--mode', 'concurrent']), 0)
            self.assertEqual(e.main(['fixture', '--export-only', '--model', 'different-judge']), 0)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(source.read_bytes(), original)
        saved = json.loads((judge/'final-results/q-a-eval-lume-fixture.jsonl').read_text())
        self.assertEqual(saved['judge_details']['status'], 'completed')
        self.assertEqual(saved['judge_details']['model_requested'], e.DEFAULT_MODEL)

    def test_export_only_pending_scores_no_calls(self):
        root, judge, source = self.integration_files()
        original = source.read_bytes()
        with patch.object(e, 'REPO', root), patch.object(e, 'HERE', judge), \
             patch.object(e, 'environment', return_value=('https://foundry.test', '')), \
             patch.object(e, 'Client') as client:
            self.assertEqual(e.main(['fixture', '--export-only']), 0)
            client.assert_not_called()
        saved = json.loads((judge/'final-results/q-a-eval-lume-fixture.jsonl').read_text())
        self.assertIsNone(saved['judge'])
        self.assertEqual(saved['judge_details']['status'], 'pending')
        self.assertEqual(source.read_bytes(), original)

    def test_payload_uses_each_answer_context(self):
        answer = record()['answers']['answer-model']
        answer['context'] = {'text': 'Model-specific context', 'chunk_ids': [], 'citation_map': {}}
        data = json.loads(e.payload(record(), gold(), answer, self.args)['messages'][1]['content'])
        self.assertEqual(data['context_sent_to_answer_model'], answer['context'])


if __name__ == '__main__':
    unittest.main()
