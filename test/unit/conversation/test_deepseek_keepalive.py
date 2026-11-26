"""Cloud provider defaults and request-scoped versus service-scoped ownership."""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock,patch
from GuideBot.gesture.catalog import Catalog
from GuideBot.gesture.provider import provider_name,validate_configuration
from GuideBot.gesture.semantic_planner import SemanticPlanner
from GuideBot.gesture.service import GestureService


class DeepSeekKeepaliveTests(unittest.TestCase):
    @patch.dict(os.environ,{},clear=True)
    def test_default_is_deepseek_and_requires_key(self):
        self.assertEqual(provider_name(),'deepseek')
        with self.assertRaises(ValueError):validate_configuration()

    def response(self,session):
        response=session.post.return_value.__enter__.return_value
        response.status_code=200
        response.iter_content.return_value=[json.dumps({'choices':[{'finish_reason':'stop','delta':{'content':'{"actions":[]}'}}]}).join(['data: ', '\n\ndata: [DONE]\n\n']).encode()]

    @patch.dict(os.environ,{'DEEPSEEK_API_KEY':'test-only'},clear=True)
    def test_cloud_reuses_one_owned_session_and_closes_once(self):
        with patch('GuideBot.gesture.semantic_planner.requests.Session') as factory, \
                patch('GuideBot.gesture.semantic_planner.requests.post',side_effect=AssertionError('Unmocked HTTP prohibited')):
            self.response(factory.return_value)
            planner=SemanticPlanner(Catalog(),provider='deepseek')
            factory.assert_called_once_with()
            planner.analyze('这里是用于测量时延的普通介绍。')
            planner.analyze('这是第二段用于测量时延的文字。')
            factory.assert_called_once_with()
            self.assertEqual(factory.return_value.post.call_count,2)
            for call in factory.return_value.post.call_args_list:
                self.assertTrue(call.kwargs['json']['stream'])
            planner.close();planner.close()
            factory.return_value.close.assert_called_once_with()

    def test_injected_session_is_not_owned(self):
        session=MagicMock()
        planner=SemanticPlanner(Catalog(),provider='deepseek',api_key='test-only',session=session)
        planner.close()
        session.close.assert_not_called()

    def test_service_closes_its_planner_without_starting_hardware(self):
        planner=MagicMock();planner.semantic=True
        with tempfile.TemporaryDirectory() as directory:
            service=GestureService(directory,planner=planner)
            service.close()
            planner.close.assert_called_once_with()

if __name__=='__main__':unittest.main()
