import tempfile
from pathlib import Path
import unittest
import yaml
from test.tools.navigation.nav_config import generate


class NavigationConfigTests(unittest.TestCase):
    def test_avoidance_sees_low_obstacles_and_recovers_without_blind_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=yaml.safe_load(generate(tmp).read_text())
            for name in ('local_costmap','global_costmap'):
                cost=data[name][name]['ros__parameters']
                self.assertEqual(cost['robot_base_frame'],'guidebot_lidar_ground')
                source=cost['obstacle_layer']['cloud']
                self.assertLess(source['min_obstacle_height'],.1)
                self.assertEqual(source['data_type'],'PointCloud2')
                self.assertGreaterEqual(cost['robot_radius'],.7)
            self.assertFalse(data['planner_server']['ros__parameters']['GridBased']['allow_unknown'])
            tree=(Path(tmp)/'navigate.xml').read_text()
            self.assertNotIn('BackUp',tree);self.assertNotIn('Spin',tree)
            self.assertNotIn('recoveries_server',data)
            self.assertEqual(data['controller_server']['ros__parameters']['FollowPath']['desired_linear_vel'],.1)


if __name__=='__main__':unittest.main()
