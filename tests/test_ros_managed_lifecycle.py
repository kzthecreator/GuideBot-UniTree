"""Resource authorization, failure cleanup, and local protection without devices."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from GuideBot.runtime.workers.voice import VoiceWorker


class ResourceTests(unittest.TestCase):
    def worker(self, directory, **options):
        (Path(directory)/'session').mkdir()
        return VoiceWorker(options, directory, 's', {})

    def request(self, op, **fields):
        return dict(dict(op=op, session_id='s', generation=1), **fields)

    def test_idle_and_wrong_generation_never_build_audio(self):
        with tempfile.TemporaryDirectory() as root, patch('GuideBot.runtime.workers.voice.build_session') as build:
            worker = self.worker(root)
            try:
                self.assertFalse(worker.rpc(self.request('health'))['active'])
                with self.assertRaises(ValueError):
                    worker.rpc(self.request('activate', generation=2))
                with self.assertRaisesRegex(ValueError, 'authorized'):
                    worker.rpc(self.request('activate'))
                build.assert_not_called()
            finally:
                worker.close()

    def test_voice_only_never_acquires_motion_and_activation_is_one_shot(self):
        with tempfile.TemporaryDirectory() as root, \
             patch('GuideBot.runtime.workers.voice.build_session') as build, \
             patch('GuideBot.runtime.workers.voice.MotionRuntime') as motion:
            session = build.return_value
            session.ready.wait.return_value = True
            session.stop.return_value = {'errors': []}
            worker = self.worker(root)
            try:
                worker.rpc(self.request('authorize'))
                worker.rpc(self.request('activate'))
                motion.assert_not_called()
                with self.assertRaises(ValueError):
                    worker.rpc(self.request('activate'))
                worker.rpc(self.request('deactivate'))
                worker.rpc(self.request('deactivate'))
                session.stop.assert_called_once()
            finally:
                worker.close()

    def test_heartbeat_loss_stops_and_releases_without_ros(self):
        with tempfile.TemporaryDirectory() as root, \
             patch('GuideBot.runtime.workers.voice.build_session') as build, \
             patch('GuideBot.runtime.workers.voice.MotionRuntime') as motion:
            session = build.return_value
            session.ready.wait.return_value = True
            session.stop.return_value = {'errors': []}
            worker = self.worker(root, gesture_backend='unitree')
            try:
                worker.rpc(self.request('authorize'))
                worker.rpc(self.request('activate'))
                worker.last_heartbeat = time.monotonic()-5
                deadline = time.monotonic()+2
                while worker.state != 'fault' and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(worker.state, 'fault')
                session.stop.assert_called_once()
                motion.return_value.stop.assert_called_once()
            finally:
                worker.close()

    def test_acquire_failure_does_not_start_voice(self):
        with tempfile.TemporaryDirectory() as root, \
             patch('GuideBot.runtime.workers.voice.build_session') as build, \
             patch('GuideBot.runtime.workers.voice.MotionRuntime') as motion:
            build.return_value.stop.return_value = {'errors': ['acquire failed']}
            motion.return_value.start.side_effect = RuntimeError('acquire failed')
            worker = self.worker(root, gesture_backend='unitree')
            try:
                worker.rpc(self.request('authorize'))
                with self.assertRaisesRegex(RuntimeError, 'acquire failed'):
                    worker.rpc(self.request('activate'))
                build.return_value.start.assert_not_called()
                motion.return_value.stop.assert_called_once()
                self.assertEqual(worker.state, 'fault')
            finally:
                worker.close()
