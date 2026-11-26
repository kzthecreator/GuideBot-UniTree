"""Tour ROS host lifecycle and cleanup races, without cloud/audio/robot resources."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from runtime.app.host_lifecycle import HostLifecycleEndpoint
from runtime.ipc.channel import call
from runtime.app.workers.voice import VoiceWorker
from runtime.app.launcher import main, session_control
from GuideBot.conversation.playback import StreamingSpeaker


class TourLifecycleTests(unittest.TestCase):
    def test_host_endpoint_fence_and_no_motion_authority(self):
        with tempfile.TemporaryDirectory() as root:
            endpoint = HostLifecycleEndpoint(root,'s')
            endpoint.start()
            try:
                request = dict(op='heartbeat',session_id='s',generation=1)
                self.assertTrue(call(Path(root)/'host.sock',request))
                self.assertIsNotNone(endpoint.last_heartbeat)
                with self.assertRaises(ValueError):endpoint.handle(dict(request,generation=2))
                for op in ('execute','motion_status'):
                    with self.assertRaises(ValueError):endpoint.handle(dict(request,op=op))
            finally:
                endpoint.close();endpoint.close()
            self.assertFalse((Path(root)/'host.sock').exists())

    def test_worker_creates_tour_host_before_voice_start_and_releases_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);(root/'ipc').mkdir();(root/'session').mkdir()
            fake = MagicMock();fake.ready.wait.return_value=True;fake.stopping=threading.Event()
            fake.stop.return_value=dict(errors=[])
            fake.start.side_effect=lambda: self.assertTrue((root/'ipc/host.sock').exists())
            worker = VoiceWorker(dict(service='tour'),root,'s',{})
            request = dict(session_id='s',generation=1)
            try:
                with patch('runtime.app.workers.voice.build_session',return_value=fake), \
                        patch('runtime.app.workers.voice.MotionRuntime') as motion:
                    worker.rpc(dict(request,op='authorize'));worker.rpc(dict(request,op='activate'))
                    self.assertTrue(call(root/'ipc/host.sock',dict(request,op='heartbeat')))
                    self.assertTrue(worker.rpc(dict(request,op='health'))['active'])
                    motion.assert_not_called()
                    worker.rpc(dict(request,op='deactivate'))
                    self.assertFalse((root/'ipc/host.sock').exists())
                    fake.stop.assert_called_once()
            finally:worker.close()

    def test_start_failure_still_closes_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'ipc').mkdir();(root/'session').mkdir()
            fake=MagicMock();fake.start.side_effect=RuntimeError('startup failed')
            fake.stop.return_value=dict(errors=[])
            worker=VoiceWorker(dict(service='tour'),root,'s',{})
            request=dict(session_id='s',generation=1)
            try:
                with patch('runtime.app.workers.voice.build_session',return_value=fake):
                    worker.rpc(dict(request,op='authorize'))
                    with self.assertRaisesRegex(RuntimeError,'startup failed'):
                        worker.rpc(dict(request,op='activate'))
                self.assertFalse((root/'ipc/host.sock').exists())
                self.assertEqual(worker.state,'fault')
            finally:worker.close()

    def test_stop_retries_transition_but_start_does_not(self):
        pending=dict(accepted=False,state='active',reason='Session transition in progress')
        accepted=dict(accepted=True,state='standby',reason='')
        with patch('runtime.app.launcher.call',side_effect=[pending,accepted]) as rpc, \
                patch('runtime.app.launcher.time.sleep'):
            self.assertEqual(session_control(Path('/tmp'),'s','stop','voice'),accepted)
            self.assertEqual(rpc.call_count,2)
        with patch('runtime.app.launcher.call',return_value=pending) as rpc:
            with self.assertRaises(RuntimeError):session_control(Path('/tmp'),'s','start','voice')
            rpc.assert_called_once()

    def test_launcher_preserves_primary_error_when_stop_also_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'worker.ready').touch()
            runtime=MagicMock();runtime.root=root;runtime.timing='immediate'
            child=MagicMock();child.poll.return_value=None
            def control(root,sid,command,mode,*args):
                if command=='health':raise RuntimeError('PRIMARY health failure')
                if command=='stop':raise RuntimeError('SECONDARY cleanup failure')
                return dict(accepted=True,state='active')
            with patch('runtime.app.launcher.LocalRuntime',return_value=runtime), \
                    patch('runtime.app.launcher.subprocess.Popen',return_value=child), \
                    patch('runtime.app.launcher.session_control',side_effect=control), \
                    patch('runtime.app.launcher.call',return_value=True), \
                    patch('runtime.app.launcher.stop_worker'), \
                    patch('GuideBot.conversation.knowledge.load_secret',return_value='test-only'), \
                    patch('GuideBot.tour.assets.load_bundle'), \
                    patch('builtins.input',return_value=''),patch('builtins.print'):
                with self.assertRaisesRegex(RuntimeError,'PRIMARY health failure'):
                    main(['--service','tour'])
            runtime.stop.assert_called_once()

    def test_shutdown_interrupt_is_not_labelled_as_user_vad(self):
        events=[]
        speaker=StreamingSpeaker(threading.Event(),lambda error:None,
                                 on_event=lambda kind,**fields:events.append((kind,fields)))
        try:
            speaker.feed('tour',b'\0\0'*240)
            speaker.interrupt(reason='tour_stop')
            self.assertEqual(events[-1][1]['reason'],'tour_stop')
        finally:speaker.close()
