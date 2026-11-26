"""Long cloud bursts must remain interruptible without terminating the session."""
from pathlib import Path
import sys
import threading
import base64
from unittest.mock import Mock
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'GuideBot/conversation'))
from GuideBot.conversation.audio import StreamingSpeaker, RATE, _PCMSpool, SpeakerBacklogExceeded
from GuideBot.conversation.stepfun import RealtimeSession


class SpeakerBacklogTests(unittest.TestCase):
    def test_45_second_burst_spools_and_interrupt_closes_it(self):
        speaker = StreamingSpeaker(threading.Event(),lambda error:self.fail(str(error)),gain=1)
        pcm = b'\x01\x00'*24000
        try:
            for _ in range(45):
                speaker.feed('long',pcm)
            self.assertGreater(speaker.buffered_bytes,RATE*2*30)
            entry = speaker.responses['long']
            self.assertTrue(entry.data.disk_backed)
            before = speaker.generation
            speaker.interrupt()
            self.assertEqual(speaker.buffered_bytes,0)
            self.assertTrue(entry.data.closed)
            self.assertEqual(speaker.generation,before+1)
        finally:
            speaker.close()

    def test_spilled_pcm_preserves_bytes_across_reads_and_appends(self):
        buffer = _PCMSpool()
        source = bytes(range(251))*1000
        try:
            buffer.extend(source)
            first = buffer.take(1234)
            buffer.extend(b'end')
            self.assertEqual(first+buffer.take(len(buffer)),source+b'end')
            self.assertEqual(len(buffer),0)
            buffer.extend(b'next')
            self.assertEqual(buffer.take(100),b'next')
        finally:
            buffer.close()

    def test_pathological_reply_is_discarded_without_stopping_session(self):
        session = RealtimeSession('dummy',Path('/tmp/unused-backlog-test'),aec=False,
                                  mic_gate_dbfs=None)
        session.speaker = Mock()
        session.speaker.feed.side_effect = SpeakerBacklogExceeded('limit')
        session.gestures = Mock()
        session.timestamps = Mock()
        session.report = Mock()
        session.active.add('long')
        session.on_event(dict(type='response.audio.delta',response_id='long',
                              delta=base64.b64encode(b'\x01\x00'*10).decode()))
        self.assertFalse(session.stopping.is_set())
        self.assertEqual(session.errors,[])
        self.assertIn('long',session.discarded)
        session.speaker.cancel.assert_called_once_with('long','reply_storage_limit')
        session.gestures.submit.assert_called_once_with('cancel','long',reason='reply_storage_limit')
        session.timestamps.send.assert_called_once_with('cancel','long')


if __name__=='__main__':
    unittest.main()
