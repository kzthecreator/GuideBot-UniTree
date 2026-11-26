"""Python 3.8 cancellation and node/SDK environment isolation."""
import os
from pathlib import Path
import threading
import tempfile
import unittest
from unittest.mock import patch
from GuideBot.compat import CancellableThreadPoolExecutor
from runtime.app.environment import sdk_environment, ros_environment, _clean_ros_base


class CompatibilityTests(unittest.TestCase):
    def test_shutdown_cancels_queued_work(self):
        gate = threading.Event()
        running = threading.Event()
        pool = CancellableThreadPoolExecutor(max_workers=1)
        def first():
            running.set()
            gate.wait(2)
        try:
            active = pool.submit(first)
            self.assertTrue(running.wait(1))
            queued = pool.submit(lambda: self.fail('Cancelled task ran'))
            pool.shutdown(wait=False, cancel_futures=True)
            self.assertTrue(queued.cancelled())
            gate.set()
            active.result(timeout=1)
            with self.assertRaises(RuntimeError):
                pool.submit(lambda: None)
        finally:
            gate.set()
            pool.shutdown()

    def test_sdk_process_does_not_inherit_foxy_library_path(self):
        with patch.dict(os.environ, {'LD_LIBRARY_PATH':'/opt/ros/foxy/lib',
                                    'PYTHONPATH':'/opt/ros/foxy/lib/python3.8/site-packages',
                                    'ROS_DOMAIN_ID':'42'}):
            sdk = sdk_environment()
            ros = _clean_ros_base()
        self.assertNotIn('/opt/ros/foxy',sdk['LD_LIBRARY_PATH'])
        self.assertNotIn('/opt/ros/foxy',sdk['PYTHONPATH'])
        self.assertNotIn('ROS_DOMAIN_ID',sdk)
        self.assertNotIn('LD_LIBRARY_PATH',ros)
        self.assertNotIn('PYTHONPATH',ros)

    def test_new_account_uses_shared_sdk_without_private_home_symlink(self):
        with patch.dict(os.environ, {}, clear=True):
            sdk = sdk_environment()
        self.assertEqual(sdk['CYCLONEDDS_HOME'], '/opt/unitree_robotics/cyclonedds')
        self.assertIn('/opt/unitree_robotics/cyclonedds/lib', sdk['LD_LIBRARY_PATH'])

    def test_ros_domains_are_per_account_and_explicit_override_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'foxy').mkdir()
            (root / 'install').mkdir()
            (root / 'foxy/setup.bash').touch()
            (root / 'install/local_setup.bash').touch()
            with patch('runtime.app.environment.FOXY', root / 'foxy'), \
                 patch('runtime.app.environment.subprocess.check_output', return_value=b'PATH=/usr/bin\0'), \
                 patch.dict(os.environ, {}, clear=True):
                with patch('os.getuid', return_value=1002):
                    first = ros_environment(install=root / 'install')
                with patch('os.getuid', return_value=1003):
                    second = ros_environment(install=root / 'install')
                self.assertNotEqual(first['ROS_DOMAIN_ID'], second['ROS_DOMAIN_ID'])
                self.assertEqual(ros_environment(install=root / 'install', domain=0)['ROS_DOMAIN_ID'], '0')
                with patch.dict(os.environ, {'GUIDEBOT_ROS_DOMAIN_ID': '83'}):
                    self.assertEqual(ros_environment(install=root / 'install')['ROS_DOMAIN_ID'], '83')
