"""Offline-only execution contract against the real C++ service; no robot/audio."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from GuideBot.gesture.execution import OfflineExecutor
from drivers.unitree_motion.client import request
from tools.motion.offline_gesture_experiment import BUILD, REPO, fixture, run_experiment, wait_until


class BackendSelectionTests(unittest.TestCase):
    def test_hardware_or_legacy_server_cannot_enable_experiment_backend(self):
        executor = OfflineExecutor('\0unused', {}, lambda *a, **k: None)
        with patch.object(executor, '_request', return_value={'status': {
            'ownership': 'owned', 'state': 'idle'}}):
            with self.assertRaisesRegex(RuntimeError, 'refuses'):
                executor.start()
        self.assertIsNone(executor.thread)

    def test_start_requires_explicit_acquire(self):
        executor = OfflineExecutor('\0unused', {}, lambda *a, **k: None)
        with patch.object(executor, '_request', return_value={'status': {
            'offline_execution_v1': True, 'ownership': 'released', 'state': 'idle'}}):
            with self.assertRaisesRegex(RuntimeError, 'acquire'):
                executor.start()

    def test_stalled_socket_does_not_block_dispatch_or_cancel_callers(self):
        entered, release = threading.Event(), threading.Event()
        executor = OfflineExecutor('\0unused', {'wave': dict(asset='greet_open', minimum_total_ms=900)},
                                   lambda *a, **k: None)
        calls = []
        def transport(payload):
            calls.append(payload)
            if len(calls) == 1:
                return {'status': dict(offline_execution_v1=True, ownership='owned', state='idle')}
            entered.set()
            release.wait(timeout=2)
            raise OSError('simulated socket loss')
        now = time.monotonic()
        job = dict(response_id='r1', job_id='r1:0', action='wave', duration_s=1.,
                   start_monotonic=now+.02, arrival_monotonic=now+.27, compressed=False)
        with patch.object(executor, '_request', side_effect=transport):
            try:
                executor.start()
                self.assertTrue(executor.submit(job))
                self.assertTrue(entered.wait(timeout=1))
                began = time.monotonic()
                executor.cancel('r1')
                self.assertFalse(executor.submit(dict(job, response_id='r2', job_id='r2:0')))
                self.assertLess(time.monotonic()-began, .05)
            finally:
                release.set()
                executor.close()


@unittest.skipUnless((BUILD/'motion_library_server').is_file(), 'Build the motion service first')
class EndToEndTests(unittest.TestCase):
    def test_scheduler_driver_cancel_deadlines_busy_and_disconnect(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_experiment(Path(temporary))
            self.assertTrue(result['no_robot'])
            self.assertTrue(result['checks']['scheduler_to_cpp_completed'])
            self.assertTrue(result['checks']['cancel_before_dispatch'])
            self.assertTrue(result['checks']['connection_loss_fails_closed'])
            self.assertGreater(result['checks']['observed_running_seconds'], 1.2)
            self.assertLess(result['checks']['observed_running_seconds'], 1.6)
            self.assertLess(result['checks']['cancel_to_idle_ms'], 2000)


@unittest.skipUnless((BUILD/'motion_library_server').is_file(), 'Build the motion service first')
class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = fixture(self.root)
        self.socket = '\0'+self.args[self.args.index('--socket-name')+1]
        self.process = subprocess.Popen(self.args, cwd=REPO, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        self.addCleanup(self.cleanup_server)
        def ready():
            try:
                return self.status()
            except OSError:
                return None
        wait_until(ready)
        request(self.socket, {'接管': True})
        wait_until(lambda: self.status()['ownership'] == 'owned')

    def cleanup_server(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=2)

    def status(self):
        return request(self.socket, {'状态': True})['status']

    def job(self, name='test_job'):
        return {'execution': dict(job_id=name, start_before=time.monotonic()+1,
            expected_ms=1250, sequence=dict(sequence_name=name, steps=[dict(
                type='motion', name='greet_open', transition_ms=250,
                duration_ms=1000, hold_ms=0)]))}

    def test_duplicate_id_cannot_replay_action(self):
        job = self.job()
        self.assertEqual(request(self.socket, job)['message'], 'queued')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            request(self.socket, job)
        request(self.socket, {'停止': True})
        wait_until(lambda: self.status()['executions']['test_job']['state'] == 'cancelled')
        self.assertNotIn('completed_at', self.status()['executions']['test_job'])

    def test_driver_rechecks_minimum_and_integer_duration(self):
        job = self.job()
        job['execution']['expected_ms'] = 350
        job['execution']['sequence']['steps'][0]['duration_ms'] = 100
        with self.assertRaisesRegex(ValueError, 'minimum duration'):
            request(self.socket, job)
        job = self.job()
        job['execution']['expected_ms'] = 1250.9
        with self.assertRaisesRegex(ValueError, 'field types'):
            request(self.socket, job)
        self.assertEqual(self.status()['executions'], {})

    def test_accepted_does_not_mean_started_if_resolution_fails(self):
        # These deliberately invalid limits are confined to the offline fixture.
        path = self.root/'OFFLINE_FIXTURE_LIMITS.json'
        limits = json.loads(path.read_text())
        limits['max_rad'] = [.05]*14
        path.write_text(json.dumps(limits))
        self.assertTrue(request(self.socket, self.job())['ok'])
        wait_until(lambda: self.status()['executions']['test_job']['state'] == 'rejected')
        receipt = self.status()['executions']['test_job']
        self.assertNotIn('running_at', receipt)
        self.assertIn('error', receipt)

    def test_long_session_prunes_receipts_but_does_not_replay_old_ids(self):
        path = self.root/'OFFLINE_FIXTURE_LIMITS.json'
        limits = json.loads(path.read_text())
        limits['max_rad'] = [.05]*14
        path.write_text(json.dumps(limits))
        for i in range(66):
            name = 'history_'+str(i)
            request(self.socket, self.job(name))
            wait_until(lambda: self.status()['executions'].get(name, {}).get('state') == 'rejected')
        self.assertLessEqual(len(self.status()['executions']), 64)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            request(self.socket, self.job('history_0'))

    def test_unverified_limits_are_not_bypassed(self):
        path = self.root/'OFFLINE_FIXTURE_LIMITS.json'
        limits = json.loads(path.read_text())
        limits['verified'] = False
        path.write_text(json.dumps(limits))
        with self.assertRaises(ValueError):
            request(self.socket, self.job())
        self.assertEqual(self.status()['executions'], {})

    def test_duplicate_concurrent_motion_rejected_instead_of_queued(self):
        request(self.socket, self.job())
        with self.assertRaisesRegex(ValueError, 'busy'):
            request(self.socket, self.job('second_job'))
        self.assertNotIn('second_job', self.status()['executions'])


if __name__ == '__main__':
    unittest.main()
