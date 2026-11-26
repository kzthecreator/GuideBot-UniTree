"""SSE and queue boundaries without network or hardware."""
import json
import tempfile
import threading
import unittest
from unittest.mock import MagicMock

from GuideBot.gesture.catalog import Catalog
from GuideBot.gesture.semantic import Chunk
from GuideBot.gesture.semantic_planner import SemanticPlanner
from GuideBot.gesture.service import GestureService, PlanningReply

TEXT = '欢迎各位来到我们的展厅，接下来请看左侧的园区沙盘。'
ROW = dict(action='present_left', begin=dict(text='欢迎', occurrence=1),
           finish_by=dict(text='园区沙盘', occurrence=1))


def event(content='', finish=None):
    return ('data: '+json.dumps({'choices': [{'delta': {'content': content},
                                             'finish_reason': finish}]})+'\n\n').encode()


class StreamingTests(unittest.TestCase):
    def planner(self, chunks):
        session = MagicMock()
        response = session.post.return_value.__enter__.return_value
        response.status_code = 200
        response.iter_content.return_value = chunks
        return SemanticPlanner(Catalog(), api_key='test-only', session=session)

    def test_complete_object_delivered_before_next_network_chunk(self):
        received = []
        row = json.dumps(ROW, ensure_ascii=False)
        def chunks():
            # Arbitrary byte splits, including UTF-8 and SSE delimiters.
            first = event('{"actions":['+row[:-1])
            for byte in first:
                yield bytes([byte])
            self.assertEqual(received, [])
            yield event('}')
            self.assertEqual(received, [ROW])
            yield event(']}', 'stop')
            yield b'data: [DONE]\n\n'
        result = self.planner(chunks()).analyze(TEXT, on_action=received.append)
        self.assertEqual(result['actions'], [ROW])
        self.assertTrue(result['streamed'])
        self.assertEqual(received, [ROW])

    def test_bad_termination_and_bad_schema(self):
        for chunks in ([event('{"actions":[]}')],
                       [event('{"actions":[]}', 'length'), b'data: [DONE]\n\n'],
                       [event('{"actions":[{"action":"unknown"}]}', 'stop'), b'data: [DONE]\n\n'],
                       [event('{"actions":[]}', 'stop')]):
            with self.assertRaises(RuntimeError):
                self.planner(chunks).analyze(TEXT)

    def test_cancel_after_first_object(self):
        cancelled = threading.Event()
        received = []
        def action(row):
            received.append(row)
            cancelled.set()
        result = self.planner([event('{"actions":['+json.dumps(ROW)),
                               event(']}', 'stop'), b'data: [DONE]\n\n']).analyze(
                                   TEXT, cancelled, action)
        self.assertTrue(result['cancelled'])
        self.assertEqual(received, [ROW])

    def test_service_incremental_queue_final_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            service = GestureService(directory, planner=type('Fake', (), {'semantic': True})())
            service.scheduler.text('r', TEXT)
            state = PlanningReply(text=TEXT, in_flight=True, request_id=1)
            service.replies['r'] = state
            value = dict(chunk=Chunk(TEXT, 0, TEXT), request_id=1, result={'actions': [ROW]})
            service._semantic_result('r', value, incremental=True)
            self.assertTrue(state.in_flight)
            self.assertEqual(len(service.pending_intents['r']), 1)
            value['result'] = dict(actions=[ROW], streamed=True)
            service._semantic_result('r', value)
            self.assertFalse(state.in_flight)
            self.assertEqual(len(service.pending_intents['r']), 1)
            service.pending_intents['r'].append(dict(request_id=2))
            value['result'] = dict(error='Invalid Planner semantic stream')
            service._semantic_result('r', value)
            self.assertEqual(service.pending_intents['r'], [dict(request_id=2)])
            state.cancelled.set()
            value['result'] = {'actions': [ROW]}
            service._semantic_result('r', value, incremental=True)
            self.assertEqual(service.pending_intents['r'], [dict(request_id=2)])

    def test_worker_emits_action_before_final_result(self):
        with tempfile.TemporaryDirectory() as directory:
            service = GestureService(directory, planner=self.planner([
                event('{"actions":['+json.dumps(ROW)), event(']}', 'stop'),
                b'data: [DONE]\n\n']))
            seen = []
            service.submit = lambda kind, rid, **value: seen.append((kind, value))
            service._semantic_request('r', Chunk(TEXT, 0, TEXT), 1, threading.Event())
            self.assertEqual([kind for kind, _ in seen], ['semantic_action', 'semantic_result'])
            self.assertEqual(seen[0][1]['result']['actions'], [ROW])
            self.assertTrue(seen[1][1]['result']['streamed'])
