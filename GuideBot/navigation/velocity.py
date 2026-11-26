"""Pure, fail-closed navigation velocity checks, shared by ROS and SDK processes."""
import math


ZERO = (0., 0., 0.)
MAX_LINEAR = .15
MAX_ANGULAR = .25
COMMAND_TTL = .25
RPC_DURATION = .20


def hardware_profile(data):
    if not isinstance(data, dict):
        raise ValueError('Hardware profile must be a mapping')
    if data.get('confirmed') is not True or not str(data.get('evidence', '')).strip():
        raise ValueError('Measured LiDAR/body calibration and footprint must be confirmed')
    keys = ('body_x_in_lidar_m', 'body_y_in_lidar_m', 'body_yaw_in_lidar_rad', 'body_radius_m')
    values = []
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError('Missing/nonfinite hardware value: '+key)
        values.append(float(value))
    x, y, yaw, radius = values
    if math.hypot(x, y) > .6 or not -.5*math.tau <= yaw <= .5*math.tau or not .3 <= radius <= .8:
        raise ValueError('Hardware geometry outside supported range')
    waist=data.get('waist_reference_rad')
    if (not isinstance(waist,list) or len(waist)!=3 or
            any(isinstance(q,bool) or not isinstance(q,(int,float)) or not math.isfinite(q) or abs(q)>.2 for q in waist)):
        raise ValueError('Measured waist_reference_rad [yaw, roll, pitch] required, within 0.2rad')
    return dict(zip(keys, values), confirmed=True, evidence=str(data['evidence']),waist_reference_rad=list(map(float,waist)))


def lidar_radius(profile):
    """Enclose the body at the LiDAR origin, avoiding a fabricated base TF."""
    return profile['body_radius_m'] + math.hypot(profile['body_x_in_lidar_m'], profile['body_y_in_lidar_m']) + .05


def body_velocity(velocity, profile):
    vx, vy, omega = velocity
    # v(body origin) = v(lidar origin) + omega cross body_offset.
    vx -= omega*profile['body_y_in_lidar_m']
    vy += omega*profile['body_x_in_lidar_m']
    yaw = profile['body_yaw_in_lidar_rad']
    c, s = math.cos(yaw), math.sin(yaw)
    return c*vx+s*vy, -s*vx+c*vy, omega


def bounded_velocity(values):
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise ValueError('Expected planar velocity')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError('Nonfinite velocity')
    vx, vy, omega = map(float, values)
    # Reject rather than rescale a controller with an unexpected configuration.
    if math.hypot(vx, vy) > MAX_LINEAR+1e-6 or abs(omega) > MAX_ANGULAR+1e-6:
        raise ValueError('Velocity exceeds independent SDK bridge limit')
    return vx, vy, omega


class CommandLease:
    """Monotonic sequence, freshness and run token; invalid packets revoke motion."""
    def __init__(self, token):
        self.token = token
        self.sequence = -1
        self.deadline = 0.
        self.velocity = ZERO

    def accept(self, packet, now):
        self.deadline = 0.
        self.velocity = ZERO
        stamp, sequence = packet.get('sent_at'), packet.get('sequence')
        if (packet.get('token') != self.token or isinstance(sequence, bool) or
                not isinstance(sequence, int) or sequence <= self.sequence or
                isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or
                not math.isfinite(stamp) or not 0 <= now-stamp <= COMMAND_TTL):
            raise ValueError('Invalid/replayed/stale velocity lease')
        self.sequence = sequence
        velocity = bounded_velocity(packet.get('velocity'))
        if packet.get('enabled') is True:
            self.velocity = velocity
            self.deadline = stamp+COMMAND_TTL
        return self.current(now)

    def current(self, now):
        return self.velocity if now < self.deadline else ZERO
