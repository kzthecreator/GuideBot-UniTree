"""Asynchronous motion dispatch; explicit offline and Unitree backends.

Bindings are validated before planner startup. Socket I/O never runs on the
speech or scheduler thread. Hardware acquisition happens only at start().
"""
from collections import deque
import math
import threading
import time
import uuid

from drivers.unitree_motion.client import request


class OfflineExecutor:
    backend = "offline"
    simulated = True
    allow_late = False
    def __init__(self, socket_name, bindings, emit, *, timeout=.25, poll=.01):
        self.socket_name, self.bindings, self.emit = socket_name, dict(bindings), emit
        self.timeout, self.poll = timeout, poll
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.pending = deque()
        self.cancelled = set()
        self.known = set()
        self.active = None
        self.closing = self.failed = False
        self.thread = None
        self.listener = None

    def _event(self, state, command=None, **details):
        fields = dict(({k: command[k] for k in ('response_id', 'job_id')} if command else {}),
                      backend=self.backend, **details)
        self.emit('execution.' + state, **fields)
        if self.listener:
            self.listener('execution.' + state, **fields)

    def set_listener(self, listener):
        self.listener = listener

    def _request(self, payload):
        return request(self.socket_name, payload, timeout=self.timeout)

    def start(self):
        if self.thread is not None:
            raise RuntimeError('Create a new executor for each experiment')
        status = self._request({'状态': True})['status']
        self._check_identity(status)
        if status['ownership'] != 'owned' or status['state'] != 'idle':
            raise RuntimeError('Explicit offline acquire and idle state are required')
        self.thread = threading.Thread(target=self._run, name='offline-motion-dispatch', daemon=True)
        self.thread.start()
        self._event('ready')

    def _check_identity(self, status):
        if not status.get('offline_execution_v1'):
            raise RuntimeError('Experiment executor refuses a hardware or legacy server')

    def _cancel_payload(self, active):
        return {'cancel_execution': active['id']}

    def submit(self, command):
        """Called from Scheduler; copy the job without doing socket I/O."""
        command = dict(command)
        with self.lock:
            if self.closing or self.failed or command['response_id'] in self.cancelled:
                reason = 'executor_closed_or_reply_cancelled'
            elif command['job_id'] in self.known:
                reason = 'duplicate_job'
            elif self.active or self.pending:
                reason = 'executor_busy'
            else:
                self.known.add(command['job_id'])
                self.pending.append(command)
                reason = None
        if reason:
            self._event('rejected', command, reason=reason)
            return False
        self.wake.set()
        return True

    def cancel(self, response_id, reason='interrupted'):
        # A tombstone also blocks planner results arriving after interruption.
        with self.lock:
            self.cancelled.add(response_id)
        self.wake.set()

    def _prepare(self, command):
        binding = self.bindings.get(command['action'])
        if not binding or set(binding) != {'asset', 'minimum_total_ms'}:
            raise ValueError('unbound_action')
        if command.get('compressed'):
            raise ValueError('compressed_deadline_not_supported')
        start, arrival, duration = (command.get(k) for k in
                                   ('start_monotonic', 'arrival_monotonic', 'duration_s'))
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, arrival, duration)):
            raise ValueError('invalid_timing')
        transition_ms, duration_ms = round((arrival-start)*1000), round(duration*1000)
        if transition_ms <= 0 or duration_ms <= 0 or duration_ms > 120000 or transition_ms > 30000:
            raise ValueError('invalid_timing')
        total_ms = transition_ms + duration_ms
        if total_ms < binding['minimum_total_ms']:
            raise ValueError('below_minimum_duration')
        # Keep arrival fixed; tolerate at most 40 ms dispatch delay. Never
        # shorten the requested transition or core to catch up with audio.
        deadline = min(start + .04, arrival - .001)
        if time.monotonic() > deadline:
            raise ValueError('start_deadline_expired')
        physical_id = 'job_' + uuid.uuid4().hex
        sequence = {'sequence_name': physical_id, 'steps': [dict(
            type='motion', name=binding['asset'], transition_ms=transition_ms,
            duration_ms=duration_ms, hold_ms=0)]}
        return physical_id, deadline, {'execution': dict(job_id=physical_id,
            start_before=deadline, expected_ms=total_ms, sequence=sequence)}

    def _run(self):
        try:
            while True:
                self.wake.wait(self.poll)
                self.wake.clear()
                with self.lock:
                    active = self.active
                    cancel_active = bool(active and (self.closing or
                                         active['command']['response_id'] in self.cancelled))
                    command = None
                    if not active and self.pending:
                        command = self.pending.popleft()
                        cancelled = self.closing or command['response_id'] in self.cancelled
                        if not cancelled:
                            # Reserve before releasing the lock; submit stays nonblocking.
                            self.active = active = dict(command=command, id=None, last=None, stop_sent=False)
                    closing = self.closing
                if command is not None and cancelled:
                    self._event('cancelled', command, reason='cancelled_before_dispatch')
                    continue
                if command is not None:
                    try:
                        physical_id, deadline, payload = self._prepare(command)
                    except ValueError as error:
                        self._event('rejected', command, reason=str(error))
                        with self.lock:
                            self.active = None
                        continue
                    # Wait for requested start, while allowing cancellation to preempt.
                    while time.monotonic() < command['start_monotonic']:
                        with self.lock:
                            cancelled = self.closing or command['response_id'] in self.cancelled
                        if cancelled:
                            break
                        self.wake.wait(min(self.poll, command['start_monotonic']-time.monotonic()))
                        self.wake.clear()
                    with self.lock:
                        cancelled = self.closing or command['response_id'] in self.cancelled
                    if cancelled:
                        self._event('cancelled', command, reason='cancelled_before_dispatch')
                        with self.lock:
                            self.active = None
                        continue
                    active['id'] = physical_id
                    try:
                        self._request(payload)
                    except ValueError as error:
                        self._event('rejected', command, reason=str(error))
                        with self.lock:
                            self.active = None
                        continue
                    self._event('accepted', command, execution_id=physical_id)
                if active and active['id']:
                    with self.lock:
                        cancel_active = self.closing or active['command']['response_id'] in self.cancelled
                    if cancel_active and not active['stop_sent']:
                        self._request(self._cancel_payload(active))
                        active['stop_sent'] = True
                        self._event('cancel_requested', active['command'])
                    status = self._request({'状态': True})['status']
                    self._check_identity(status)
                    receipt = status['executions'].get(active['id'])
                    if not receipt:
                        raise RuntimeError('Missing correlated execution receipt')
                    state = receipt['state']
                    if state != active['last']:
                        self._event('driver_' + state, active['command'], receipt=receipt)
                        active['last'] = state
                    if state in {'completed', 'cancelled', 'rejected'}:
                        with self.lock:
                            self.active = None
                with self.lock:
                    if closing and not self.active and not self.pending:
                        return
        except Exception as error:
            # Fail closed: no reconnect/replay of uncertain old jobs.
            with self.lock:
                self.failed = True
                self.pending.clear()
            self._event('fault', active['command'] if active else None,
                        reason=type(error).__name__, execution_state='unknown',
                        requires_server_inspection=True)

    def close(self):
        with self.lock:
            self.closing = True
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=4)
            if self.thread.is_alive():
                raise RuntimeError('Offline executor did not drain; inspect server before release')


class UnitreeExecutor(OfflineExecutor):
    """Explicit real-server backend; never spawns the service or replays on loss."""
    backend = 'unitree'
    simulated = False
    allow_late = True

    def __init__(self, socket_name, bindings, emit, *, skip_joint_limits=False, **kwargs):
        super().__init__(socket_name, bindings, emit, **kwargs)
        self.skip_joint_limits = skip_joint_limits
        self.acquired = False

    def _check_identity(self, status):
        if not status.get('execution_v1') or status.get('offline_execution_v1'):
            raise RuntimeError('Unitree backend requires the updated hardware service')
        if bool(status.get('joint_limits_skipped')) != self.skip_joint_limits:
            raise RuntimeError('Joint limit option differs between conversation and motion service')

    def start(self):
        if self.thread is not None:
            raise RuntimeError('Create a new executor for each conversation')
        status = self._request({'状态': True})['status']
        self._check_identity(status)
        if status['ownership'] != 'released' or status['state'] != 'idle':
            raise RuntimeError('Motion service must start released and idle')
        self._request({'接管': True})
        self.acquired = True
        deadline = time.monotonic()+8
        try:
            while time.monotonic() < deadline:
                status = self._request({'状态': True})['status']
                self._check_identity(status)
                if status['ownership'] == 'owned':
                    break
                if status['ownership'] == 'released':
                    raise RuntimeError('Motion service rejected acquisition; inspect its terminal')
                time.sleep(.03)
            else:
                raise TimeoutError('Motion acquisition did not complete within 8 seconds')
            self.thread = threading.Thread(target=self._run, name='unitree-motion-dispatch', daemon=True)
            self.thread.start()
            self._event('ready', joint_limits_skipped=self.skip_joint_limits)
        except Exception:
            self.close()
            raise

    def _prepare(self, command):
        binding = self.bindings.get(command['action'])
        if not binding:
            raise ValueError('unbound_action')
        start, arrival, duration = (command.get(k) for k in
                                   ('start_monotonic', 'arrival_monotonic', 'duration_s'))
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, arrival, duration)):
            raise ValueError('invalid_timing')
        # Keep full trajectory duration. A missing/short lead-in gets a 300 ms
        # transition; late requests run late, rather than accelerating the robot.
        transition_ms = max(300, round((arrival-start)*1000))
        duration_ms = round(duration*1000)
        total_ms = transition_ms+duration_ms
        if duration_ms < 1 or duration_ms > 120000 or transition_ms > 30000:
            raise ValueError('invalid_timing')
        if total_ms < binding['minimum_total_ms']:
            raise ValueError('below_minimum_duration')
        physical_id = 'job_'+uuid.uuid4().hex
        deadline = max(start, time.monotonic())+.25
        self._event('timing', command, transition_ms=transition_ms, duration_ms=duration_ms,
                    requested_arrival=arrival, synchronization='best_effort',
                    joint_limits_skipped=self.skip_joint_limits)
        sequence = {'sequence_name': physical_id, 'steps': [dict(type='motion', name=binding['asset'],
                    transition_ms=transition_ms, duration_ms=duration_ms, hold_ms=0)]}
        return physical_id, deadline, {'execution': dict(job_id=physical_id,
            start_before=deadline, expected_ms=total_ms, sequence=sequence)}

    def close(self):
        try:
            super().close()
        finally:
            if self.acquired:
                try:
                    status = self._request({'状态': True})['status']
                    self._check_identity(status)
                    deadline = time.monotonic()+10
                    release_sent = False
                    while status['ownership'] != 'released' and time.monotonic() < deadline:
                        if status['ownership'] == 'owned' and not release_sent:
                            self._request({'释放': True})
                            release_sent = True
                        time.sleep(.03)
                        status = self._request({'状态': True})['status']
                        self._check_identity(status)
                    if status['ownership'] != 'released':
                        raise TimeoutError('Motion ownership release did not complete')
                    self.acquired = False
                    self._event('released')
                except Exception as error:
                    self.failed = True
                    self._event('release_failed', reason=type(error).__name__, requires_server_inspection=True)
