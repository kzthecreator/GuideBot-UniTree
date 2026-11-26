"""Reproduce silent hardware-motion disablement seen in the user's session."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'GuideBot/conversation'))
from GuideBot.conversation import session as conversation
from GuideBot.conversation.stepfun import RealtimeSession


class MotionStartupTests(unittest.TestCase):
    def test_missing_planner_key_stops_before_manual_audio_prompt(self):
        with patch.dict(os.environ, {'GUIDEBOT_PLANNER_PROVIDER':'deepseek'}, clear=True), \
             patch('GuideBot.conversation.session.load_secret', return_value='dummy'), \
             patch('GuideBot.conversation.session.load_knowledge') as knowledge:
            with self.assertRaisesRegex(ValueError, 'DEEPSEEK_API_KEY'):
                conversation.prepare({'gesture_backend':'unitree'})
            knowledge.assert_not_called()

    def test_local_planner_preparation_does_not_require_cloud_key(self):
        with patch.dict(os.environ, {'GUIDEBOT_PLANNER_PROVIDER':'local_qwen'}, clear=True), \
             patch('GuideBot.conversation.session.load_secret', return_value='dummy'), \
             patch('GuideBot.conversation.session.load_knowledge', return_value='kb-test'), \
             patch('GuideBot.conversation.session.read_conversation_prompt', return_value='instructions'):
            result = conversation.prepare({'gesture_backend':'simulated'})
            self.assertEqual(result['vector_store_id'], 'kb-test')

    def test_failed_motion_startup_does_not_silently_start_voice(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = RealtimeSession('dummy', Path(temporary), aec=False, mic_gate_dbfs=None,
                                      vector_store_id='kb-test')
            session.gesture_backend = 'unitree'
            session.gestures = Mock()
            session.gestures.start.side_effect = RuntimeError('DEEPSEEK_API_KEY is not set')
            with patch('GuideBot.conversation.stepfun.websocket.WebSocketApp') as ws, patch('GuideBot.conversation.stepfun.threading.Thread') as thread:
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
