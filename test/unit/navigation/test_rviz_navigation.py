import contextlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import yaml

from GuideBot.navigation.mapping.lidar_odometry import LidarOdometry
from GuideBot.navigation.mapping.offline_mapping import transform
from test.tools.navigation.rviz_config import generate, UPSTREAM, LIDAR_FRAME, ODOM_FRAME


class RvizNavigationTests(unittest.TestCase):
    def test_pinned_config_is_adapted_without_overwriting_original(self):
        original=(UPSTREAM/'g1_navigation.rviz').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);maps=root/'map';maps.mkdir()
            (maps/'report.json').write_text(json.dumps(dict(status='offline_draft_consistent')))
            params,rviz=generate(root,maps,(1.,2.,.3))
            data=yaml.safe_load(params.read_text())
            amcl=data['amcl']['ros__parameters']
            self.assertEqual(amcl['robot_model_type'],'omnidirectional')
            self.assertEqual(amcl['base_frame_id'],LIDAR_FRAME)
            self.assertEqual(amcl['odom_frame_id'],ODOM_FRAME)
            self.assertNotIn('robot_center',[LIDAR_FRAME,ODOM_FRAME])
            self.assertEqual(amcl['initial_pose']['x'],1.)
            self.assertEqual(data['map_server']['ros__parameters']['yaml_filename'],str(maps/'map.yaml'))
            self.assertEqual(data['lifecycle_manager_localization']['ros__parameters']['node_names'],['map_server','amcl'])
            ui=yaml.safe_load(rviz.read_text())['Visualization Manager']
            self.assertEqual(ui['Global Options']['Fixed Frame'],'map')
            nav=next(d for d in ui['Displays'] if d['Name']=='Nav2')
            particles=next(d for d in nav['Displays'] if d['Name']=='Amcl Particle Swarm')
            self.assertEqual(particles['Class'],'rviz_default_plugins/PoseArray')
            self.assertEqual(particles['Topic']['Value'],'/particlecloud')
            for name in ('Robot','Object poses'):
                self.assertFalse(next(d for d in ui['Displays'] if d['Name']==name)['Enabled'])
            self.assertTrue(any(t['Class']=='rviz_default_plugins/SetInitialPose' for t in ui['Tools']))
            self.assertEqual((UPSTREAM/'g1_navigation.rviz').read_bytes(),original)
            (maps/'report.json').write_text(json.dumps(dict(status='offline_draft_needs_review')))
            with self.assertRaises(ValueError):generate(root,maps)

    def test_measured_sensor_motion_does_not_require_robot_translation_or_extrinsic(self):
        rng=np.random.default_rng(15)
        points=rng.uniform([-3,-2,.3],[3,2,1.7],(1800,3))
        expected=np.array([.12,-.07,.04])
        c,s=math.cos(expected[2]),math.sin(expected[2])
        inverse=np.array([-c*expected[0]-s*expected[1],s*expected[0]-c*expected[1],-expected[2]])
        observed=transform(points,inverse)
        # Floor estimator is independently exercised by test_offline_mapping.
        with patch('GuideBot.navigation.mapping.lidar_odometry.level',side_effect=lambda p,r:(p,[0,0,-1,1.2,.003])):
            odom=LidarOdometry()
            odom.update(points,1.,1.5)
            _,pose,quality,_=odom.update(observed,1.3,1.54)
            np.testing.assert_allclose(pose,expected,atol=.003)
            self.assertGreater(quality[0],.95)
            with self.assertRaises(ValueError):odom.update(observed,.9,1.54)
            self.assertTrue(odom.lost)
            with self.assertRaises(ValueError):odom.update(observed,1.6,1.54)

    def test_frontend_gap_and_repeated_failures_do_not_publish_fabricated_motion(self):
        odom=LidarOdometry()
        odom.stamp=1.
        with self.assertRaises(ValueError):odom.update(np.zeros((50,3)),4.,0.)
        self.assertTrue(odom.lost)
        odom=LidarOdometry()
        for _ in range(3):odom.reject()
        self.assertTrue(odom.lost)
        self.assertIsNone(odom.stamp)

    def test_invalid_input_does_not_launch_any_process(self):
        from test.tools.navigation.rviz import main
        with tempfile.TemporaryDirectory() as tmp:
            with patch('sys.argv',['rviz.py','live','--map-directory',tmp]),patch('subprocess.Popen') as launch,patch('builtins.input') as enter,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):main()
                launch.assert_not_called();enter.assert_not_called()


if __name__=='__main__':unittest.main()
