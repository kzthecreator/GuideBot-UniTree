import tempfile
from pathlib import Path
import unittest

from GuideBot.ros2.protocol import Fence, context_to_wire, context_from_wire
from GuideBot.runtime.ipc import Server, call


class ROSProtocolTests(unittest.TestCase):
    def test_generation_duplicate_and_expired_job_fences(self):
        fence = Fence(clock=lambda: 10)
        fence.start('s', 1)
        fence.job('s',1,'job','r',12)
        for args in [('s',1,'job','r',12), ('s',2,'next','r',12), ('s',1,'late','r',9)]:
            with self.assertRaises(ValueError):
                fence.job(*args)

    def test_cancel_closes_reply_and_old_sequence(self):
        fence = Fence()
        fence.start('s',1)
        fence.input('s',1,2,'cancel','r')
        for args in [('s',1,3,'text','r'),('s',1,1,'text','new')]:
            with self.assertRaises(ValueError):
                fence.input(*args)
        fence.close()
        with self.assertRaises(ValueError):
            fence.start('s',1)
        with self.assertRaises(ValueError):
            fence.check('s',1)

    def test_context_round_trip_requires_explicit_state(self):
        raw = dict(stage='listening', history=[], facts=[],
                   scene=dict(confirmed=True,direction='left',target_id='A'))
        wire = context_to_wire(raw,'s',1,2,12)
        # Fill generated ROS default fields for the conversion under test.
        self.assertEqual(context_from_wire(wire),raw)
        self.assertFalse(wire['navigation_valid'])
        self.assertFalse(wire['task_valid'])

    def test_private_ipc_frames_and_sanitizes_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'rpc.sock'
            def handler(value):
                if value.get('bad'):
                    raise ValueError('must-not-expose-secret')
                return value
            server = Server(path,handler)
            try:
                self.assertEqual(call(path, {'token':1}), {'token':1})
                with self.assertRaisesRegex(RuntimeError, '^ValueError$'):
                    call(path, {'bad':True})
            finally:
                server.close()

class ROSHostAdapterTests(unittest.TestCase):
    def test_constructing_robot_adapter_does_not_contact_robot(self):
        from unittest.mock import Mock
        from GuideBot.runtime.transport import ROSGestureService
        with tempfile.TemporaryDirectory() as directory:
            service = ROSGestureService(directory,catalog=Mock(),execution_mode='robot',root=directory)
            service.executor.request = Mock()
            self.assertIsNone(service.server)
            self.assertFalse(service.running)
            service.executor.request.assert_not_called()

    def test_transport_loss_requests_stop_and_reports_once(self):
        from unittest.mock import Mock
        from GuideBot.runtime.transport import ROSGestureService
        callback = Mock()
        with tempfile.TemporaryDirectory() as directory:
            service = ROSGestureService(directory,callback,catalog=Mock(),execution_mode='robot',root=directory)
            service.executor.request = Mock(return_value={})
            service._fail('lost')
            service._fail('lost')
            service.executor.request.assert_called_once_with({'停止': True})
            self.assertTrue(service.failed.is_set())
            self.assertFalse(service.running)
            callback.assert_called_once_with('gesture.transport_lost',reason='lost')

    def test_cancellation_has_priority_over_pending_text(self):
        from unittest.mock import Mock
        from GuideBot.runtime.transport import ROSGestureService
        with tempfile.TemporaryDirectory() as directory:
            service = ROSGestureService(directory,catalog=Mock(),root=directory)
            service.submit('text','r',text='old')
            service.submit('cancel','r',reason='interrupt')
            self.assertEqual(service.queue.get_nowait()[2],'cancel')


if __name__ == '__main__':
    unittest.main()
