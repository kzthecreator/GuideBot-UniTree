import sys
import unittest
from pathlib import Path
import threading
from unittest.mock import Mock, patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'GuideBot/conversation'))
from audio import LevelGate, StreamingSpeaker
from stepfun import RealtimeSession

def frame(amplitude):
    return np.full(320, amplitude, dtype='<i2').tobytes()

class GateTests(unittest.TestCase):
    def test_quiet_muted_and_loud_passes_without_length_change(self):
        gate = LevelGate(-35)
        self.assertEqual(gate.process(frame(100)), bytes(640))
        self.assertEqual(gate.process(frame(1500)), frame(1500))

    def test_hysteresis_and_release_preserve_quiet_tail(self):
        gate = LevelGate(-35)
        gate.process(frame(1000))
        self.assertEqual(gate.process(frame(400)), frame(400))
        for _ in range(9):
            self.assertEqual(gate.process(frame(50)), frame(50))
        self.assertEqual(gate.process(frame(50)), bytes(640))
        self.assertFalse(gate.open)

    def test_chunk_boundaries_do_not_change_output(self):
        pcm = frame(100) + frame(1800) + frame(50)*12
        first, second = LevelGate(-35), LevelGate(-35)
        expected = first.process(pcm)
        actual = b''.join(second.process(pcm[i:i+200]) for i in range(0,len(pcm),200))
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual),len(pcm))

    def test_gate_uses_aec_output_and_still_uploads_silence(self):
        s = RealtimeSession('dummy',Path('/tmp/unused-gate'),mic_gate_dbfs=-35)
        s.echo = Mock()
        s.speaker.is_playing = Mock(return_value=True)
        s.echo.process.return_value = frame(100)*8
        with patch('stepfun.microphone_packets',return_value=iter([frame(3000)*8])):
            s._capture()
        queued = b''.join(list(s.input_queue.queue))
        self.assertGreater(len(queued),0)
        self.assertFalse(any(queued))
        self.assertEqual(s.gate.stats['muted_frames'],8)
        self.assertFalse(s.stopping.is_set())

    def test_bypass_preserves_quiet_audio_and_resets_gate(self):
        gate = LevelGate(-35)
        gate.process(frame(2000))
        self.assertEqual(gate.process(frame(50), enabled=False), frame(50))
        self.assertFalse(gate.open)
        self.assertEqual(gate.process(frame(50), enabled=True), bytes(640))

    def test_session_only_gates_during_playback(self):
        s = RealtimeSession('dummy',Path('/tmp/unused-gate'),mic_gate_dbfs=-35)
        s.speaker.is_playing = Mock(side_effect=[False,True,False])
        with patch('stepfun.microphone_packets',return_value=iter([frame(100)*8]*3)):
            s._capture()
        self.assertEqual(s.gate.stats['muted_frames'],8)
        self.assertEqual(s.gate.stats['bypassed_frames'],16)
        self.assertFalse(s.stopping.is_set())

    def test_playback_state_ignores_cloud_buffer_and_covers_tail(self):
        speaker = StreamingSpeaker(threading.Event(), lambda error: None)
        speaker.feed('not-yet-submitted', frame(100))
        with patch('audio.time.monotonic', return_value=10):
            self.assertFalse(speaker.is_playing())
            speaker._submitting = True
            self.assertTrue(speaker.is_playing())
            speaker._submitting = False
            speaker._playback_until = 9.9
            self.assertTrue(speaker.is_playing())
        with patch('audio.time.monotonic', return_value=10.2):
            self.assertFalse(speaker.is_playing())

    def test_invalid_threshold_rejected(self):
        for value in (-100,1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):
                LevelGate(value)

    def test_interrupt_immediately_bypasses_gate_during_inflight_rpc(self):
        speaker = StreamingSpeaker(threading.Event(), lambda error: None)
        speaker._submitting = True
        speaker._playback_until = 100
        with patch('audio.time.monotonic', return_value=10):
            self.assertTrue(speaker.is_playing())
            speaker.interrupt()
            self.assertFalse(speaker.is_playing())
            speaker._playback_until = 101
            self.assertFalse(speaker.is_playing())

    def test_next_reply_reenables_gate_after_interruption(self):
        entered = [threading.Event(), threading.Event()]
        release = [threading.Event(), threading.Event()]
        errors, calls = [], []
        client = Mock()
        client.GetVolume.return_value = (0, {'volume':100})
        def play(*_):
            index = len(calls)
            calls.append(index)
            if index < 2:
                entered[index].set()
                release[index].wait(3)
            return 0, ''
        client.PlayStream.side_effect = play
        speaker = StreamingSpeaker(threading.Event(), errors.append, chunk_ms=200)
        pcm = np.full(6000,1000,dtype='<i2').tobytes()
        with patch('audio.load_audio_sdk',return_value=(lambda *_:None,lambda:client)):
            try:
                self.assertTrue(speaker.start())
                speaker.feed('old',pcm)
                self.assertTrue(entered[0].wait(2))
                speaker.interrupt()
                self.assertFalse(speaker.is_playing())
                speaker.feed('new',pcm)
                release[0].set()
                self.assertTrue(entered[1].wait(2))
                self.assertTrue(speaker.is_playing())
            finally:
                for event in release:
                    event.set()
                speaker.close()
        self.assertFalse(errors)

if __name__ == '__main__':
    unittest.main()
