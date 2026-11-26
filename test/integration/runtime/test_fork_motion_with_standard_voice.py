"""Fork lifecycle must preserve the standard audio path and manual-start boundary."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'GuideBot/conversation'))
from GuideBot.conversation import session as conversation
from runtime.app.workers.motion import MotionRuntime
from GuideBot.robot.motion.paths import ASSETS, BUILD, LIMITS


class ForkVoiceBridgeTests(unittest.TestCase):
    def run_conversation(self, fail_voice=False):
        from runtime.app.workers.voice import VoiceWorker
        events = []
        with tempfile.TemporaryDirectory() as temporary:
            session, runtime = Mock(), Mock()
            session.ready.wait.return_value = True
            session.stop.side_effect = lambda: events.append('voice.stop') or {'errors': []}
            def voice_start():
                events.append('voice.start')
                if fail_voice:
                    raise RuntimeError('voice startup failed')
            session.start.side_effect = voice_start
            runtime.start.side_effect = lambda: events.append('motion.start')
            runtime.stop.side_effect = lambda: events.append('motion.stop')
            root = Path(temporary)
            (root/'session').mkdir()
            with patch('runtime.app.workers.voice.build_session', return_value=session), \
                 patch('runtime.app.workers.voice.MotionRuntime', return_value=runtime):
                worker = VoiceWorker({'gesture_backend':'unitree'}, root, 's', {})
                self.assertEqual(events, [])
                request = dict(op='activate', session_id='s', generation=1)
                worker.rpc(dict(request, op='authorize'))
                try:
                    if fail_voice:
                        with self.assertRaisesRegex(RuntimeError, 'voice startup failed'):
                            worker.rpc(request)
                    else:
                        worker.rpc(request)
                        worker.rpc(dict(request, op='deactivate'))
                finally:
                    worker.close()
        self.assertEqual(events, ['motion.start','voice.start','voice.stop','motion.stop'])

    def test_real_motion_starts_only_on_resource_activation(self):
        self.run_conversation()

    def test_voice_start_failure_still_releases_motion(self):
        self.run_conversation(fail_voice=True)

    def test_fork_runtime_passes_external_asset_paths(self):
        process = Mock()
        process.poll.return_value = None
        process.returncode = 0
        status_calls = iter([OSError('not running'), {'ownership': 'released'},
                             {'ownership': 'owned'}])
        def request(payload):
            if payload == {'状态': True}:
                result = next(status_calls)
                if isinstance(result, Exception):
                    raise result
                return {'status': result}
            return {'ok': True}
        popen = Mock(return_value=process)
        runtime = MotionRuntime(request=request, popen=popen, sleep=lambda _: None)
        runtime.start()
        command = popen.call_args.args[0]
        self.assertEqual(command[0], str(BUILD/'motion_library_server'))
        self.assertEqual(command[command.index('--dir')+1], str(ASSETS/'motions'))
        self.assertEqual(command[command.index('--limits')+1], str(LIMITS))
        process.poll.return_value = 0
        runtime.stop()


if __name__ == '__main__':
    unittest.main()
