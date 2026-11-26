import unittest
from unittest.mock import patch
from GuideBot.runtime.environment import ros_environment


class RosEnvironmentTests(unittest.TestCase):
    def test_foxy_uses_system_python_without_conda_binary_paths(self):
        raw=b'PYTHONPATH=/opt/ros/foxy/lib/python3.8/site-packages\0LD_LIBRARY_PATH=/opt/ros/foxy/lib\0'
        with patch('GuideBot.runtime.environment.subprocess.check_output', return_value=raw):
            env=ros_environment()
        self.assertEqual(env['GUIDEBOT_PYTHON'], '/usr/bin/python3')
        self.assertNotIn('/envs/', env['PYTHONPATH'])
        self.assertEqual(env['LD_LIBRARY_PATH'], '/opt/ros/foxy/lib')
