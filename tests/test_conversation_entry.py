"""Production entry contract; never connects to audio hardware or the network."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'GuideBot/conversation'))
import conversation
from stepfun import RealtimeSession


class EntryTests(unittest.TestCase):
    def test_standard_frontend_is_explicit_and_manual_start_is_preserved(self):
        with patch.dict(os.environ, {'LOCALVQE_MODEL': '/tmp/experimental-model.gguf'}), \
             patch('conversation.read_soul', return_value='soul'), \
             patch('conversation.load_secret', return_value='dummy'), \
             patch('conversation.load_knowledge', return_value='kb-test'), \
             patch('conversation.RealtimeSession') as session, \
             patch('conversation.wait_for_enter', side_effect=RuntimeError('cancel')):
            with self.assertRaisesRegex(RuntimeError, 'cancel'):
                conversation.start_conversation(diagnose_audio=False, gestures=True, timestamps=True)
            options = session.call_args.kwargs
            self.assertTrue(options['aec'])
            self.assertTrue(options['agc'])
            self.assertIsNone(options['mic_gate_dbfs'])
            self.assertEqual(options['aec_delay_ms'], 0)
            self.assertEqual(options['aec_model'], conversation.STANDARD_AEC_MODEL)
            self.assertFalse(options['diagnose_audio'])
            self.assertTrue(options['gestures'])
            self.assertTrue(options['timestamps'])
            session.return_value.start.assert_not_called()

    def test_cli_keeps_stepfun_and_motion_options(self):
        with patch.object(sys, 'argv', ['conversation.py', '--no-diagnose-audio',
                                      '--voice', 'test-voice', '--vad-energy', '100',
                                      '--timestamps', '--gestures']), \
             patch('conversation.start_conversation') as start:
            conversation.main()
            self.assertFalse(start.call_args.kwargs['diagnose_audio'])
            self.assertEqual(start.call_args.kwargs['voice'], 'test-voice')
            self.assertEqual(start.call_args.kwargs['vad_energy'], 100)
            self.assertTrue(start.call_args.kwargs['gestures'])

    def test_recording_disabled_keeps_events_and_errors_without_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = RealtimeSession('dummy', root, instructions='soul',
                                      vector_store_id='kb-test', diagnose_audio=False,
                                      aec=False, mic_gate_dbfs=None)
            with patch('stepfun.websocket.WebSocketApp'), patch('stepfun.threading.Thread') as thread:
                thread.return_value.is_alive.return_value = False
                session.start()
                session.fail(RuntimeError('offline test error'))
                result = session.stop()
            self.assertIsNone(session.audio_diagnostic)
            self.assertFalse(list(root.glob('*.wav')))
            events = [json.loads(line) for line in (root / 'events.jsonl').read_text().splitlines()]
            self.assertTrue(events)
            self.assertIn('offline test error', result['errors'])


if __name__ == '__main__':
    unittest.main()
