"""Native standalone AGC2 stream framing checks; no audio devices."""
import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'GuideBot/conversation'))
from agc import AGC2


class AGC2Tests(unittest.TestCase):
    def test_silence_stays_silent(self):
        agc = AGC2()
        try:
            self.assertEqual(agc.process(bytes(32000)), bytes(32000))
        finally:
            agc.close()

    def test_arbitrary_pcm_packet_boundaries_preserve_result(self):
        pcm = np.rint(np.sin(np.arange(16000)*.17)*2000).astype('<i2').tobytes()
        whole, split = AGC2(), AGC2()
        try:
            expected = whole.process(pcm)
            actual = b''.join(split.process(pcm[i:i+514]) for i in range(0, len(pcm), 514))
            self.assertEqual(actual, expected)
            self.assertEqual(len(actual), len(pcm))
        finally:
            whole.close()
            split.close()

    def test_full_scale_and_sudden_level_changes_respect_minus1_ceiling(self):
        agc = AGC2()
        # A quiet signal followed by an adversarial full-scale transient.
        data = np.concatenate([np.ones(16000)*10, np.tile([32767, -32768], 8000)]).astype('<i2')
        try:
            output = np.frombuffer(agc.process(data.tobytes()), dtype='<i2').astype(float)
            self.assertLessEqual(np.max(np.abs(output)), np.floor(32768*10**(-1/20)))
            self.assertEqual(agc.stats['above_minus1_samples'], 0)
            self.assertEqual(agc.stats['samples'], len(data))
        finally:
            agc.close()

    def test_invalid_ceiling_cannot_disable_peak_protection(self):
        with self.assertRaises(RuntimeError):
            AGC2(ceiling_dbfs=0)


if __name__ == '__main__':
    unittest.main()
