"""Provider boundary tests: local inference must not leak cloud credentials."""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from GuideBot.gesture.catalog import Catalog
from GuideBot.gesture.provider import local_base_url, validate_configuration
from GuideBot.gesture.semantic_planner import SemanticPlanner
from runtime.app.planner_server import PlannerServer


class LocalPlannerTests(unittest.TestCase):
    @patch.dict(os.environ, {'GUIDEBOT_PLANNER_PROVIDER': 'local_qwen',
                           'DEEPSEEK_API_KEY': 'cloud-secret'}, clear=True)
    def test_local_request_has_schema_no_thinking_and_no_cloud_key(self):
        session = MagicMock()
        response = session.post.return_value.__enter__.return_value
        response.status_code = 200
        response.iter_content.return_value = [json.dumps({'choices': [dict(
            finish_reason='stop', message=dict(content='{"actions":[]}'))]}).encode()]
        planner = SemanticPlanner(Catalog(), session=session)
        self.assertEqual(planner.analyze('这里是普通的事实说明。')['actions'], [])
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], 'http://127.0.0.1:8088/v1/chat/completions')
        self.assertEqual(kwargs['headers'], {})
        self.assertFalse(session.trust_env)
        self.assertEqual(kwargs['json']['chat_template_kwargs'], {'enable_thinking': False})
        self.assertEqual(kwargs['json']['response_format']['type'], 'json_schema')
        validate_configuration()

    def test_local_address_cannot_send_text_to_remote_host(self):
        for address in ['https://127.0.0.1/v1', 'http://example.com/v1',
                        'http://secret@127.0.0.1/v1', 'http://127.0.0.1/v1?q=secret']:
            with patch.dict(os.environ, {'GUIDEBOT_PLANNER_BASE_URL': address}):
                with self.assertRaises(ValueError):
                    local_base_url()

    @patch.dict(os.environ, {'GUIDEBOT_PLANNER_PROVIDER': 'deepseek'}, clear=True)
    def test_cloud_requires_explicit_credentials(self):
        with self.assertRaises(ValueError):
            validate_configuration()

    @patch.dict(os.environ, {'GUIDEBOT_PLANNER_PROVIDER': 'local_qwen'}, clear=True)
    def test_reusing_service_does_not_take_process_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            server = PlannerServer(directory)
            with patch.object(server, 'ready', return_value=True), patch('subprocess.Popen') as spawn:
                server.start()
                server.stop()
                spawn.assert_not_called()
                self.assertIsNone(server.process)

    @patch.dict(os.environ, {'GUIDEBOT_PLANNER_PROVIDER': 'local_qwen',
                           'STEP_SECRET': 'private-voice-key'}, clear=True)
    def test_owned_server_is_cuda_only_and_has_no_cloud_secrets(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            binary, model = Path(directory)/'server', Path(directory)/'model'
            binary.touch()
            model.touch()
            with patch.dict(os.environ, {'GUIDEBOT_LLAMA_SERVER': str(binary),
                                        'GUIDEBOT_QWEN_MODEL': str(model)}):
                server = PlannerServer(directory)
                with patch.object(server, 'ready', side_effect=[False, True]), patch('subprocess.Popen') as spawn:
                    spawn.return_value.poll.return_value = None
                    server.start()
                    args, kwargs = spawn.call_args
                    self.assertEqual(args[0][args[0].index('--device')+1], 'CUDA0')
                    self.assertEqual(args[0][args[0].index('--host')+1], '127.0.0.1')
                    self.assertNotIn('STEP_SECRET', kwargs['env'])
                    server.stop()
                    self.assertTrue(server.log.closed)

    def test_stop_only_owned_process(self):
        with tempfile.TemporaryDirectory() as directory:
            server = PlannerServer(directory)
            server.process = MagicMock()
            server.process.poll.return_value = None
            server.stop()
            server.process.terminate.assert_called_once()
            server.process.wait.assert_called_once_with(timeout=10)
