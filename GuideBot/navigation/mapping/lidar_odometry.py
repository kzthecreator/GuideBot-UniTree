"""Measured ground-projected LiDAR odometry; no base extrinsic or map matching."""
import math
import numpy as np
from GuideBot.navigation.mapping.offline_mapping import icp, level, transform, voxel


class LidarOdometry:
    def __init__(self):
        self.pose=np.zeros(3)
        self.history=[]
        self.stamp=None
        self.yaw=None
        self.last_input=None
        self.rng=np.random.default_rng(13)
        self.failures=0
        self.lost=False

    def update(self, points, stamp, robot_yaw):
        if self.lost:
            raise ValueError('LiDAR odometry lost; restart near initial pose')
        if not all(math.isfinite(x) for x in (stamp,robot_yaw)):
            self.lost=True
            raise ValueError('Invalid timestamp/yaw')
        if self.last_input is not None and stamp<=self.last_input:
            self.lost=True
            raise ValueError('Source clock moved backwards')
        self.last_input=stamp
        if self.stamp is not None and stamp-self.stamp>2.:
            self.lost=True
            raise ValueError('LiDAR odometry gap >2s')
        cloud,floor=level(points,self.rng)
        radius=np.linalg.norm(cloud[:,:2],axis=1)
        obstacle=voxel(cloud[(cloud[:,2]>.3)&(cloud[:,2]<1.7)&(radius>.5)&(radius<12)])
        if len(obstacle)<40:
            raise ValueError('Too few obstacle points')
        quality=[1.,0.]
        guess=self.pose.copy()
        if self.stamp is not None:
            guess[2]+=math.atan2(math.sin(robot_yaw-self.yaw),math.cos(robot_yaw-self.yaw))
            reference=voxel(np.concatenate(self.history))
            pose,quality=icp(obstacle,reference,guess)
            angle=math.atan2(math.sin(pose[2]-guess[2]),math.cos(pose[2]-guess[2]))
            if quality[0]<.6 or quality[1]>.09 or np.linalg.norm(pose[:2]-guess[:2])>.6 or abs(angle)>.35:
                raise ValueError('LiDAR odometry match/jump rejected')
        else:
            pose=guess
        self.pose=pose
        self.stamp,self.yaw=stamp,robot_yaw
        self.history.append(transform(obstacle,pose))
        self.history=self.history[-8:]
        self.failures=0
        return cloud,pose.copy(),quality,floor

    def reject(self):
        self.failures+=1
        if self.failures>=3:self.lost=True
