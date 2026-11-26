"""Read-only fixed-map tracking in the leveled LiDAR frame (not robot_center)."""
from collections import deque
import math
from pathlib import Path
import json
import time

import numpy as np

from GuideBot.navigation.mapping.offline_mapping import icp, level, transform, voxel


class MapTracker:
    def __init__(self, reference, initial_pose=(0., 0., 0.), matcher=icp):
        self.reference = reference
        self.matcher = matcher
        self.pose = np.asarray(initial_pose, dtype=float)
        if self.pose.shape != (3,) or not np.all(np.isfinite(self.pose)):
            raise ValueError('Initial pose must be three finite numbers')
        self.accepted_stamp = None
        self.accepted_yaw = None
        self.last_input_stamp = None
        self.rejects = 0
        self.rng = np.random.default_rng(13)
        self.history = deque(maxlen=1000)
        self.state = dict(state='waiting', valid=False, reason='等待雷达和里程计',
                          pose=None, accepted=0, rejected=0, navigation_ready=False)

    @classmethod
    def load(cls, directory, initial_pose=(0., 0., 0.)):
        directory = Path(directory)
        report = json.loads((directory/'report.json').read_text())
        if report['status'] != 'offline_draft_consistent':
            raise ValueError('Map has not passed offline consistency checks')
        path = directory/'mapping.npz'
        if not path.exists():
            path = directory/'matched3d.npz'
        with np.load(path) as data:
            points, offsets, poses = data['points'], data['offsets'], data['poses']
            reference = voxel(np.concatenate([transform(points[a:b], poses[i])
                              for i, (a,b) in enumerate(zip(offsets[:-1], offsets[1:]))
                              if i % 2 == 0]), .1)
        return cls(reference, initial_pose)

    def reject(self, reason, hard=False):
        self.rejects += 1
        lost = hard or self.rejects >= 3 or self.state['state'] == 'lost'
        self.state = dict(self.state, state='lost' if lost else 'rejected', valid=False,
                          reason=reason, rejected=self.state['rejected']+1)
        return self.snapshot()

    def update(self, raw_points, stamp, yaw, received_at, now=None):
        started = time.monotonic()
        cloud, floor = level(raw_points, self.rng)
        radius = np.linalg.norm(cloud[:, :2], axis=1)
        mask = (cloud[:,2]>.3)&(cloud[:,2]<1.7)&(radius>.5)&(radius<12)
        return self.match(voxel(cloud[mask]), stamp, yaw, received_at, now,
                          preprocess_ms=(time.monotonic()-started)*1000, floor=floor)

    def match(self, cloud, stamp, yaw, received_at, now=None, preprocess_ms=0., floor=None):
        """Quality and jump checks fence invalid results; lost requires restart."""
        clock_override = now is not None
        now = time.monotonic() if now is None else now
        if self.state['state'] == 'lost':
            return self.snapshot(now)
        if not all(math.isfinite(value) for value in (stamp, yaw, received_at, now)):
            return self.reject('无效时间或朝向', hard=True)
        if now-received_at > 2. or received_at > now+.1:
            return self.reject('点云已过期')
        if self.last_input_stamp is not None and stamp <= self.last_input_stamp:
            return self.reject('传感器时间戳倒退', hard=True)
        self.last_input_stamp = stamp
        guess = self.pose.copy()
        if self.accepted_stamp is not None:
            gap = stamp-self.accepted_stamp
            if gap > 2.:
                return self.reject('定位间隔超过2秒，请回起点重新启动', hard=True)
            # Wrap difference only for bounded short gaps, never integrate a long outage.
            guess[2] += math.atan2(math.sin(yaw-self.accepted_yaw),math.cos(yaw-self.accepted_yaw))
        start = time.monotonic()
        try:
            pose, metric = self.matcher(cloud, self.reference, guess)
        except (ValueError, np.linalg.LinAlgError) as error:
            return self.reject('匹配失败：'+str(error))
        compute_ms = (time.monotonic()-start)*1000
        if not np.all(np.isfinite(pose)) or not np.all(np.isfinite(metric)):
            return self.reject('匹配结果无效', hard=True)
        if metric[0] < .6 or metric[1] > .09:
            return self.reject('点云与地图匹配不足')
        # A good local RMS alone is insufficient: reject a different local solution.
        if np.linalg.norm(pose[:2]-guess[:2]) > .6 or abs(math.atan2(math.sin(pose[2]-guess[2]),math.cos(pose[2]-guess[2]))) > .35:
            return self.reject('位姿跳变超出局部跟踪范围', hard=True)
        # Use current time after compute for actual freshness, except deterministic tests.
        finished = now+(time.monotonic()-start) if clock_override else time.monotonic()
        if finished-received_at > 2.:
            return self.reject('定位结果完成时已过期')
        self.pose = np.asarray(pose)
        self.accepted_stamp, self.accepted_yaw = stamp, yaw
        self.rejects = 0
        self.history.append(self.pose[:2].tolist())
        self.state = dict(self.state, state='tracking', valid=True, reason='雷达定位跟踪中',
                          pose=self.pose.tolist(), trajectory=list(self.history), overlap=float(metric[0]), inlier_rms_m=float(metric[1]),
                          source_stamp_s=stamp, received_at=received_at, accepted=self.state['accepted']+1,
                          compute_ms=compute_ms, preprocess_ms=preprocess_ms,
                          receive_to_result_ms=(finished-received_at)*1000,
                          floor_height_m=float(floor[3]) if floor is not None else None)
        return self.snapshot(now)

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        result = dict(self.state)
        age = now-result.get('received_at', now)
        result['age_s'] = max(0., age)
        if result['state']=='tracking' and age>2.:
            result.update(state='stale',valid=False,reason='定位已过期，等待新数据')
        result.setdefault('trajectory', [])
        return result


def decode_cloud(msg):
    if msg.is_bigendian:
        raise ValueError('Big endian clouds not supported')
    fields = {field.name: field for field in msg.fields}
    if any(name not in fields or fields[name].datatype!=7 or fields[name].count!=1 for name in ('x','y','z')):
        raise ValueError('Expected float32 XYZ point fields')
    raw = bytes(msg.data)
    xyz = np.column_stack([np.ndarray((msg.height,msg.width),dtype='<f4',buffer=raw,
             offset=fields[key].offset,strides=(msg.row_step,msg.point_step)).reshape(-1)
             for key in ('x','y','z')])
    xyz = xyz[np.all(np.isfinite(xyz),axis=1)]
    return xyz[np.linalg.norm(xyz,axis=1)>.25][::2]
