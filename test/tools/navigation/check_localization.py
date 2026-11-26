"""Read-only held-out replay tracking against a fixed 3D LiDAR map.

Map uses even indexed scans; tracking uses odd indexed scans of the SAME capture.
This tests local tracking consistency, not independent/global localization accuracy.
No ROS, robot DDS or motion commands are imported.
"""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def check(directory):
    import numpy as np
    from scipy.spatial.transform import Rotation
    from GuideBot.navigation.mapping.offline_mapping import icp, transform, voxel
    matched_path = directory/'mapping.npz'
    if not matched_path.exists():
        matched_path = directory/'matched3d.npz'
    matched = np.load(matched_path)
    extracted = np.load(directory/'extracted.npz')
    reference_poses = matched['poses']
    scans = [matched['points'][a:b] for a,b in zip(matched['offsets'][:-1], matched['offsets'][1:])]
    reference = voxel(np.concatenate([transform(scans[i], reference_poses[i])
                                     for i in range(0,len(scans),2)]), .1)
    times = extracted['cloud_times'][matched['indices']]
    odom = extracted['odom']
    yaw = np.interp(times, odom[:,0], np.unwrap(Rotation.from_quat(odom[:,4:]).as_euler('xyz')[:,2]))
    # Explicit operator-known start near map origin; deliberately perturbed.
    previous = np.array([.15, -.15, np.deg2rad(5)])
    previous_index = 0
    rows = []
    failed = []
    for i in range(1,len(scans),2):
        guess = previous.copy()
        guess[2] += yaw[i]-yaw[previous_index]
        start = time.monotonic()
        try:
            pose, quality = icp(scans[i], reference, guess)
            elapsed = time.monotonic()-start
            # Quality failures do not update tracking state.
            accepted = quality[0]>=.6 and quality[1]<=.09
            if not accepted:
                failed.append(i)
                continue
        except ValueError:
            failed.append(i)
            continue
        delta = pose-reference_poses[i]
        angle = np.arctan2(np.sin(delta[2]),np.cos(delta[2]))
        rows.append([times[i]-times[0], *pose, quality[0], quality[1], elapsed,
                     np.linalg.norm(delta[:2]), abs(angle)])
        previous, previous_index = pose, i
    rows = np.asarray(rows)
    if not len(rows):
        raise ValueError('No accepted localizations')
    stats = dict(experiment='same_capture_even_map_odd_tracking', independent_capture=False,
        initialization='Known map start plus 0.15m/-0.15m/5deg perturbation',
        map_points=len(reference), attempted=len(range(1,len(scans),2)), accepted=len(rows),
        failed_scan_indices=failed, min_overlap=float(rows[:,4].min()),
        rms_median_m=float(np.median(rows[:,5])),
        compute_median_ms=float(1000*np.median(rows[:,6])),
        compute_p95_ms=float(1000*np.percentile(rows[:,6],95)),
        compute_max_ms=float(1000*rows[:,6].max()),
        position_consistency_p95_m=float(np.percentile(rows[:,7],95)),
        position_consistency_max_m=float(rows[:,7].max()),
        yaw_consistency_p95_deg=float(np.rad2deg(np.percentile(rows[:,8],95))),
        limits=['Same recording as mapping; not independent physical ground truth',
                'Requires approximate starting pose; no global kidnapped-robot recovery',
                'Only ICP compute timed; floor fitting and cloud decoding excluded',
                'Leveled LiDAR poses only; no calibrated robot_center TF'],
        live_ready=False, navigation_ready=False, robot_commands=False)
    np.savetxt(directory/'localization.csv', rows, delimiter=',', comments='',
               header='elapsed_s,x_m,y_m,yaw_rad,overlap,inlier_rms_m,compute_s,position_consistency_m,yaw_consistency_rad')
    (directory/'localization-report.json').write_text(json.dumps(stats,indent=2)+'\n')
    return stats


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--map-directory',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(check(args.map_directory.expanduser().resolve()),indent=2))


if __name__=='__main__':
    main()
