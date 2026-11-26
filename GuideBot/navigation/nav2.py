"""Tour-to-Nav2 boundary, independent of ROS distribution and motor control.

The transport owns the ROS executor. Only a successful NavigateToPose result
means arrival; accepting a goal, feedback and cancellation do not mean arrival.
"""
import math
import threading


def validate_waypoints(value):
    if not isinstance(value, dict):
        raise ValueError('Waypoints must map tour point IDs to map poses')
    result = {}
    for point, pose in value.items():
        if not isinstance(point, str) or not point or not isinstance(pose, dict):
            raise ValueError('Invalid waypoint')
        if set(pose) != {'frame_id', 'x', 'y', 'yaw'} or pose['frame_id'] != 'map':
            raise ValueError('Waypoints require frame_id=map and x/y/yaw')
        if any(type(pose[key]) not in (int, float) or not math.isfinite(pose[key])
               for key in ('x', 'y', 'yaw')):
            raise ValueError('Waypoint coordinates must be finite numbers')
        result[point] = dict(pose)
    return result


class Nav2Navigator:
    """Transport contract: send(pose, done)->handle, cancel(handle).

    done(status) uses succeeded/aborted/rejected/canceled. Callbacks may arrive
    on a ROS thread; notify must enqueue events, not mutate the tour directly.
    A session owns one adapter, and late callbacks are fenced by a local token.
    """
    def __init__(self, transport, waypoints, notify):
        self.transport = transport
        self.waypoints = validate_waypoints(waypoints)
        self.notify = notify
        self.lock = threading.RLock()
        self.pending = None
        self.closed = False

    def go_to(self, point_id, task_id):
        if point_id not in self.waypoints or not task_id:
            raise ValueError('Navigation target needs a registered map pose and task ID')
        with self.lock:
            if self.closed:
                raise RuntimeError('Navigator is closed')
            if self.pending:
                if (point_id, task_id) == self.pending['key']:
                    return  # A repeated resume must not send two goals.
                raise RuntimeError('Cancel the current goal before replacing it')
            token = object()
            entry = dict(key=(point_id, task_id), token=token, handle=None)
            self.pending = entry
            try:
                handle = self.transport.send(dict(self.waypoints[point_id]),
                    lambda status: self._done(token, status))
            except Exception:
                self.pending = None
                raise
            if self.pending is entry:
                entry['handle'] = handle

    def _done(self, token, status):
        with self.lock:
            if self.closed or not self.pending or self.pending['token'] is not token:
                return
            point_id, task_id = self.pending['key']
            self.pending = None
            kind = 'arrived' if status == 'succeeded' else 'navigation_failed'
            self.notify(kind, point_id=point_id, task_id=task_id)

    def arrived(self, point_id, task_id=None):
        raise ValueError('Nav2 mode accepts arrival only from its action result')

    def cancel(self):
        with self.lock:
            entry, self.pending = self.pending, None
            if entry and entry['handle'] is not None:
                self.transport.cancel(entry['handle'])

    def close(self):
        with self.lock:
            self.closed = True
            self.cancel()
