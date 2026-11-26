"""Regression for stale execution_v1 shutdown access after the fork migration."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'GuideBot/conversation'))
from GuideBot.conversation.stepfun import RealtimeSession
from GuideBot.gesture.service import GestureService


class ForkMotionShutdownTests(unittest.TestCase):
    def test_fork_executor_closes_without_legacy_failed_attribute(self):
        with tempfile.TemporaryDirectory() as directory:
            session = RealtimeSession('dummy', Path(directory), aec=False,
                                      mic_gate_dbfs=None, gestures=True, gesture_service_factory=GestureService,
                                      gesture_backend='simulated')
            session.timestamps = None
            self.assertIsNone(session.gestures.executor)
            result = session.stop()
            self.assertEqual(result['errors'], [])


if __name__ == '__main__':
    unittest.main()
