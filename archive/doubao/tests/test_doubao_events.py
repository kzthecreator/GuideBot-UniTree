"""Regression coverage for observed Doubao realtime event payloads."""

from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
import tempfile
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'GuideBot/conversation'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from doubao import DoubaoSession
from audio import AudioDiagnostic, StreamingSpeaker
import threading


class DoubaoEventTests(unittest.TestCase):
    def session(self):
        session = DoubaoSession('dummy', Path('/tmp/unused-doubao'), aec=False)
        session.speaker = Mock()
        session.speaker.pending_response_ids.return_value = set()
        session.speaker.is_playing.return_value = False
        session.report = Mock()
        session.timestamps = Mock()
        session.gestures = Mock()
        return session

    def begin(self, session):
        session.on_event(dict(type='response.output_audio.started',
                              question_id='q1', response_id='r1'))

    def test_asr_interrupts_buffered_audio_after_cloud_done(self):
        session = self.session()
        session.speaker = StreamingSpeaker(threading.Event(), session.fail)
        self.begin(session)
        session.on_event(dict(type='response.output_audio.delta', question_id='q1',
                              delta='AQABAA=='))
        session.on_event(dict(type='response.done', response={'usage': {}}))
        self.assertFalse(session.active)
        self.assertIn('r1', session.speaker.responses)
        session.on_event(dict(type='conversation.item.input_audio_transcription.started', item_id='u2'))
        self.assertFalse(session.speaker.responses, 'Old reply must stop at ASR started, before ASR completed')

    def test_usage_only_done_finishes_without_stopping_conversation(self):
        session = self.session()
        self.begin(session)
        session.on_event(dict(type='response.output_audio.delta', question_id='q1',
                              response_id='', delta='AQABAA=='))
        session.speaker.feed.assert_called_once_with('r1', b'\x01\x00\x01\x00')
        session.on_event(dict(type='response.output_audio.done', question_id='q1', response_id=''))
        session.on_event(dict(type='response.done', response={'usage': {'total_tokens': 3339}}))
        self.assertFalse(session.stopping.is_set())
        self.assertEqual(session.errors, [])
        self.assertEqual(session.stats['responses'], [{'id': 'r1', 'status': 'completed'}])
        session.gestures.submit.assert_called_with('done', 'r1')
        session.timestamps.send.assert_called_with('done', 'r1')

    def test_usage_only_done_after_interrupt_does_not_complete_old_gesture(self):
        session = self.session()
        self.begin(session)
        session.on_event(dict(type='conversation.item.input_audio_transcription.started', item_id='u2'))
        session.on_event(dict(type='response.done', response={'usage': {}}))
        session.gestures.submit.assert_called_with('cancel', 'r1')
        self.assertFalse(session.stopping.is_set())
        session.on_event(dict(type='response.output_audio.delta', question_id='q1',
                              response_id='', delta='AQABAA=='))
        session.speaker.feed.assert_not_called()

    def test_recorded_upload_matches_successfully_sent_pcm(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.session()
            session.audio_diagnostic = AudioDiagnostic(Path(directory), session.started_at, uploaded=True)
            pcm = b'\x23\x01' * 320
            session.input_queue.put(pcm)
            sent = []

            def send(kind, **fields):
                import base64
                sent.append(base64.b64decode(fields['audio']))
                session.stopping.set()
                return True

            session._send = send
            session._send_microphone()
            session.audio_diagnostic.close()
            with wave.open(str(Path(directory) / 'microphone-uploaded-16k.wav')) as track:
                self.assertEqual(track.getframerate(), 16000)
                self.assertEqual(track.readframes(track.getnframes()), b''.join(sent))
            self.assertEqual(sent, [pcm])

    def test_partial_hypotheses_are_replaced_and_displayed_before_final(self):
        session = self.session()
        session.on_event(dict(type='conversation.item.input_audio_transcription.started', item_id='u1'))
        for text in ['你', '你帮我', '你帮我录']:
            session.on_event(dict(type='conversation.item.input_audio_transcription.delta', item_id='u1', delta=text))
        self.assertEqual(session.asr_partials['u1'], '你帮我录')
        session.report.assert_called_with('ASR-partial', 'User（暂定）: 你帮我录', turn=1)
        session.on_event(dict(type='conversation.item.input_audio_transcription.completed', item_id='u1'))
        session.report.assert_called_with('ASR-final', 'User: 你帮我录', turn=1)

    def test_close_suppresses_upload_and_expected_transport_error(self):
        session = self.session()
        session.ws = Mock()
        session.session_closing = True
        self.assertFalse(session._send('input_audio_buffer.append', audio='AAAA'))
        session.ws.send.assert_not_called()
        self.assertTrue(session._send('session.close'))
        session._socket_error(RuntimeError('Connection to remote host was lost.'))
        self.assertEqual(session.errors, [])
        session.session_closing = False
        session._socket_error(RuntimeError('unexpected disconnect'))
        self.assertEqual(session.errors, ['unexpected disconnect'])


if __name__ == '__main__':
    unittest.main()
