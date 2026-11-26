"""Resource worker controlled by ROS session requests, never by stdin."""
import json
from pathlib import Path
import threading
import time

from runtime.app.services import build_session, prepare, validate_options
from runtime.ipc.transport import ROSGestureService
from runtime.app.workers.motion import MotionRuntime
from runtime.app.host_lifecycle import HostLifecycleEndpoint


class VoiceWorker:
    def __init__(self, options, root, session_id, prepared):
        validate_options(options)
        self.options, self.root, self.session_id = options, Path(root), session_id
        self.prepared = prepared
        self.session = self.motion = self.host_lifecycle = None
        self.generation = 1
        self.state = 'standby'
        self.authorized = False
        self.last_heartbeat = time.monotonic()
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.watchdog = threading.Thread(target=self.watch, daemon=True, name='resource-watchdog')
        self.watchdog.start()
        self.result = None

    def rpc(self, request):
        if request.get('session_id') != self.session_id or request.get('generation') != self.generation:
            raise ValueError('Resource session fence rejected')
        op = request['op']
        if op == 'authorize':
            if self.state != 'standby':
                raise ValueError('Authorization only allowed in standby')
            self.authorized = True
            return True
        if op == 'health':
            session = self.session
            return dict(active=self.state == 'active', state=self.state,
                        failed=self.state == 'fault' or bool(session and session.stopping.is_set()))
        if op == 'tour':
            if (self.state != 'active' or self.options.get('service') != 'tour'
                    or self.session is None):
                raise ValueError('Tour service is not active')
            return self.session.control(request['command'], **request.get('fields', {}))
        if op == 'heartbeat':
            self.last_heartbeat = time.monotonic()
            return True
        if op == 'activate':
            with self.lock:
                if self.state != 'standby' or not self.authorized:
                    raise ValueError('Resource not authorized or already used')
                self.state = 'starting'
                try:
                    directory = self.root/'session'
                    if self.prepared is None:
                        self.prepared = prepare(self.options)
                    self.session = build_session(self.options, directory, self.prepared,
                        lambda *args, **kwargs: ROSGestureService(*args, **kwargs,
                            root=self.root/'ipc', managed=True, session_id=self.session_id))
                    if self.options.get('gesture_backend') == 'unitree':
                        self.motion = MotionRuntime()
                        self.motion.log_directory = directory
                        self.motion.start()
                    if self.options.get('service') == 'tour':
                        self.host_lifecycle = HostLifecycleEndpoint(
                            self.root/'ipc', self.session_id, self.generation)
                        self.host_lifecycle.start()
                    self.session.start()
                    deadline = time.monotonic()+25
                    while not self.session.ready.wait(.1):
                        if self.session.stopping.is_set() or time.monotonic() > deadline:
                            raise RuntimeError('Voice failed to become ready')
                    self.last_heartbeat = time.monotonic()
                    self.state = 'active'
                    return True
                except BaseException as error:
                    if self.session:
                        self.session.fail(error)
                    else:
                        (self.root/'session/result.json').write_text(json.dumps(
                            dict(errors=[type(error).__name__], phase='resource_preparation')))
                    self._deactivate()
                    self.state = 'fault'
                    raise
        if op == 'deactivate':
            with self.lock:
                self._deactivate()
                return True
        raise ValueError('Unknown resource operation')

    def _deactivate(self):
        self.state = 'stopping'
        try:
            if self.session is not None:
                session, self.session = self.session, None
                self.result = session.stop()
                (self.root/'session/result.json').write_text(json.dumps(self.result, ensure_ascii=False, indent=2))
        finally:
            if self.motion is not None:
                motion, self.motion = self.motion, None
                motion.stop()
            if self.host_lifecycle is not None:
                endpoint, self.host_lifecycle = self.host_lifecycle, None
                endpoint.close()
            self.state = 'stopped'

    def watch(self):
        while not self.stopping.wait(.2):
            if self.state == 'active' and time.monotonic()-self.last_heartbeat > 4:
                with self.lock:
                    if self.state == 'active':
                        self._deactivate()
                        self.state = 'fault'

    def close(self):
        self.stopping.set()
        with self.lock:
            if self.state not in {'stopped','standby'}:
                self._deactivate()
        self.watchdog.join(timeout=5)
