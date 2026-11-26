"""Production entry and fixed frontend without cloud or hardware."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runtime.app.launcher import parser
from GuideBot.conversation.session import build_session, STANDARD_AEC_MODEL
from GuideBot.conversation.stepfun import RealtimeSession


class EntryTests(unittest.TestCase):
    def test_standard_frontend_is_fixed(self):
        with patch('GuideBot.conversation.session.RealtimeSession') as factory:
            build_session(dict(diagnose_audio=False, gestures=True, timestamps=True), Path('/tmp/test'),
                          dict(secret='dummy', instructions='soul', vector_store_id='kb-test'), object())
        options = factory.call_args.kwargs
        self.assertTrue(options['aec'])
        self.assertTrue(options['agc'])
        self.assertIsNone(options['mic_gate_dbfs'])
        self.assertEqual(options['aec_delay_ms'], 0)
        self.assertEqual(options['aec_model'], STANDARD_AEC_MODEL)
        self.assertFalse(options['diagnose_audio'])
        self.assertTrue(options['timestamps'])
        self.assertEqual(options['gesture_backend'], 'simulated')

    def test_cli_keeps_options_and_defaults_to_voice_only(self):
        self.assertIsNone(parser().parse_args([]).gesture_backend)
        self.assertFalse(parser().parse_args([]).gestures)
        args = parser().parse_args(['--no-diagnose-audio', '--voice', 'test', '--vad-energy','100','--gestures'])
        self.assertFalse(args.diagnose_audio)
        self.assertEqual(args.vad_energy, 100)
        self.assertEqual(args.voice, 'test')
        self.assertTrue(args.gestures)

    def test_recording_disabled_keeps_events_without_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = RealtimeSession('dummy', root, instructions='soul', vector_store_id='kb-test',
                                      diagnose_audio=False, aec=False, mic_gate_dbfs=None)
            with patch('GuideBot.conversation.stepfun.websocket.WebSocketApp'), patch('GuideBot.conversation.stepfun.threading.Thread') as thread:
                thread.return_value.is_alive.return_value = False
                session.start()
                session.fail(RuntimeError('offline test error'))
                result = session.stop()
            self.assertFalse(list(root.glob('*.wav')))
            self.assertTrue((root/'events.jsonl').exists())
            self.assertIn('offline test error', result['errors'])
