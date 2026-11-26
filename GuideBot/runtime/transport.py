"""Local resource adapter for ROS nodes; SDK workers do not import rclpy."""
import json
import itertools
import os
from pathlib import Path
import queue
import threading
import time
import uuid

from GuideBot.runtime.ipc import Server, call
from GuideBot.runtime.workers.motion_executor import MotionExecutor, MotionTimingRejected
from GuideBot.ros2.protocol import context_to_wire, INPUTS


class ROSGestureService:
    def __init__(self, directory, on_event=None, *, catalog, targets=(), execution_mode=None,
                 root=None, native_test_request=None, managed=False, session_id=None, generation=1):
        if targets:
            raise ValueError('ROS2 custom scene targets are not configured; use the standard catalog for acceptance')
        self.root = Path(root or os.environ['GUIDEBOT_ROS_IPC'])
        self.directory = Path(directory)
        self.callback = on_event
        self.session_id = session_id or uuid.uuid4().hex
        self.managed = managed
        self.generation = generation
        self.mode = execution_mode or 'simulation'
        self.catalog = catalog
        self.native_test_request = native_test_request
        self.executor = MotionExecutor(catalog, mode='robot' if native_test_request else self.mode,
                                       request=native_test_request)
        self.queue = queue.PriorityQueue(maxsize=256)
        self.serial = itertools.count()
        self.stopping = threading.Event()
        self.failed = threading.Event()
        self.sequence = 0
        self.context_version = 0
        self.last_heartbeat = 0
        self.server = self.thread = self.watchdog = self.log = None
        self.running = False
        self.virtual_end = 0
        self.error = None
        self.lock = threading.Lock()

    def rpc(self, request, timeout=8):
        return call(self.root/'ros.sock', request, timeout)

    def _control(self, command):
        result = self.rpc(dict(op='session', session_id=self.session_id,
                              generation=self.generation, command=command, mode=self.mode), 45)
        if not result['accepted']:
            raise RuntimeError('ROS session rejected: ' + result['reason'])
        return result

    def start(self):
        if self.server is not None:
            raise RuntimeError('Create a new ROS session per conversation')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.log = (self.directory/'gesture-transport.jsonl').open('w', encoding='utf-8')
        self.running = True
        self.last_heartbeat = time.monotonic()
        self.server = Server(self.root/'host.sock', self._host)
        try:
            self._control('attach' if self.managed else 'start')
            self.thread = threading.Thread(target=self._send, daemon=True, name='ros-events')
            self.watchdog = threading.Thread(target=self._watch, daemon=True, name='ros-watchdog')
            self.thread.start()
            self.watchdog.start()
        except BaseException:
            self.close()
            raise

    def _event(self, kind, details):
        with self.lock:
            if self.log and not self.log.closed:
                self.log.write(json.dumps(dict(kind=kind, monotonic=time.monotonic(), **details),
                                          ensure_ascii=False, default=str) + '\n')
                self.log.flush()
        if self.callback:
            self.callback(kind, **dict(details))

    def _host(self, request):
        if (request.get('session_id'), request.get('generation')) != (self.session_id, self.generation):
            raise ValueError('Host session fence rejected')
        op = request['op']
        if op == 'event':
            self._event(request['kind'], request['details'])
            return True
        if op == 'heartbeat':
            self.last_heartbeat = time.monotonic()
            return True
        if op == 'stop_motion':
            if self.mode == 'robot' or self.native_test_request is not None:
                return self.executor.request({'停止': True})
            self.virtual_end = 0
            return {'stopped': True}
        if not self.running or self.failed.is_set():
            raise ValueError('Host execution not authorized')
        if op == 'execute':
            event = request['event']
            try:
                result = self.executor.handle('gesture.command', event)
            except MotionTimingRejected as error:
                return dict(mode=self.mode, accepted=False, **error.diagnostic)
            self.virtual_end = event.get('end_monotonic') or event['arrival_monotonic'] + event.get('duration_s', 0)
            return result
        if op == 'motion_status':
            if self.mode == 'robot' or self.native_test_request is not None:
                return self.executor.request({'状态': True})['status']
            return dict(ownership='owned', state='playing' if time.monotonic() < self.virtual_end else 'idle')
        raise ValueError('Unknown host operation')

    def submit(self, kind, response_id=None, **details):
        if kind not in INPUTS:
            raise ValueError('Unknown ROS input')
        if self.stopping.is_set() or self.failed.is_set():
            return
        details['_queued_monotonic'] = time.monotonic()
        try:
            self.queue.put_nowait((0 if kind == 'cancel' else 1, next(self.serial), kind, response_id, details))
        except queue.Full:
            self._fail('ROS input queue overflow')

    def _send(self):
        try:
            while not self.stopping.is_set():
                try:
                    _, _, kind, rid, details = self.queue.get(timeout=.1)
                except queue.Empty:
                    continue
                if kind == 'transcript':
                    self.rpc({'op':'transcript', 'event':dict(session_id=self.session_id,
                              generation=self.generation, turn_id=str(rid or ''),
                              text=details['text'], final=details['final'])})
                    continue
                self.sequence += 1
                fields = dict(session_id=self.session_id, generation=self.generation,
                              sequence=self.sequence, response_id=str(rid or ''), kind=kind,
                              text=details.get('text',''), reason=details.get('reason', details.get('condition','')),
                              origin=float(details.get('origin',0)),
                              alignment_version=int(details.get('version',0)),
                              queued_monotonic=details['_queued_monotonic'],
                              anchors=[{k:r[k] for k in ('index','text','text_offset','start')}
                                       for r in details.get('anchors',[])])
                self.rpc({'op':'input', 'event':fields})
        except Exception as error:
            self._fail('ROS event transport failed: ' + type(error).__name__)

    def set_interaction_context(self, context, ttl=5, source='operator'):
        # Explicit state setter, never infer trusted scene/navigation from assistant wording.
        from GuideBot.gesture.service import GestureService
        checked = GestureService._validate_interaction_context(context)
        self.context_version += 1
        fields = context_to_wire(checked, self.session_id, self.generation,
                                 self.context_version, time.monotonic()+ttl, source)
        return self.rpc({'op':'context', 'context':fields})

    def request_base_pose(self, reason='interaction_state_change'):
        self.submit('base_pose', reason=reason)

    def transcript(self, text, turn_id='', final=False):
        if not self.running:
            return
        try:
            self.queue.put_nowait((1, next(self.serial), 'transcript', turn_id, dict(text=text, final=final)))
        except queue.Full:
            self._fail('ROS transcript queue overflow')

    def _watch(self):
        while not self.stopping.wait(.2):
            if time.monotonic() - self.last_heartbeat > 3:
                self._fail('ROS heartbeat expired')
                return

    def _fail(self, reason):
        if self.failed.is_set():
            return
        self.failed.set()
        self.error = reason
        self.running = False
        if self.mode == 'robot' or self.native_test_request is not None:
            try:
                self.executor.request({'停止': True})
            except Exception:
                pass
        self._event('gesture.transport_lost', {'reason':reason})

    def close(self):
        if self.server is None:
            return
        self.stopping.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=10)
        try:
            if not self.managed:
                self._control('stop')
        except Exception:
            if self.mode == 'robot' or self.native_test_request is not None:
                try:
                    self.executor.request({'停止': True})
                except Exception:
                    pass
        self.running = False
        self.server.close()
        self.server = None
        try:
            (self.root/'host.sock').unlink()
        except FileNotFoundError:
            pass
        if self.watchdog:
            self.watchdog.join(timeout=1)
        with self.lock:
            if self.log:
                self.log.close()
