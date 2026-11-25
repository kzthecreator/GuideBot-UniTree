"""Real-backend wiring and lifecycle without sending commands to a real robot."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'GuideBot/conversation'))
import conversation
from stepfun import RealtimeSession
from GuideBot.gesture.execution import UnitreeExecutor
from GuideBot.gesture.catalog import Catalog, make_input, messages
from drivers.unitree_motion.assets import ROOT, conversation_assets
from drivers.unitree_motion.client import request
from tools.motion.offline_gesture_experiment import BUILD, REPO, wait_until


class WiringTests(unittest.TestCase):
    def test_hardware_catalog_only_exposes_published_trajectories(self):
        document, bindings = conversation_assets()
        catalog = Catalog(document=document, examples_path=ROOT/'conversation-few-shots.json')
        self.assertEqual(set(catalog.actions), set(bindings))
        self.assertIn('greet_wave', bindings)
        self.assertNotIn('present_center', bindings)  # draft
        self.assertNotIn('point', bindings)
        self.assertGreater(len(messages(catalog, make_input('r', '欢迎来到展厅。'))), 2)

    def test_hardware_session_construction_does_not_connect(self):
        with patch('GuideBot.gesture.execution.request') as transport:
            session = RealtimeSession('dummy', Path('/tmp/unused-motion-wire'), aec=False,
                gestures=True, gesture_backend='unitree', skip_joint_limits=True)
            self.assertIsInstance(session.gestures.executor, UnitreeExecutor)
            self.assertFalse(session.gestures.executor.acquired)
            transport.assert_not_called()
            session.gestures.close()
            transport.assert_not_called()

    def test_cli_hardware_selection_enables_gestures_but_waits_for_enter(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'offline-test-placeholder'}), \
             patch('conversation.read_soul', return_value='soul'), \
             patch('conversation.load_secret', return_value='dummy'), \
             patch('conversation.load_knowledge', return_value='kb-test'), \
             patch('conversation.RealtimeSession') as session, \
             patch('conversation.wait_for_enter', side_effect=RuntimeError('cancel')):
            with self.assertRaisesRegex(RuntimeError, 'cancel'):
                conversation.start_conversation(gesture_backend='unitree', skip_joint_limits=True)
            self.assertTrue(session.call_args.kwargs['gestures'])
            self.assertTrue(session.call_args.kwargs['skip_joint_limits'])
            session.return_value.start.assert_not_called()

    def test_acquire_and_release_are_explicit_and_options_must_match(self):
        events, calls = [], []
        status = dict(execution_v1=True, offline_execution_v1=False,
                      joint_limits_skipped=True, ownership='released', state='idle')
        def transport(payload):
            calls.append(payload)
            if '接管' in payload:
                status['ownership'] = 'owned'
            if '释放' in payload:
                status['ownership'] = 'released'
            return {'ok': True, 'status': dict(status)}
        executor = UnitreeExecutor('\0unused', {}, lambda k, **v: events.append(k), skip_joint_limits=True)
        with patch.object(executor, '_request', side_effect=transport):
            self.assertEqual(calls, [])
            executor.start()
            executor.close()
        self.assertIn({'接管': True}, calls)
        self.assertIn({'释放': True}, calls)
        self.assertIn('execution.released', events)
        bad = UnitreeExecutor('\0unused', {}, lambda *a, **k: None)
        with patch.object(bad, '_request', return_value={'status': status}):
            with self.assertRaisesRegex(RuntimeError, 'differs'):
                bad.start()

    def test_hardware_timing_keeps_core_and_adds_transition_for_zero_lead(self):
        events = []
        executor = UnitreeExecutor('\0unused', {'greet_wave':dict(asset='greet_wave', minimum_total_ms=2000)},
                                   lambda k, **v: events.append((k,v)))
        now = time.monotonic()
        job = dict(response_id='r', job_id='r:0', action='greet_wave', duration_s=2.,
                   start_monotonic=now, arrival_monotonic=now, compressed=True)
        _, _, payload = executor._prepare(job)
        step = payload['execution']['sequence']['steps'][0]
        self.assertEqual(step['duration_ms'], 2000)
        self.assertEqual(step['transition_ms'], 300)
        self.assertEqual(payload['execution']['expected_ms'], 2300)

    def test_late_hardware_plan_still_dispatches_without_acceleration(self):
        from GuideBot.gesture.catalog import Plan, units_for
        from GuideBot.gesture.scheduler import Scheduler
        class Backend:
            simulated = False
            allow_late = True
            def set_listener(self, listener): pass
            def submit(self, command):
                self.command = command
        backend = Backend()
        events = []
        scheduler = Scheduler(Catalog(), lambda k, **v: events.append((k,v)),
                              clock=lambda: 10., executor=backend)
        text = '欢迎来到这里'
        units = units_for(text)
        scheduler.text('r', text)
        scheduler.add('r', Plan('wave',0,3,{'duration_s':2.}), units)
        scheduler.alignment('r', dict(version=1, anchors=[dict(index=i,start=t,
            text=units[i]['text'],text_offset=units[i]['text_offset']) for i,t in [(0,1.),(3,2.)]]))
        scheduler.playback('r', 0.)
        scheduler.tick()
        self.assertEqual(backend.command['duration_s'], 2.)
        self.assertFalse(backend.command['simulated'])
        self.assertTrue(any(k == 'gesture.late' for k,_ in events))


@unittest.skipUnless((BUILD/'motion_library_server').is_file(), 'Build the service first')
class PublishedAssetsProtocolTests(unittest.TestCase):
    def test_all_published_assets_start_and_cancel_with_explicit_limit_skip_offline(self):
        # Real imported assets, but explicitly no DDS or robot connection.
        socket_name = 'guidebot_published_'+uuid.uuid4().hex
        process = subprocess.Popen([str(BUILD/'motion_library_server'), '--offline-server',
            '--skip-joint-limits', '--socket-name', socket_name,
            '--catalog', str(ROOT/'config/motion_catalog.json'), '--dir', str(ROOT/'motions'),
            '--poses', str(ROOT/'poses'), '--metadata', str(ROOT/'metadata'),
            '--limits', str(REPO/'drivers/unitree_motion/config/arm_joint_limits.json')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            socket_name = '\0'+socket_name
            def status():
                return request(socket_name, {'状态': True})['status']
            def ready():
                try:
                    return status()
                except OSError:
                    return None
            wait_until(ready)
            self.assertTrue(status()['joint_limits_skipped'])
            self.assertTrue(status()['offline_execution_v1'])
            request(socket_name, {'接管': True})
            wait_until(lambda: status()['ownership'] == 'owned')
            _, bindings = conversation_assets()
            for i, binding in enumerate(bindings.values()):
                job_id = 'published_'+str(i)
                duration = binding['minimum_total_ms']
                request(socket_name, {'execution':dict(job_id=job_id, start_before=time.monotonic()+1,
                    expected_ms=300+duration, sequence=dict(sequence_name=job_id, steps=[dict(
                        type='motion', name=binding['asset'], transition_ms=300,
                        duration_ms=duration, hold_ms=0)]))})
                wait_until(lambda: status()['executions'][job_id]['state'] in {'running','rejected'})
                receipt = status()['executions'][job_id]
                self.assertEqual(receipt['state'], 'running', receipt)
                self.assertAlmostEqual(receipt['planned_seconds'], (duration+300)/1000.)
                request(socket_name, {'cancel_execution':job_id})
                wait_until(lambda: status()['executions'][job_id]['state'] == 'cancelled')
            request(socket_name, {'释放':True})
            wait_until(lambda: status()['ownership'] == 'released')
        finally:
            process.kill()
            process.wait(timeout=2)


if __name__ == '__main__':
    unittest.main()
