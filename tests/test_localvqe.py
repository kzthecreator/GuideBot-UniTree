import ctypes
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'GuideBot/conversation'))
from localvqe import LocalVQEEcho, Processor
from stepfun import RealtimeSession


class FakeProcessor:
    def __init__(self, **kwargs):
        self.model = Path('fake.gguf')
        self.references = []
    def process(self, near, ref, streaming=False):
        self.references.append(ref.copy())
        return near.copy()
    def close(self):
        pass


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.mock = patch('localvqe.Processor', FakeProcessor)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_partial_frames_preserve_sample_order(self):
        echo = LocalVQEEcho()
        pcm = np.arange(512, dtype='<i2').tobytes()
        self.assertEqual(echo.process(pcm[:160], .005), b'')
        actual = echo.process(pcm[160:], .032)
        self.assertEqual(actual, pcm)
        self.assertEqual(echo.stats['frames'], 2)

    def test_arrival_jitter_does_not_shift_sample_reference(self):
        echo = LocalVQEEcho()
        ref = np.arange(512, dtype='<i2')
        echo.add_reference(ref.tobytes(), 1)
        echo.process(bytes(512), 1.016)
        echo.process(bytes(512), 1.037)
        np.testing.assert_array_equal(np.concatenate(echo.processor.references), ref)

    def test_explicit_delay_and_stop_trim(self):
        echo = LocalVQEEcho(delay_ms=100)
        echo.add_reference(bytes(3200), 1)
        self.assertAlmostEqual(echo.reference[0][0], 1.1)
        echo.stop_reference(1.15)
        self.assertEqual(len(echo.reference[0][1]), 800)
        echo.add_reference(bytes(512), 1.2)
        self.assertAlmostEqual(echo.reference[-1][0], 1.3)


class NativeTests(unittest.TestCase):
    def test_model_gate_disabled_shape_and_lifecycle(self):
        processor = Processor()
        try:
            getter = processor.lib.localvqe_get_noise_gate
            getter.argtypes = [ctypes.c_size_t, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_float)]
            getter.restype = ctypes.c_int
            enabled, threshold = ctypes.c_int(), ctypes.c_float()
            self.assertEqual(getter(processor.context, ctypes.byref(enabled), ctypes.byref(threshold)), 0)
            self.assertEqual(enabled.value, 0)
            zero = np.zeros(256, dtype='<i2')
            output = processor.process(zero, zero, streaming=True)
            self.assertEqual(output.shape, zero.shape)
            self.assertLessEqual(int(np.abs(output.astype(int)).max()), 1)
            with self.assertRaises(ValueError):
                processor.process(zero, zero[:100], streaming=True)
        finally:
            processor.close()
            processor.close()
        with self.assertRaises(RuntimeError):
            processor.process(zero, zero, streaming=True)

    def test_realtime_start_selects_localvqe_before_connect(self):
        with patch('stepfun.LocalVQEEcho') as factory, patch('stepfun.websocket.WebSocketApp') as socket:
            socket.side_effect = RuntimeError('stop before network')
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                session = RealtimeSession('dummy', Path(directory), aec=True, vector_store_id='test')
                with self.assertRaisesRegex(RuntimeError, 'stop before network'):
                    session.start()
                factory.assert_called_once_with(0)
                session.stop()


if __name__ == '__main__':
    unittest.main()
