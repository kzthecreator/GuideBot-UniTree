import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from GuideBot.runtime.planner_config import load_planner_config


class ConfigTests(unittest.TestCase):
    def test_json_escapes_literal_values_and_preserves_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'planner.env'
            path.write_text('DEEPSEEK_API_KEY="literal$token\\\""\nDEEPSEEK_MODEL="saved"\n')
            with patch.dict(os.environ, {'DEEPSEEK_MODEL':'existing'}, clear=True):
                load_planner_config(path)
                self.assertEqual(os.environ['DEEPSEEK_API_KEY'], 'literal$token"')
                self.assertEqual(os.environ['DEEPSEEK_MODEL'], 'existing')

    def test_rejects_unexpected_keys_before_applying(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'planner.env'
            path.write_text('DEEPSEEK_API_KEY="test"\nUNEXPECTED="value"\n')
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ValueError):load_planner_config(path)
                self.assertNotIn('DEEPSEEK_API_KEY',os.environ)
