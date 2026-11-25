"""Authoritative ROS session lifecycle; host workers never start themselves."""
from .common import *

ROLES = ('planner', 'interaction', 'motion', 'bridge', 'scheduler')


class SessionManager(Node):
    def __init__(self):
        super().__init__('session_manager')
        self.session_id = None
        self.generation = 0
        self.mode = 'voice'
        self.state = 'standby'
        self.lock = threading.Lock()
        self.offline = os.environ.get('GUIDEBOT_ROS_OFFLINE') == '1'
        self.managed_resources = not self.offline or os.environ.get('GUIDEBOT_ROS_MANAGED_TEST') == '1'
        self.control_clients = {role: self.create_client(SessionControl, '/guidebot/internal/'+role+'/control',
                       callback_group=ReentrantCallbackGroup()) for role in ROLES}
        self.control = self.create_service(SessionControl, '/guidebot/session/control', self.control_session,
                                          callback_group=ReentrantCallbackGroup())
        self.timer = self.create_timer(.5, self.check_health, callback_group=ReentrantCallbackGroup())
        self.retired = set()

    def worker(self, op, timeout=60):
        return call(ROOT/'resources.sock', dict(op=op, session_id=self.session_id,
                                              generation=self.generation), timeout)

    def node_control(self, role, command):
        client = self.control_clients[role]
        if not client.wait_for_service(timeout_sec=5):
            raise RuntimeError('Required ROS node unavailable: '+role)
        result = wait(client.call_async(message(SessionControl.Request,
                      dict(session_id=self.session_id, generation=self.generation,
                           command=command, mode=self.mode))), 20)
        if not result.accepted:
            raise RuntimeError('ROS node rejected '+command+': '+role)

    def shutdown_session(self, fault=False):
        self.state = 'stopping'
        errors = []
        if self.managed_resources:
            try:
                self.worker('deactivate', 90)
            except Exception as error:
                errors.append(type(error).__name__)
        for role in reversed(ROLES):
            try:
                self.node_control(role, 'stop')
            except Exception as error:
                errors.append(role+':'+type(error).__name__)
        self.retired.add((self.session_id, self.generation))
        self.session_id = None
        self.state = 'fault' if fault or errors else 'standby'
        return errors

    def control_session(self, request, result):
        if request.command == 'health':
            result.accepted, result.state = True, self.state
            return result
        if not self.lock.acquire(blocking=False):
            result.reason = 'Session transition in progress'
            return result
        try:
            if request.command == 'start':
                if self.session_id or self.state != 'standby':
                    raise ValueError('Session already started or faulted')
                if not request.session_id or request.generation < 1 or (request.session_id, request.generation) in self.retired:
                    raise ValueError('Invalid or retired session')
                if request.mode not in {'voice','simulation','robot'}:
                    raise ValueError('Invalid mode')
                if self.offline and request.mode == 'robot':
                    raise ValueError('Offline robot access forbidden')
                self.session_id, self.generation, self.mode = request.session_id, request.generation, request.mode
                self.state = 'starting'
                try:
                    for role in ROLES:
                        self.node_control(role, 'start')
                    if self.managed_resources:
                        self.worker('activate', 90)
                    self.state = 'active'
                except Exception:
                    self.shutdown_session(fault=True)
                    raise
            elif request.command == 'stop':
                if (request.session_id, request.generation) != (self.session_id, self.generation):
                    raise ValueError('Session fence rejected')
                errors = self.shutdown_session()
                if errors:
                    raise RuntimeError('Resource cleanup failed')
            else:
                raise ValueError('Unknown command')
            result.accepted = True
        except Exception as error:
            result.reason = str(error)  # Local lifecycle errors contain no provider credentials.
        finally:
            result.state = self.state
            self.lock.release()
        return result

    def check_health(self):
        if self.state != 'active' or not self.lock.acquire(blocking=False):
            return
        try:
            try:
                # Every managed node must answer; no automatic restart or reacquire.
                for role in ROLES:
                    self.node_control(role, 'health')
                if self.managed_resources:
                    health = self.worker('health', 3)
                    if not health['active'] or health['failed']:
                        raise RuntimeError('Host worker failed')
                    self.worker('heartbeat', 3)
                call(ROOT/'host.sock', dict(op='heartbeat', session_id=self.session_id,
                                           generation=self.generation), 2)
            except Exception:
                self.shutdown_session(fault=True)
        finally:
            self.lock.release()
