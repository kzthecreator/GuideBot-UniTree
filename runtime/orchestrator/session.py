"""Transport-independent lifecycle policy shared by the ROS adapter.

Adapters provide node_control, worker, host_heartbeat and log_health_error.
Request and result objects only need the declared session-control fields.
"""
import threading

ROLES = ('motion', 'conversation', 'gesture')


class SessionCoordinator:
    def initialize_session(self, offline=False, managed_resources=True):
        self.session_id = None
        self.generation = 0
        self.mode = 'voice'
        self.state = 'standby'
        self.lock = threading.Lock()
        self.offline = offline
        self.managed_resources = managed_resources
        self.retired = set()

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
        if request.command == 'stop' and (request.session_id, request.generation) in self.retired:
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
                    stage = role+'_health'
                    self.node_control(role, 'health')
                if self.managed_resources:
                    stage = 'worker_health'
                    health = self.worker('health', 3)
                    if not health['active'] or health['failed']:
                        raise RuntimeError('Host worker failed')
                    stage = 'worker_heartbeat'
                    self.worker('heartbeat', 3)
                stage = 'host_heartbeat'
                self.host_heartbeat()
            except Exception as error:
                self.log_health_error('Session health failed at '+stage+': '+type(error).__name__)
                self.shutdown_session(fault=True)
        finally:
            self.lock.release()
