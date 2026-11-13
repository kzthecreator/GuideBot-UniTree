import sys
import json
import socket
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'GuideBot/conversation'))
from stepfun import RealtimeSession
import websocket


class VadTests(unittest.TestCase):
    def session(self):
        s = RealtimeSession('dummy', Path('/tmp/unused-g1-test'))
        s.speaker = Mock()
        s.report = Mock()
        s.active.add('reply1')
        return s

    def test_captured_backchannel_does_not_cut_reply(self):
        s = self.session()
        s.on_event({'type': 'input_audio_buffer.speech_started', 'item_id': 'noise'})
        s.on_event({'type': 'input_audio_buffer.speech_backchannel', 'item_id': 'noise'})
        s.on_event({'type': 'input_audio_buffer.cleared'})
        s.speaker.interrupt.assert_not_called()
        self.assertNotIn('reply1', s.discarded)

    def test_confirmed_interruption_cuts_reply_once(self):
        s = self.session()
        s.on_event({'type': 'input_audio_buffer.speech_started', 'item_id': 'user'})
        s.speaker.interrupt.assert_not_called()
        s.on_event({'type': 'input_audio_buffer.speech_interrupted', 'item_id': 'user'})
        s.on_event({'type': 'input_audio_buffer.speech_interrupted', 'item_id': 'user'})
        s.speaker.interrupt.assert_called_once()
        self.assertIn('reply1', s.discarded)

    def test_late_chunks_only_discarded_after_confirmation(self):
        s = self.session()
        s.on_event({'type': 'input_audio_buffer.speech_started', 'item_id': 'user'})
        s.on_event({'type': 'response.audio.delta', 'response_id': 'reply1', 'delta': 'AQABAA=='})
        self.assertEqual(s.speaker.feed.call_count, 1)
        s.on_event({'type': 'input_audio_buffer.speech_interrupted', 'item_id': 'user'})
        s.on_event({'type': 'response.audio.delta', 'response_id': 'reply1', 'delta': 'AQABAA=='})
        self.assertEqual(s.speaker.feed.call_count, 1)
        s.on_event({'type': 'response.created', 'response': {'id': 'reply2'}})
        s.on_event({'type': 'response.audio.delta', 'response_id': 'reply2', 'delta': 'AQABAA=='})
        self.assertEqual(s.speaker.feed.call_count, 2)
        self.assertFalse(s.stopping.is_set())

    def test_configured_energy_sent_to_server(self):
        s = RealtimeSession('dummy', Path('/tmp/unused-g1-test'), vad_energy=4000)
        s.ws = Mock()
        s.on_event({'type': 'session.created'})
        payload = json.loads(s.ws.send.call_args.args[0])
        self.assertEqual(payload['session']['turn_detection']['energy_awakeness_threshold'], 4000)
        with self.assertRaises(ValueError):
            RealtimeSession('dummy', Path('/tmp/unused-g1-test'), vad_energy=5001)

    def test_stop_wakes_blocked_websocket_receiver(self):
        left, right = socket.socketpair()
        connection = websocket.WebSocket(enable_multithread=True)
        connection.sock = left
        connection.connected = True
        s = self.session()
        s.ws = websocket.WebSocketApp('ws://unused')
        s.ws.sock = connection
        exited = threading.Event()

        def receive():
            try:
                connection.recv_data_frame()
            except Exception:
                pass
            finally:
                exited.set()

        thread = threading.Thread(target=receive, daemon=True)
        thread.start()
        try:
            s._close_socket()
            self.assertTrue(exited.wait(1), 'Receiver stayed blocked after stop')
            thread.join(1)
        finally:
            right.close()
            left.close()


if __name__ == '__main__':
    unittest.main()
