"""Heartbeat probes are offline: no API, robot or audio device."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from GuideBot.conversation.websocket_diagnostics import WebSocketDiagnostics
from GuideBot.conversation.stepfun import RealtimeSession


class Clock:
    def __init__(self):
        self.now = 100.
    def __call__(self):
        return self.now


class DiagnosticsTests(unittest.TestCase):
    def test_audio_does_not_count_as_pong_and_rtt_is_monotonic(self):
        clock = Clock()
        diagnostics = WebSocketDiagnostics(clock=clock)
        connection = Mock()
        diagnostics.attach(connection)
        connection.ping('')
        clock.now += 2
        diagnostics.audio_received()
        state = diagnostics.snapshot()
        self.assertEqual(state['ping_sent_at'], 100)
        self.assertEqual(state['last_audio_delta_at'], 102)
        self.assertIsNone(state['pong_received_at'])
        self.assertIsNone(state['ping_rtt_ms'])
        diagnostics.pong_received(b'')
        self.assertEqual(diagnostics.snapshot()['ping_rtt_ms'], 2000)

    def test_slow_receiver_callback_and_stage_are_visible(self):
        clock = Clock()
        diagnostics = WebSocketDiagnostics(clock=clock)
        with diagnostics.callback():
            with diagnostics.stage('speaker.feed'):
                clock.now += 12
        state = diagnostics.snapshot()
        self.assertEqual(state['event_loop_lag_ms'], 12000)
        self.assertEqual(state['max_stage_ms']['speaker.feed'], 12000)
        self.assertEqual(diagnostics.drain()[-1]['kind'], 'websocket.callback_slow')

    def test_ping_failure_is_not_reported_as_successful_send(self):
        diagnostics = WebSocketDiagnostics()
        connection = Mock()
        connection.ping.side_effect = OSError('sensitive detail')
        diagnostics.attach(connection)
        with self.assertRaises(OSError):
            connection.ping('')
        self.assertIsNone(diagnostics.snapshot()['ping_sent_at'])
        self.assertNotIn('sensitive detail', json.dumps(diagnostics.drain()))

    def test_timeout_preserves_heartbeat_snapshot_before_session_shutdown(self):
        with tempfile.TemporaryDirectory() as root:
            session = RealtimeSession('test-secret', Path(root), instructions='soul',
                                      aec=False, diagnose_audio=False, mic_gate_dbfs=None)
            session.ws = Mock()
            session.log = (Path(root) / 'events.jsonl').open('w')
            session._socket_error(TimeoutError('ping/pong timed out'))
            self.assertTrue(session.stopping.is_set())
            session.ws.close.assert_called_once()
            state = session.websocket_diagnostics.snapshot()
            self.assertEqual(state['websocket_close_reason'], 'ping/pong timed out')
            session.log.close()
            logs = [json.loads(line) for line in (Path(root) / 'events.jsonl').read_text().splitlines()]
            self.assertTrue(any(row['type'] == 'websocket.diagnostics' for row in logs))

    def test_real_session_receiver_exposes_slow_audio_stage(self):
        session = RealtimeSession('dummy', Path('/tmp/unused-heartbeat-test'), instructions='soul',
                                  aec=False, diagnose_audio=False, mic_gate_dbfs=None)
        clock = Clock()
        session.websocket_diagnostics = WebSocketDiagnostics(clock=clock)
        session.active.add('reply')
        def feed(*args):
            clock.now += 12
            return b'\0\0'
        session.speaker = Mock()
        session.speaker.feed.side_effect = feed
        session._socket_message(None, json.dumps(dict(type='response.audio.delta',
                                                      response_id='reply', delta='AAAAAA==')))
        state = session.websocket_diagnostics.snapshot()
        self.assertEqual(state['max_stage_ms']['speaker.feed'], 12000)
        self.assertEqual(state['event_loop_lag_ms'], 12000)
        self.assertIsNone(state['pong_received_at'])

    def test_production_heartbeat_thresholds_stay_unchanged(self):
        session = RealtimeSession('dummy', Path('/tmp/unused-heartbeat-test'), instructions='soul',
                                  aec=False, diagnose_audio=False, mic_gate_dbfs=None)
        session.ws = Mock()
        session._run_socket()
        session.ws.run_forever.assert_called_once_with(ping_interval=20, ping_timeout=10)


class LibraryReceiveLoopTests(unittest.TestCase):
    def run_socket_pair(self, blocked):
        """Real websocket-client framing/thread/check; local peer replies to Ping."""
        import base64
        import hashlib
        import socket
        import threading
        import time
        import websocket

        left, right = socket.socketpair()
        right.settimeout(2)
        pong_sent = threading.Event()
        callback_entered = threading.Event()
        server_errors, errors = [], []
        diagnostics = WebSocketDiagnostics()

        def server():
            try:
                request = b''
                while b'\r\n\r\n' not in request:
                    request += right.recv(4096)
                key = next(line.split(b':', 1)[1].strip() for line in request.split(b'\r\n')
                           if line.lower().startswith(b'sec-websocket-key:'))
                accept = base64.b64encode(hashlib.sha1(
                    key + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                right.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                              b'Connection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
                peer = websocket.WebSocket()
                peer.sock, peer.connected = right, True
                frame = websocket.ABNF.create_frame('audio-probe', websocket.ABNF.OPCODE_TEXT)
                frame.mask = 0
                peer.send_frame(frame)
                while True:
                    frame = peer.recv_frame()
                    if frame.opcode == websocket.ABNF.OPCODE_PING:
                        reply = websocket.ABNF.create_frame(frame.data, websocket.ABNF.OPCODE_PONG)
                        reply.mask = 0
                        peer.send_frame(reply)
                        # Pin one outstanding Ping; a later Ping must not move
                        # the timeout deadline while this callback is blocked.
                        app.stop_ping.set()
                        pong_sent.set()
                    elif frame.opcode == websocket.ABNF.OPCODE_CLOSE:
                        reply = websocket.ABNF.create_frame(frame.data, websocket.ABNF.OPCODE_CLOSE)
                        reply.mask = 0
                        peer.send_frame(reply)
                        break
            except (OSError, websocket.WebSocketConnectionClosedException):
                pass
            except Exception as error:
                server_errors.append(error)

        def message(ws, value):
            with diagnostics.callback():
                diagnostics.audio_received()
                callback_entered.set()
                if blocked:
                    if not pong_sent.wait(1):
                        raise AssertionError('Local peer never returned Pong')
                    # Pong is already in the socket, but callback owns the receiver.
                    time.sleep(.15)

        def pong(ws, data):
            diagnostics.pong_received(data)
            ws.keep_running = False

        app = websocket.WebSocketApp('ws://localhost/probe', socket=left,
            on_open=lambda ws: diagnostics.attach(ws.sock), on_message=message,
            on_pong=pong, on_error=lambda ws, error: errors.append(str(error)))
        worker = threading.Thread(target=server, daemon=True)
        worker.start()
        try:
            app.run_forever(ping_interval=.05, ping_timeout=.02)
        finally:
            left.close()
            right.close()
            worker.join(2)
        self.assertTrue(callback_entered.is_set())
        self.assertTrue(pong_sent.is_set())
        self.assertFalse(server_errors)
        return diagnostics.snapshot(), errors

    def test_prompt_receiver_handles_pong(self):
        state, errors = self.run_socket_pair(False)
        self.assertEqual(errors, [])
        self.assertIsNotNone(state['pong_received_at'])
        self.assertIsNotNone(state['ping_rtt_ms'])

    def test_received_audio_and_peer_pong_can_still_timeout_when_callback_blocks(self):
        state, errors = self.run_socket_pair(True)
        self.assertIn('ping/pong timed out', errors)
        self.assertIsNotNone(state['last_audio_delta_at'])
        self.assertIsNone(state['pong_received_at'])
        self.assertGreaterEqual(state['event_loop_lag_ms'], 100)


if __name__ == '__main__':
    unittest.main()
