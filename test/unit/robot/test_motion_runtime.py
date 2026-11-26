import unittest
import io
import tempfile
from pathlib import Path

from runtime.app.workers.motion import MotionRuntime


class Process:
    returncode = None

    class Input:
        def write(self, value):
            assert value == 'RUN\n'

        def flush(self):
            pass

        def close(self):
            pass

    stdin = Input()

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0

    def terminate(self):
        self.returncode = 1

    def kill(self):
        self.returncode = 1


class MotionRuntimeTests(unittest.TestCase):
    def test_session_owns_and_releases_server(self):
        state = {'ownership': 'released'}
        commands = []
        process = Process()

        def request(payload):
            command = next(iter(payload))
            commands.append(command)
            if command == '状态' and len(commands) == 1:
                raise OSError('No server')
            if command == '接管':
                state['ownership'] = 'owned'
            if command == '释放':
                state['ownership'] = 'released'
            return {'status': dict(state)}

        runtime = MotionRuntime(request=request, popen=lambda *a, **k: process,
                                sleep=lambda _: None)
        runtime.start()
        self.assertEqual(state['ownership'], 'owned')
        runtime.stop()
        self.assertEqual(state['ownership'], 'released')
        self.assertEqual(process.returncode, 0)
        self.assertEqual([c for c in commands if c != '状态'],
                         ['接管', '停止', '释放', '退出'])

    def test_acquire_rejection_preserves_native_output(self):
        process = Process()
        process.returncode = None
        process.stdout = io.StringIO('[ACQUIRE-GUARD] reasons=leg_speed,\n')
        first = [True]
        def request(payload):
            if payload == {'状态': True} and first[0]:
                first[0] = False
                raise OSError('not running')
            return {'status': {'ownership': 'released'}}
        with tempfile.TemporaryDirectory() as directory:
            runtime = MotionRuntime(request=request, popen=lambda *a, **k: process,
                                    sleep=lambda _: None)
            runtime.log_directory = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'rejected upper-body acquire'):
                runtime.start()
            self.assertIn('reasons=leg_speed', (Path(directory)/'motion-native.log').read_text())
            self.assertEqual(process.returncode, 0)

    def test_existing_server_is_not_taken_over(self):
        runtime = MotionRuntime(request=lambda _: {'status': {'ownership': 'released'}},
                                popen=lambda *a, **k: self.fail('must not start'))
        with self.assertRaisesRegex(RuntimeError, 'already running'):
            runtime.start()


if __name__ == '__main__':
    unittest.main()
