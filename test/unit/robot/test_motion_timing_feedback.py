"""Replay the 20.92s real reply's rejected timing, without hardware or API."""
import json
import unittest
from types import SimpleNamespace
from GuideBot.gesture.catalog import Catalog, make_input
from test.archive.anchor_planner.prompts import messages
from GuideBot.gesture.scheduler import Scheduler
from runtime.ipc.transport import ROSGestureService
from runtime.app.workers.motion_executor import MotionExecutor


class TimingFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()

    def test_real_failed_window_preserves_specific_reason_across_host_boundary(self):
        host = ROSGestureService.__new__(ROSGestureService)
        host.session_id, host.generation, host.mode = 'test', 1, 'simulation'
        host.running = True
        host.failed = SimpleNamespace(is_set=lambda:False)
        host.executor = MotionExecutor(self.catalog, clock=lambda:1993.828887712)
        result = host._host(dict(session_id='test', generation=1, op='execute', event=dict(
            action='please_wait', job_id='long:0', start_monotonic=1993.123479232,
            arrival_monotonic=1995.123479232, end_monotonic=1995.123479232)))
        self.assertFalse(result['accepted'])
        self.assertEqual(result['reason'], 'insufficient_remaining_time')
        self.assertAlmostEqual(result['remaining_s'], 1.29459152)
        self.assertEqual(result['minimum_required_s'], 1.4)

    def test_fixed_prompt_exposes_real_budget_and_failure_status(self):
        rows = []
        scheduler = Scheduler(self.catalog, lambda kind, **event:rows.append(event),
                              clock=lambda:100., immediate=True)
        scheduler.text('r', '请稍等。')
        scheduler.playback('r', 100.)
        plan = self.catalog.validate(dict(action='please_wait', start_unit=0, arrival_unit=1,
                                          start_s=0., end_s=3.), [0, 1], [])
        scheduler.add('r', plan, scheduler.replies['r'].units)
        scheduler.tick()
        scheduler.execution_result('r:0', False, 'insufficient_remaining_time')
        history = scheduler.planning_history('r')
        self.assertEqual(history[0]['status'], 'skipped')
        self.assertEqual(history[0]['reason'], 'insufficient_remaining_time')
        payload = dict(make_input('r', '请稍等。', existing=history), timing_contract='fixed_deadline')
        prompt = messages(self.catalog, payload)
        self.assertIn('minimum_remaining_s', prompt[0]['content'])
        self.assertIn('insufficient_remaining_time', prompt[-1]['content'])
        self.assertEqual(self.catalog.execution_timing('please_wait')['minimum_remaining_s'], .5)
        self.assertEqual(self.catalog.execution_timing('please_wait')['minimum_execution_s'], 1.4)

    def test_all_actions_admit_half_second_windows_without_retiming_recorded_motion(self):
        for action in self.catalog.actions:
            timing = self.catalog.execution_timing(action)
            self.assertEqual(timing['minimum_remaining_s'], .5)
            self.assertGreaterEqual(timing['minimum_execution_s'],
                                    timing['recorded_core_s']+timing['minimum_transition_s'])
