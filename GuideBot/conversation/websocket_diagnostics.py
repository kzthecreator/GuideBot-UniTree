"""Bounded, in-memory probes: never write logs from the ping/receive hot path.

All *_at values use time.monotonic(), in seconds. event_loop_lag_ms measures
receiver callback occupancy, NOT network latency or an asyncio scheduler probe.
RTT is observed when the receive loop processes Pong, not packet arrival time.
"""
from collections import deque
from contextlib import contextmanager
import threading
import time


class WebSocketDiagnostics:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.events = deque(maxlen=512)
        self.state = dict(ping_attempted_at=None, ping_sent_at=None,
                          ping_send_completed_at=None, ping_send_duration_ms=None,
                          pong_received_at=None, ping_rtt_ms=None,
                          last_audio_delta_at=None, event_loop_lag_ms=0.,
                          event_loop_lag_basis='receiver_callback_occupancy',
                          websocket_close_reason=None, websocket_close_code=None,
                          max_stage_ms={})
        self.pending = None
        self.callback_started = None
        self.dropped_events = 0

    def _record(self, kind, **fields):
        if len(self.events) == self.events.maxlen:
            self.dropped_events += 1
        self.events.append(dict(kind=kind, observed_at=self.clock(), **fields))

    def attach(self, connection):
        """Wrap only this connection's Ping send; retain the library's thread/timer."""
        original = connection.ping
        def ping(payload=''):
            started = self.clock()
            data = payload.encode('utf-8') if isinstance(payload, str) else payload
            with self.lock:
                self.state['ping_attempted_at'] = started
                self.pending = (started, data)
                self._record('websocket.ping_attempt', ping_attempted_at=started)
            try:
                result = original(payload)
            except Exception as error:
                with self.lock:
                    self.pending = None
                    self._record('websocket.ping_send_failed', error_type=type(error).__name__)
                raise
            completed = self.clock()
            with self.lock:
                self.state.update(ping_sent_at=started, ping_send_completed_at=completed,
                                  ping_send_duration_ms=(completed-started)*1000)
                self._record('websocket.ping_sent', ping_sent_at=started,
                             ping_send_completed_at=completed,
                             ping_send_duration_ms=(completed-started)*1000)
            return result
        connection.ping = ping

    def pong_received(self, data):
        now = self.clock()
        with self.lock:
            matched = self.pending is not None and self.pending[1] == data
            rtt = (now-self.pending[0])*1000 if matched else None
            self.state.update(pong_received_at=now, ping_rtt_ms=rtt)
            self._record('websocket.pong_received', pong_received_at=now,
                         ping_rtt_ms=rtt, matches_pending_ping=matched)
            if matched:
                self.pending = None

    def audio_received(self):
        with self.lock:
            self.state['last_audio_delta_at'] = self.clock()

    @contextmanager
    def callback(self):
        start = self.clock()
        with self.lock:
            self.callback_started = start
        try:
            yield
        finally:
            elapsed = (self.clock()-start)*1000
            with self.lock:
                self.state['event_loop_lag_ms'] = max(self.state['event_loop_lag_ms'], elapsed)
                self.callback_started = None
                if elapsed >= 100:
                    self._record('websocket.callback_slow', callback_elapsed_ms=elapsed,
                                 event_loop_lag_ms=elapsed)

    @contextmanager
    def stage(self, name):
        start = self.clock()
        try:
            yield
        finally:
            elapsed = (self.clock()-start)*1000
            with self.lock:
                maxima = self.state['max_stage_ms']
                maxima[name] = max(maxima.get(name, 0.), elapsed)
                if elapsed >= 100:
                    self._record('websocket.stage_slow', stage=name, elapsed_ms=elapsed)

    def closed(self, reason, code=None):
        with self.lock:
            # Preserve the original error when on_close later supplies no reason.
            if self.state['websocket_close_reason'] is None:
                self.state['websocket_close_reason'] = reason
            if code is not None:
                self.state['websocket_close_code'] = code
            self._record('websocket.closed', websocket_close_reason=self.state['websocket_close_reason'],
                         websocket_close_code=self.state['websocket_close_code'])

    def snapshot(self):
        with self.lock:
            state = dict(self.state, max_stage_ms=dict(self.state['max_stage_ms']),
                         dropped_events=self.dropped_events)
            state['callback_in_progress_ms'] = ((self.clock()-self.callback_started)*1000
                                                if self.callback_started is not None else 0.)
            return state

    def drain(self):
        with self.lock:
            events = list(self.events)
            self.events.clear()
            return events
