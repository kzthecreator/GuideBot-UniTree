"""Offline contract tests: no network, audio devices or robot."""
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from GuideBot.gesture.catalog import Catalog, units_for
from GuideBot.gesture.semantic import Chunk, bind, next_chunk, validate_output
from GuideBot.gesture.semantic_planner import SemanticPlanner
from GuideBot.gesture.service import GestureService, PlanningReply


TEXT = '欢迎各位来到我们的展厅，接下来请看左侧的园区沙盘。'
ROW = dict(action='present_left', begin=dict(text='欢迎', occurrence=1),
           finish_by=dict(text='园区沙盘', occurrence=1))


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()

    def test_chunk_threshold_punctuation_and_eof(self):
        self.assertIsNone(next_chunk('你好，请问', 0))
        text = '你好，请问有什么可以帮您的？还有一些文字'
        first = next_chunk(text, 0)
        self.assertEqual(first.text, '你好，请问有什么可以帮您的？')
        self.assertIsNone(next_chunk(text, len(first.text), True))
        self.assertEqual(next_chunk('一二三四五六七八九十', 0, True).text, '一二三四五六七八九十')
        self.assertIsNone(next_chunk('一，二。三！四？', 0, True))

    def test_quote_occurrences_and_global_offsets(self):
        prefix = '第一段介绍。'
        chunk = Chunk('欢迎来到展厅，欢迎观看沙盘。', len(prefix), prefix+'欢迎来到展厅，欢迎观看沙盘。')
        row = dict(action='greet_open', begin=dict(text='欢迎', occurrence=2),
                   finish_by=dict(text='沙盘', occurrence=1))
        begin, finish, source = bind(self.catalog, row, chunk)
        units = units_for(chunk.snapshot)
        self.assertEqual(units[begin]['text_offset'], len(prefix)+7)
        self.assertEqual(source[-1], units[finish])
        row['finish_by']['text'] = '不存在'
        with self.assertRaisesRegex(ValueError, 'quote_not_found'):
            bind(self.catalog, row, chunk)

    def test_strict_contract_and_word_boundary(self):
        for row in [dict(ROW, start_s=1), dict(ROW, action='invented'),
                    dict(ROW, begin=dict(text='欢迎', occurrence=True))]:
            with self.assertRaises(ValueError):
                validate_output(self.catalog, {'actions':[row]})
        chunk = Chunk('Welcome visitors to GuideBot.', 0, 'Welcome visitors to GuideBot.')
        row = dict(action='greet_open', begin=dict(text='Wel', occurrence=1),
                   finish_by=dict(text='GuideBot', occurrence=1))
        with self.assertRaisesRegex(ValueError, 'quote_not_unit_boundary'):
            bind(self.catalog, row, chunk)

    def planner(self, content, finish='stop'):
        session = MagicMock()
        response = session.post.return_value.__enter__.return_value
        response.status_code = 200
        response.iter_content.return_value = [json.dumps({'choices':[
            {'finish_reason':finish, 'delta':{'content':content}}]}).join(['data: ', '\n\ndata: [DONE]\n\n']).encode()]
        return SemanticPlanner(self.catalog, api_key='test-only', session=session), session

    def test_http_plain_text_only_and_whole_json(self):
        planner, session = self.planner(json.dumps({'actions':[ROW]}))
        self.assertEqual(planner.analyze(TEXT)['actions'], [ROW])
        payload = session.post.call_args.kwargs['json']
        self.assertEqual(payload['messages'], [dict(role='system', content=planner.instruct),
                                              dict(role='user', content=TEXT)])
        self.assertTrue(payload['stream'])
        for content, finish in [('{"actions":[],"actions":[]}', 'stop'),
                                ('{"actions":[]}', 'length'), ('{', 'stop')]:
            planner, _ = self.planner(content, finish)
            with self.assertRaises(RuntimeError):
                planner.analyze(TEXT)

    def test_cancel_and_transport_bounds(self):
        planner, session = self.planner('{"actions":[]}')
        cancelled = threading.Event()
        cancelled.set()
        self.assertTrue(planner.analyze(TEXT, cancelled)['cancelled'])
        session.post.assert_not_called()
        cancelled.clear()
        response = session.post.return_value.__enter__.return_value
        response.iter_content.return_value = [b'x'*131073]
        with self.assertRaisesRegex(RuntimeError, 'limit exceeded'):
            planner.analyze(TEXT, cancelled)

    def test_local_join_waits_then_fixes_deadline_and_invalidates_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            service = GestureService(directory, planner=type('Fake', (), {'semantic':True})())
            service.scheduler.text('r', TEXT)
            begin, finish, source = bind(self.catalog, ROW, Chunk(TEXT, 0, TEXT))
            service.pending_intents['r'] = [dict(action=ROW['action'], begin=begin, finish=finish,
                                                source=source, request_id=1, waiting=False)]
            service._resolve_semantic()
            self.assertEqual(len(service.pending_intents['r']), 1)
            service.scheduler.playback('r', time.monotonic()+10)
            units = units_for(TEXT)
            anchors = [dict(index=i, text=units[i]['text'], text_offset=units[i]['text_offset'], start=t)
                       for i,t in [(begin, 0.), (finish, 4.)]]
            service.scheduler.alignment('r', dict(version=1, anchors=anchors))
            service._resolve_semantic()
            job = service.scheduler.replies['r'].jobs[0]
            self.assertEqual((job.plan.start_s, job.plan.end_s), (0.,4.))
            anchors[-1]['start'] = 5.
            service.scheduler.alignment('r', dict(version=2, anchors=anchors))
            service._invalidate_semantic_windows('r')
            self.assertEqual(job.status, 'cancelled')
            self.assertEqual(job.plan.end_s, 4.)

    def test_expired_window_never_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            events = []
            service = GestureService(directory, planner=type('Fake', (), {'semantic':True})(),
                                     on_event=lambda kind, **kw: events.append((kind, kw)))
            service.scheduler.text('r', TEXT)
            begin, finish, source = bind(self.catalog, ROW, Chunk(TEXT, 0, TEXT))
            service.pending_intents['r'] = [dict(action=ROW['action'], begin=begin, finish=finish,
                                                source=source, request_id=1, waiting=False)]
            reply = service.scheduler.replies['r']
            reply.playback_origin = time.monotonic()-10
            reply.anchors = {begin:dict(start=0), finish:dict(start=4)}
            service._resolve_semantic()
            self.assertFalse(reply.jobs)
            self.assertTrue(any(d.get('reason') == 'deadline_passed' for _, d in events))

    def test_live_start_revision_replans_instead_of_losing_viable_action(self):
        # foxy-ssafsaib: present_center at [4.23,6.59], revised start 4.35.
        with tempfile.TemporaryDirectory() as directory:
            events = []
            service = GestureService(directory, planner=type('Fake', (), {'semantic':True})(),
                on_event=lambda kind, **kw: events.append((kind, kw)))
            service.scheduler.text('r', TEXT)
            begin, finish, source = bind(self.catalog, ROW, Chunk(TEXT, 0, TEXT))
            service.pending_intents['r'] = [dict(action='present_center', begin=begin, finish=finish,
                source=source, request_id=1, waiting=False)]
            reply = service.scheduler.replies['r']
            reply.playback_origin = 100.
            reply.anchors = {begin:dict(start=4.23), finish:dict(start=6.59)}
            with patch('GuideBot.gesture.service.time.monotonic', return_value=102.9):
                service._resolve_semantic()
                reply.anchors[begin]['start'] = 4.35
                service._invalidate_semantic_windows('r')
                service._resolve_semantic()
            service.scheduler.clock = lambda:104.4
            service.scheduler.tick()
            commands = [e for k,e in events if k=='gesture.command']
            self.assertEqual(len(commands), 1)
            self.assertAlmostEqual(commands[0]['end_monotonic'], 106.59)

    def test_alignment_replanning_caps_deadline_and_waits_for_retracted_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            service = GestureService(directory, planner=type('Fake', (), {'semantic':True})())
            service.scheduler.text('r', TEXT)
            begin, finish, source = bind(self.catalog, ROW, Chunk(TEXT, 0, TEXT))
            service.pending_intents['r'] = [dict(action=ROW['action'], begin=begin, finish=finish,
                source=source, request_id=1, waiting=False)]
            reply = service.scheduler.replies['r']
            reply.playback_origin = 100.
            reply.anchors = {begin:dict(start=1.), finish:dict(start=5.)}
            with patch('GuideBot.gesture.service.time.monotonic', return_value=100.):
                service._resolve_semantic()
                del reply.anchors[finish]
                service._invalidate_semantic_windows('r')
                service._resolve_semantic()
                self.assertEqual(len(service.pending_intents['r']), 1)
                reply.anchors[finish] = dict(start=6.)
                service._resolve_semantic()
                latest = reply.jobs[-1]
                self.assertEqual(latest.plan.end_s, 5.)
                service._invalidate_semantic_windows('r')
                self.assertEqual(latest.status, 'waiting')
                reply.anchors[finish]['start'] = 4.
                service._invalidate_semantic_windows('r')
                service._resolve_semantic()
                self.assertEqual(reply.jobs[-1].plan.end_s, 4.)
                # A committed command never moves in response to later anchors.
                latest = reply.jobs[-1]
                latest.status = 'committed'
                reply.anchors[finish]['start'] = 7.
                service._invalidate_semantic_windows('r')
                self.assertEqual(latest.status, 'committed')
                self.assertEqual(latest.plan.end_s, 4.)

    def test_uniform_half_second_admission_boundary(self):
        for duration, admitted in [(.499, False), (.5, True)]:
            with tempfile.TemporaryDirectory() as directory:
                service = GestureService(directory, planner=type('Fake', (), {'semantic':True})())
                service.scheduler.text('r', TEXT)
                begin, finish, source = bind(self.catalog, ROW, Chunk(TEXT, 0, TEXT))
                service.pending_intents['r'] = [dict(action=ROW['action'], begin=begin, finish=finish,
                    source=source, request_id=1, waiting=False)]
                reply = service.scheduler.replies['r']
                reply.playback_origin = time.monotonic()+10
                reply.anchors = {begin:dict(start=0.), finish:dict(start=duration)}
                service._resolve_semantic()
                self.assertEqual(bool(reply.jobs), admitted)

    def test_cancelled_inflight_keeps_global_slot_until_transport_returns(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        events = []
        class Fake:
            semantic = True
            def analyze(self, text, cancelled):
                calls.append(text)
                if len(calls) == 1:
                    entered.set()
                    release.wait(2)
                return dict(actions=[ROW])
        with tempfile.TemporaryDirectory() as directory:
            service = GestureService(directory, planner=Fake(),
                on_event=lambda kind, **kw: events.append((kind, kw)))
            service.start()
            try:
                service.submit('text', 'old', text='欢迎各位来到我们的机器人展厅。')
                self.assertTrue(entered.wait(1))
                service.submit('cancel', 'old')
                service.submit('text', 'new', text='欢迎各位来到我们的机器人展厅。')
                time.sleep(.08)
                self.assertEqual(len(calls), 1)
                release.set()
                until = time.monotonic()+2
                while len(calls)<2 and time.monotonic()<until:
                    time.sleep(.01)
                self.assertEqual(len(calls), 2)
                self.assertNotIn('old', service.pending_intents)
                self.assertNotIn('old', service.scheduler.replies)
                self.assertTrue(any(k=='gesture.semantic_discarded' for k,d in events))
            finally:
                release.set()
                service.close()

    def test_serial_requests_no_cumulative_resend_and_cancelled_reply(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        class Fake:
            semantic = True
            def analyze(self, text, cancelled):
                calls.append(text)
                started.set()
                release.wait(2)
                return dict(actions=[])
        def wait_for(predicate):
            deadline = time.monotonic()+2
            while not predicate() and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as directory:
            service = GestureService(directory, planner=Fake())
            service.start()
            try:
                first, second = '欢迎各位来到我们的机器人展厅。', '接下来我们一起看看这里的园区沙盘。'
                service.submit('text_delta', 'r', text=first)
                self.assertTrue(started.wait(1))
                service.submit('text_delta', 'r', text=second)
                time.sleep(.08)
                self.assertEqual(calls, [first])
                release.set()
                wait_for(lambda:len(calls)==2)
                self.assertEqual(calls, [first, second])
                service.submit('cancel', 'r')
                wait_for(lambda:'r' in service.scheduler.closed)
                self.assertNotIn('r', service.pending_intents)
            finally:
                release.set()
                service.close()


if __name__ == '__main__':
    unittest.main()
