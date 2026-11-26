import tempfile
import unittest
from pathlib import Path

import numpy as np

from GuideBot.navigation.mapping.offline_mapping import export_grid, finalize, icp, level, transform


class OfflineMappingTests(unittest.TestCase):
    def test_spatial_matching_recovers_pose_with_clutter(self):
        rng = np.random.default_rng(9)
        scene = rng.uniform([-3, -2, .3], [3, 2, 1.7], (1500, 3))
        expected = np.array([.12, -.08, .04])
        c, s = np.cos(expected[2]), np.sin(expected[2])
        inverse = np.array([-c*expected[0]-s*expected[1],
                            s*expected[0]-c*expected[1], -expected[2]])
        observed = transform(scene, inverse)
        observed += rng.normal(0, .002, observed.shape)
        observed = np.concatenate([observed, rng.uniform([7,7,.3],[8,8,1.7],(100,3))])
        pose, metric = icp(observed, scene, np.zeros(3))
        np.testing.assert_allclose(pose, expected, atol=.002)
        self.assertGreater(metric[0], .9)
        self.assertLess(metric[1], .01)

    def test_floor_is_measured_not_identity(self):
        rng = np.random.default_rng(12)
        xy = rng.uniform(-3, 3, (2000, 2))
        z = 1.24 - .12*xy[:,0] + rng.normal(0,.003,len(xy))
        plane = np.column_stack([xy,z])
        cloud, fit = level(plane, rng)
        self.assertLess(np.std(cloud[:,2]), .004)
        self.assertLess(abs(np.mean(cloud[:,2])), .003)
        self.assertLess(fit[-1], .004)
        self.assertLess(fit[2], -.98)
        with self.assertRaises(ValueError):
            level(np.zeros((20,3)), rng)

    def test_loop_inconsistency_is_reported_without_claiming_navigation(self):
        cloud = np.array([[2.,0.,1.], [2.,.2,1.]])
        extracted = dict(odom=np.array([[0,0,0,0],[1,.1,0,0]]),
                         cloud_times=np.array([0.,.5,1.]))
        matched = dict(poses=np.zeros((3,3)), points=np.concatenate([cloud]*3),
                       offsets=np.array([0,2,4,6]), indices=np.arange(3),
                       loop=np.array([1.,0.,0.]), loop_metrics=np.array([.9,.03]),
                       metrics=np.array([[.9,.03],[.9,.03]]),
                       floors=np.array([[0,0,-1,1.2,.005]]*3))
        with tempfile.TemporaryDirectory() as tmp:
            result = finalize(tmp, '/offline/capture', extracted, matched)
            self.assertEqual(result['status'], 'offline_draft_needs_review')
            self.assertFalse(result['navigation_ready'])
            self.assertEqual(result['closure_disagreement_m'], 1.)
            matched['loop'] = np.array([.05,0.,2*np.pi])
            result = finalize(tmp, '/offline/capture', extracted, matched)
            self.assertEqual(result['status'], 'offline_draft_consistent')
            self.assertFalse(result['navigation_ready'])

    def test_grid_keeps_unseen_unknown_and_marks_repeated_hits(self):
        scans = [np.array([[2.,0.,1.], [2.,.2,1.]])] * 3
        poses = np.zeros((3,3))
        with tempfile.TemporaryDirectory() as tmp:
            info = export_grid(tmp, scans, poses, .1)
            raw = (Path(tmp)/'map.pgm').read_bytes().split(b'\n',3)[-1]
            self.assertIn(205, raw)
            self.assertIn(254, raw)
            self.assertIn(0, raw)
            self.assertEqual(info['occupied_cells'], 2)
            self.assertTrue((Path(tmp)/'preview.png').read_bytes().startswith(b'\x89PNG'))


if __name__ == '__main__':
    unittest.main()
