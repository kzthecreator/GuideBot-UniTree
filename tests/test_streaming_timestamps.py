import io
import json
from pathlib import Path
import queue
import sys
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'GuideBot/conversation'))
from timestamps import ResponseAlignment, StreamingTimestamps, text_units
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
