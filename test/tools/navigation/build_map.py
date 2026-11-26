"""Offline mapping of the recorded upside-down MID360 mount; never connects DDS."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


def extract(capture, output):
    import json
    import numpy as np
    from GuideBot.robot.sensors.runtime import source_types
    types = source_types()  # IDL types only: never creates a DDS participant.
    odom, imu, clouds, points = [], [], [], []
    with (capture/'samples.cdr').open('rb') as stream:
        for line in (capture/'samples.jsonl').open():
            row = json.loads(line)
            stream.seek(row['offset'])
            payload = stream.read(row['size'])
            if len(payload) != row['size']:
                raise ValueError('Truncated CDR recording')
            msg = types[row['track']][1].deserialize(payload)
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
            if row['track'] == 'odom':
                p, q = msg.pose.pose.position, msg.pose.pose.orientation
                odom.append([stamp, p.x, p.y, p.z, q.x, q.y, q.z, q.w])
            elif row['track'] == 'imu':
                a, g = msg.linear_acceleration, msg.angular_velocity
                imu.append([stamp, a.x, a.y, a.z, g.x, g.y, g.z])
            else:
                if msg.is_bigendian:
                    raise ValueError('Big-endian point clouds not supported')
                fields = {field.name: field.offset for field in msg.fields}
                raw = bytes(msg.data)
                xyz = np.column_stack([np.ndarray((msg.height, msg.width), dtype='<f4', buffer=raw,
                    offset=fields[key], strides=(msg.row_step, msg.point_step)).reshape(-1)
                    for key in ['x', 'y', 'z']])
                xyz = xyz[np.all(np.isfinite(xyz), axis=1)]
                points.append(xyz[np.linalg.norm(xyz, axis=1) > .25][::2])
                clouds.append(stamp)
    if len(clouds) < 10 or not odom:
        raise ValueError('Recording lacks clouds/odometry')
    np.savez_compressed(output/'extracted.npz', odom=odom, imu=imu, cloud_times=clouds,
                        points=np.concatenate(points), offsets=np.cumsum([0]+[len(p) for p in points]))


def build(output):
    import numpy as np
    from GuideBot.navigation.mapping.offline_mapping import level, voxel, transform, icp
    from scipy.spatial.transform import Rotation
    data = np.load(output/'extracted.npz')
    rng = np.random.default_rng(13)
    indices = np.arange(0, len(data['cloud_times']), 3)
    scans, floors = [], []
    for index in indices:
        raw = data['points'][data['offsets'][index]:data['offsets'][index+1]]
        cloud, floor = level(raw, rng)
        ranges = np.linalg.norm(cloud[:, :2], axis=1)
        mask = (cloud[:, 2] > .3) & (cloud[:, 2] < 1.7) & (ranges > .5) & (ranges < 12)
        scans.append(voxel(cloud[mask]))
        floors.append(floor)
        if len(scans) % 30 == 0:
            print('Leveled %d/%d scans' % (len(scans), len(indices)), flush=True)
    odom = data['odom']
    if np.any(np.diff(odom[:, 0]) <= 0) or np.any(np.diff(data['cloud_times']) <= 0):
        raise ValueError('Non-monotonic source timestamps')
    if data['cloud_times'][0] < odom[0, 0]-.2 or data['cloud_times'][-1] > odom[-1, 0]+.2:
        raise ValueError('Cloud and odometry clocks do not overlap')
    yaw = np.unwrap(Rotation.from_quat(odom[:, 4:]).as_euler('xyz')[:, 2])
    scan_yaw = np.interp(data['cloud_times'][indices], odom[:, 0], yaw)
    poses, metrics = [np.zeros(3)], []
    for index in range(1, len(scans)):
        reference = voxel(np.concatenate([transform(scans[j], poses[j])
                          for j in range(max(0, index-8), index)]))
        guess = poses[-1].copy()
        # Relative yaw is a search prior only; translation/extrinsics remain geometric.
        guess[2] += scan_yaw[index] - scan_yaw[index-1]
        pose, metric = icp(scans[index], reference, guess)
        if metric[0] < .6 or metric[1] > .09:
            raise ValueError('Unreliable registration at scan %d: %s' % (index, metric))
        poses.append(pose)
        metrics.append(metric)
        if index % 20 == 0:
            print('Matched %d/%d scans' % (index, len(scans)), flush=True)
    poses = np.asarray(poses)
    # User confirmed return to origin; zero is a search seed, never a forced constraint.
    loop, loop_metric = icp(scans[-1], scans[0], np.array([0., 0., scan_yaw[-1]-scan_yaw[0]]))
    np.savez_compressed(output/'matched3d.npz', poses=poses, metrics=metrics, floors=floors,
                        indices=indices, points=np.concatenate(scans),
                        offsets=np.cumsum([0]+[len(scan) for scan in scans]),
                        loop=loop, loop_metrics=loop_metric)
    return dict(poses=poses, metrics=np.asarray(metrics), floors=np.asarray(floors),
                indices=indices, points=np.concatenate(scans),
                offsets=np.cumsum([0]+[len(scan) for scan in scans]),
                loop=loop, loop_metrics=np.asarray(loop_metric))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    capture = args.capture.expanduser().resolve()
    for name in ['samples.cdr', 'samples.jsonl']:
        if not (capture/name).is_file():
            parser.error('Missing recording file: %s' % (capture/name))
    output = (args.output or Path.home()/'.local/state/guidebot/navigation/maps'/capture.name).expanduser().resolve()
    if not args.worker:
        from runtime.app.environment import sdk_environment
        env = sdk_environment()
        env['OPENBLAS_NUM_THREADS'] = '1'
        return subprocess.call([sys.executable, str(Path(__file__).resolve()), '--capture', str(capture),
                                '--output', str(output), '--worker'], env=env, cwd=REPO)
    if output.exists():
        parser.error('Output already exists; choose a new --output directory: %s' % output)
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    extract(capture, output)
    matched = build(output)
    import json
    import numpy as np
    from GuideBot.navigation.mapping.offline_mapping import finalize
    report = finalize(output, capture, np.load(output/'extracted.npz'), matched)
    print(json.dumps(report, indent=2), flush=True)
    print('Matched LiDAR scans saved to '+str(output), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
