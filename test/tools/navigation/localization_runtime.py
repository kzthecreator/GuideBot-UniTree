"""Bounded sensor inbox. SDK CDR decoding runs only in an SDK environment."""
from collections import deque
import math
import threading
import time

import numpy as np

from runtime.ipc.sensor_wire import receive


class SensorInbox:
    def __init__(self, connection, types):
        self.connection = connection
        self.types = types
        self.lock = threading.Lock()
        self.odometry = deque(maxlen=5000)
        self.latest = None
        self.counts = dict(cloud=0, imu=0, odom=0)
        self.overwritten = 0
        self.done = False
        self.error = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        try:
            while not self.stop_event.is_set():
                header, payload = receive(self.connection)
                track = header['track']
                arrived = time.monotonic()
                if track == 'odom':
                    msg = self.types['odom'][1].deserialize(payload)
                    stamp = msg.header.stamp.sec + msg.header.stamp.nanosec/1e9
                    q = msg.pose.pose.orientation
                    yaw = math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
                    if not all(math.isfinite(v) for v in (stamp,yaw,q.x,q.y,q.z,q.w)):
                        raise ValueError('Invalid odometry')
                    with self.lock:
                        if self.odometry and stamp <= self.odometry[-1][0]:
                            raise ValueError('Odometry clock moved backwards')
                        self.odometry.append((stamp,yaw))
                with self.lock:
                    self.counts[track] += 1
                    if track == 'cloud':
                        self.overwritten += int(self.latest is not None)
                        self.latest = (payload,arrived)
        except EOFError:
            pass
        except Exception as error:
            if not self.stop_event.is_set():
                self.error = type(error).__name__+': '+str(error)
        finally:
            self.done = True

    def take(self):
        with self.lock:
            item, self.latest = self.latest, None
            return item

    def yaw_at(self, stamp):
        with self.lock:
            samples = np.asarray(self.odometry)
        if len(samples)<2 or stamp<samples[0,0]-.02 or stamp>samples[-1,0]+.02:
            raise ValueError('点云对应的里程计尚未就绪')
        return float(np.interp(stamp,samples[:,0],np.unwrap(samples[:,1])))

    def statistics(self):
        with self.lock:
            return dict(received=dict(self.counts), skipped_clouds=self.overwritten,
                        source_connected=not self.done, source_error=self.error)
