"""Python 3.8 cancellation and node/SDK environment isolation."""
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from GuideBot.compat import CancellableThreadPoolExecutor
from GuideBot.runtime.environment import sdk_environment, _clean_ros_base


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
