"""Speed modes remain native, bounded, optional, and reversible."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runtime.app.planner_server import PlannerServer


class PlannerSpeculationTests(unittest.TestCase):
    def command(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            binary, model = Path(directory)/'server', Path(directory)/'model'
            binary.touch(); model.touch()
            env = dict(GUIDEBOT_PLANNER_PROVIDER='local_qwen',
                       GUIDEBOT_LLAMA_SERVER=str(binary), GUIDEBOT_QWEN_MODEL=str(model))
            if mode is not None:
                env['GUIDEBOT_QWEN_SPECULATION'] = mode
            with patch.dict(os.environ, env, clear=True):
                server = PlannerServer(directory)
                try:
                    with patch.object(server, 'ready', side_effect=[False, True]), patch('subprocess.Popen') as spawn:
                        spawn.return_value.poll.return_value = None
                        server.start()
                        return spawn.call_args[0][0]
                finally:
                    server.stop()

    def test_default_keeps_original_decoder(self):
        self.assertNotIn('--spec-type', self.command(None))

    def test_explicit_off_keeps_original_decoder(self):
        self.assertNotIn('--spec-type', self.command('off'))

    def test_conservative_mode_has_measured_parameters(self):
        args = self.command('ngram-simple')
        self.assertEqual(args[args.index('--spec-type')+1], 'ngram-simple')
        self.assertEqual(args[args.index('--spec-ngram-simple-size-n')+1], '8')
        self.assertEqual(args[args.index('--spec-ngram-simple-size-m')+1], '16')

    def test_fast_mode_has_measured_parameters(self):
        args = self.command('ngram-map-k')
        self.assertEqual(args[args.index('--spec-type')+1], 'ngram-map-k')
        self.assertEqual(args[args.index('--spec-ngram-map-k-size-n')+1], '4')
        self.assertEqual(args[args.index('--spec-ngram-map-k-size-m')+1], '16')
        self.assertEqual(args[args.index('--spec-ngram-map-k-min-hits')+1], '1')

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            self.command('unmeasured arbitrary flags')

if __name__ == '__main__':
    unittest.main()
