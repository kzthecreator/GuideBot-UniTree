import math
import contextlib
import io
import unittest
from unittest.mock import patch
from GuideBot.navigation.velocity import (CommandLease, ZERO, bounded_velocity,
    body_velocity, hardware_profile, lidar_radius)


class NavigationVelocityTests(unittest.TestCase):
    def profile(self):
        return hardware_profile(dict(confirmed=True,evidence='synthetic test geometry, not hardware',
            body_x_in_lidar_m=.1,body_y_in_lidar_m=.2,body_yaw_in_lidar_rad=math.pi/2,body_radius_m=.4,waist_reference_rad=[0.,0.,0.]))

    def test_missing_geometry_cannot_enable_hardware(self):
        for data in ({},dict(confirmed=True,evidence='factory',body_radius_m=.4),
                     dict(self.profile(),body_yaw_in_lidar_rad=float('nan'))):
            with self.assertRaises(ValueError):hardware_profile(data)

    def test_twist_uses_body_heading_and_lever_arm(self):
        velocity=body_velocity((.1,0.,.2),self.profile())
        self.assertAlmostEqual(velocity[0],.02)
        self.assertAlmostEqual(velocity[1],-.06)
        self.assertAlmostEqual(velocity[2],.2)
        self.assertGreater(lidar_radius(self.profile()),.65)

    def test_stale_replayed_nan_and_wrong_session_revoke_motion(self):
        lease=CommandLease('private')
        packet=dict(token='private',sequence=1,sent_at=10.,enabled=True,velocity=[.1,0.,0.])
        self.assertEqual(lease.accept(packet,10.1),(.1,0.,0.))
        self.assertEqual(lease.current(10.251),ZERO)
        for changed in (dict(sequence=1),dict(sequence=2,token='other'),
                        dict(sequence=3,sent_at=9.),dict(sequence=4,velocity=[float('nan'),0.,0.])):
            with self.assertRaises(ValueError):lease.accept(dict(packet,**changed),10.1)
            self.assertEqual(lease.current(10.1),ZERO)
        self.assertEqual(lease.accept(dict(packet,sequence=5,enabled=False),10.1),ZERO)

    def test_independent_limits_reject_unexpected_controller_output(self):
        for value in ([.2,0,0],[.1,.12,0],[0,0,.3],[0,0,float('inf')],[True,0,0]):
            with self.assertRaises(ValueError):bounded_velocity(value)

    def test_missing_motion_calibration_rejects_before_process_or_enter(self):
        from test.tools.navigation.rviz import main
        with patch('sys.argv',['rviz.py','live','--headless','--navigation','--motion','--map-directory','/missing']), \
                patch('subprocess.Popen') as launch,patch('builtins.input') as enter,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):main()
            launch.assert_not_called();enter.assert_not_called()


if __name__=='__main__':unittest.main()
