"""Reproduce silent hardware-motion disablement seen in the user's session."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'GuideBot/conversation'))
import conversation
from stepfun import RealtimeSession


class MotionStartupTests(unittest.TestCase):
    def test_missing_planner_key_stops_before_manual_audio_prompt(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch('conversation.read_soul', return_value='soul'), \
             patch('conversation.load_secret', return_value='dummy'), \
             patch('conversation.load_knowledge', return_value='kb-test'), \
             patch('conversation.RealtimeSession') as session, \
             patch('conversation.wait_for_enter', side_effect=RuntimeError('voice would start')) as prompt:
            with self.assertRaisesRegex(ValueError, 'DEEPSEEK_API_KEY'):
                conversation.start_conversation(gesture_backend='unitree', skip_joint_limits=True)
            prompt.assert_not_called()
            session.assert_not_called()

    def test_failed_motion_startup_does_not_silently_start_voice(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = RealtimeSession('dummy', Path(temporary), aec=False, mic_gate_dbfs=None,
                                      vector_store_id='kb-test')
            session.gesture_backend = 'unitree'
            session.gestures = Mock()
            session.gestures.start.side_effect = RuntimeError('DEEPSEEK_API_KEY is not set')
            with patch('stepfun.websocket.WebSocketApp') as ws, patch('stepfun.threading.Thread') as thread:
                thread.return_value.is_alive.return_value = False
                try:
                    with self.assertRaisesRegex(RuntimeError, 'DEEPSEEK_API_KEY'):
                        session.start()
                    ws.assert_not_called()
                    self.assertTrue(session.errors)
                finally:
                    session.stop()


if __name__ == '__main__':
    unittest.main()
