import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'GuideBot/conversation'))
from timestamps import ResponseAlignment, StreamingTimestamps, text_units, _worker
from stepfun import RealtimeSession
from audio import StreamingSpeaker


class Backend:
    def align(self, pcm, labels, final=False):
        duration = len(pcm) / 32000
        count = len(labels) if final else min(len(labels), int(duration))
        spacing = duration / count
        return [{**u, 'start': i*spacing, 'end': (i+1)*spacing}
                for i,u in enumerate(labels[:count])], float(count+1)


class TimestampTests(unittest.TestCase):
    def test_start_cursor_progresses_without_complete_intervals(self):
        state = ResponseAlignment('r', text='一二三四五六七八九十',
                                  data=bytearray(8*32000), window=4,
                                  cursor_from_starts=True, resync_every=0)
        state.latest_starts = {2: dict(index=2, text='三', text_offset=2, start=3.8)}
        result = state.update(Backend())
        self.assertEqual(result['profile']['cursor'], 2)
        self.assertAlmostEqual(result['window_start'], 3.72)

    def test_worker_uses_latest_coalesced_input_after_inflight_inference(self):
        incoming, outgoing = queue.Queue(), queue.Queue()
        def send(kind, payload):
            incoming.put((kind, 'r', payload, time.monotonic()))
        send('text', '你好世界欢迎参观')
        send('audio', bytes(32000))
        seen = []
        class Backend:
            def align(self, pcm, labels, final=False):
                seen.append(len(pcm)/32000)
                if len(seen) == 1:
                    for _ in range(3):
                        send('audio', bytes(16000))
                    send('text_delta', '这里')
                else:
                    send('stop', None)
                return [], 0.
        with tempfile.TemporaryDirectory() as directory, patch('timestamps.MonotonicBackend', return_value=Backend()):
            _worker(incoming, outgoing, 'unused', str(Path(directory)/'worker.log'),
                    dict(step=.5, resync_every=0))
        self.assertEqual(seen, [1., 2.5])
        results = []
        while not outgoing.empty():
            event = outgoing.get_nowait()
            if event['kind'] == 'alignment.update':
                results.append(event)
        self.assertEqual(results[-1]['profile']['batch_audio_messages'], 3)
        self.assertEqual(results[-1]['profile']['coalesced_step_thresholds'], 2)
        self.assertEqual(results[-1]['profile']['text_revision'], 2)

    def test_profile_retains_inference_cost_for_rejected_window(self):
        state = ResponseAlignment('r', text='一二三四五六七八九十',
                                  data=bytearray(4*32000), resync_every=0)
        state.update(Backend())
        state.data.extend(bytes(4*32000))
        result = state.update(Backend())
        self.assertEqual(result['reason'], 'order_conflict')
        self.assertTrue(result['profile']['inference_ran'])
        self.assertGreater(result['profile']['backend_seconds'], 0)
        self.assertGreaterEqual(result['profile']['update_seconds'], result['profile']['backend_seconds'])

    def test_start_events_are_observations_not_errors(self):
        session = RealtimeSession('dummy', Path('/tmp/unused'))
        session.report = Mock()
        session._alignment_event('alignment.starts', response_id='r', anchors=[],
                                 total_units=1, changes=[])
        self.assertEqual(session.timestamp_stats['errors'], [])
        self.assertEqual(session.timestamp_stats['start_updates'], 1)

    def test_replaced_text_retracts_published_start_indices(self):
        state = ResponseAlignment('r', text='你好', data=bytearray(2*32000), tail=0)
        state.update(Backend())
        state.set_text('再见')
        result = state.update(Backend())
        self.assertEqual(result['start_update']['removed_indices'], [0, 1])
        self.assertEqual([r['text'] for r in result['start_update']['anchors']], ['再', '见'])

    def test_text_delta_reaches_worker_before_done_and_is_recorded(self):
        session = RealtimeSession('dummy', Path('/tmp/unused'))
        session.timestamps = Mock()
        session.active.add('r')
        session.log = io.StringIO()
        session.on_event({'type': 'response.audio_transcript.delta',
                          'response_id': 'r', 'delta': '请注意这里'})
        session.timestamps.send.assert_called_once_with('text_delta', 'r', '请注意这里')
        record = json.loads(session.log.getvalue())
        self.assertEqual(record['delta'], '请注意这里')
        session.timestamps.send.reset_mock()
        session.discarded.add('r')
        session.on_event({'type': 'response.audio_transcript.delta',
                          'response_id': 'r', 'delta': '旧回复'})
        session.timestamps.send.assert_not_called()

    def test_append_preserves_aligned_prefix_and_retries_with_new_text(self):
        state = ResponseAlignment('r', text='你好', data=bytearray(2*32000))
        state.update(Backend())
        previous = dict(state.latest)
        state.set_text('你好世界')
        self.assertEqual(state.latest, previous)
        self.assertEqual(state.last_samples, 2*16000)
        self.assertTrue(state.due())

    def test_append_to_partial_english_word_invalidates_only_that_unit(self):
        state = ResponseAlignment('r', text='你好Guide', data=bytearray(4*32000), tail=0)
        state.update(Backend())
        state.set_text('你好GuideBot')
        self.assertEqual([row['text'] for row in state.latest.values()], ['你', '好'])
        self.assertTrue(state.due())

    def test_start_anchor_does_not_wait_for_end_tail(self):
        state = ResponseAlignment('r', text='你好', data=bytearray(2*32000), tail=1.5)
        result = state.update(Backend())
        self.assertEqual(result['timestamps'], [])
        anchors = result['start_update']['anchors']
        self.assertEqual([row['text'] for row in anchors], ['你'])
        self.assertNotIn('end', anchors[0])
        self.assertTrue(result['start_update']['provisional'])

    def test_experiment_options_reject_invalid_scheduling(self):
        for options in ({'step': 0}, {'window': -1}, {'tail': float('nan')},
                        {'resync_every': float('inf')}, {'unknown': 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                StreamingTimestamps('/tmp/unused', Mock(), alignment_options=options)

    def test_shorter_step_and_tail_publish_earlier(self):
        default = ResponseAlignment('default', text='你好', data=bytearray(32000))
        candidate = ResponseAlignment('candidate', step=.5, tail=0,
                                      text='你好', data=bytearray(32000))
        self.assertFalse(default.due())
        self.assertTrue(candidate.due())
        result = candidate.update(Backend())
        self.assertEqual(len(result['timestamps']), 1)

    def test_token_offsets_preserve_source(self):
        text = '你好，GuideBot。'
        units = text_units(text)
        self.assertEqual([u['text'] for u in units], ['你','好','GuideBot'])
        self.assertTrue(all(text[u['text_offset']:].startswith(u['text']) for u in units))

    def test_tail_is_provisional_and_final_repairs_all(self):
        state=ResponseAlignment('r')
        state.set_text('一二三四五六七八九十')
        state.data.extend(bytes(4*32000))
        first=state.update(Backend())
        self.assertTrue(first['provisional'])
        self.assertEqual(len(first['timestamps']),3)
        self.assertTrue(all(r['end']<=3 for r in first['timestamps']))
        state.data.extend(bytes(6*32000))
        state.done=True
        final=state.update(Backend())
        self.assertFalse(final['provisional'])
        self.assertEqual(len(final['timestamps']),10)
        self.assertTrue(final['ordered'])
        self.assertEqual(final['window_start'],0)

    def test_recent_window_uses_previous_prediction(self):
        state=ResponseAlignment('r')
        state.set_text('一二三四五六七八九十')
        state.data.extend(bytes(4*32000))
        state.update(Backend())
        state.data.extend(bytes(4*32000))
        backend=Mock()
        backend.align.return_value=([],0)
        result=state.update(backend)
        self.assertGreater(result['window_start'],0)
        self.assertLessEqual(result['window_seconds'],8)

    def test_conflicting_window_is_not_published_and_requests_repair(self):
        state=ResponseAlignment('r',text='一二三四五六七八九十',data=bytearray(4*32000))
        state.update(Backend())
        previous=dict(state.latest)
        state.data.extend(bytes(4*32000))
        result=state.update(Backend())
        self.assertEqual(result['reason'],'order_conflict')
        self.assertEqual(state.latest,previous)
        self.assertTrue(state.due())
        repaired=state.update(Backend())
        self.assertEqual(repaired['scope'],'prefix_resync')
        self.assertEqual(repaired['resync_reason'],'order_conflict')
        self.assertTrue(repaired['ordered'])

    def test_lost_cursor_does_not_expand_window(self):
        state=ResponseAlignment('r',text='你好',data=bytearray(9*32000))
        result=state.update(Backend())
        self.assertEqual(result['reason'],'cursor_lost')

    def test_periodic_resync_is_explicitly_reported(self):
        state=ResponseAlignment('r',text='一二三四五六七八九十',data=bytearray(10*32000))
        result=state.update(Backend())
        self.assertEqual(result['scope'],'prefix_resync')
        self.assertEqual(result['window_start'],0)
        self.assertEqual(state.last_resync,10)

    def test_disabled_resync_never_expands_to_prefix(self):
        state = ResponseAlignment('r', text='一二三四五六七八九十',
                                  data=bytearray(10*32000), resync_every=0)
        backend = Mock()
        result = state.update(backend)
        self.assertEqual(result['reason'], 'cursor_lost')
        backend.align.assert_not_called()

    def test_disabled_conflict_repair_waits_for_new_audio(self):
        state = ResponseAlignment('r', text='一二三四五六七八九十',
                                  data=bytearray(4*32000), resync_every=0)
        state.update(Backend())
        state.data.extend(bytes(4*32000))
        result = state.update(Backend())
        self.assertEqual(result['reason'], 'order_conflict')
        self.assertFalse(state.force_resync)
        self.assertFalse(state.due())

    def test_disabled_final_repair_keeps_local_window_and_missing_units(self):
        state = ResponseAlignment('r', text='一二三四五六七八九十', window=4,
                                  data=bytearray(4*32000), resync_every=0, final_repair=False)
        state.update(Backend())
        state.data.extend(bytes(2*32000))
        state.done = True
        backend = Mock(wraps=Backend())
        result = state.update(backend)
        self.assertEqual(result['kind'], 'alignment.final')
        self.assertEqual(result['scope'], 'final_window')
        self.assertTrue(result['provisional'])
        self.assertFalse(backend.align.call_args.args[2])
        self.assertLess(len(backend.align.call_args.args[0]), len(state.data))
        self.assertLess(len(result['timestamps']), 10)

    def test_text_replacement_discards_previous_indices(self):
        state=ResponseAlignment('r',text='旧文字',last_samples=100,latest={1:{'text':'旧'}})
        state.set_text('新文本')
        self.assertFalse(state.latest)
        self.assertEqual(state.last_samples,0)

    def test_cancel_suppresses_future_audio(self):
        worker=StreamingTimestamps('/tmp/unused',Mock())
        worker.enabled=True
        worker.incoming=queue.Queue()
        worker.send('cancel','r')
        worker.send('audio','r',bytes(16))
        self.assertEqual(worker.incoming.qsize(),1)

    def test_timestamp_failure_does_not_stop_audio(self):
        session=RealtimeSession('dummy',Path('/tmp/unused'))
        session.timestamp_log=io.StringIO()
        session.report=Mock()
        session._alignment_event('alignment.error',message='model failed')
        self.assertFalse(session.stopping.is_set())
        self.assertEqual(session.timestamp_stats['errors'],['model failed'])
        self.assertEqual(json.loads(session.timestamp_log.getvalue())['message'],'model failed')

    def test_only_completed_response_gets_full_repair(self):
        session=RealtimeSession('dummy',Path('/tmp/unused'))
        session.timestamps=Mock()
        session.speaker=Mock()
        session.report=Mock()
        session.active.add('r')
        session.on_event({'type':'response.audio.done','response_id':'r'})
        session.timestamps.send.assert_not_called()
        session.on_event({'type':'response.done','response':{'id':'r','status':'incomplete'}})
        session.timestamps.send.assert_called_once_with('cancel','r')

    def test_feed_returns_exact_final_speaker_pcm(self):
        speaker=StreamingSpeaker(threading.Event(),Mock())
        converted=speaker.feed('r',b'\x10\x00'*2400)
        self.assertEqual(converted,bytes(speaker.responses['r'].data))
        self.assertEqual(len(converted),speaker.responses['r'].received_bytes)


if __name__=='__main__':
    unittest.main()
