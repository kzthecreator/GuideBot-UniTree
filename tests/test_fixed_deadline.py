"""Fixed playback deadlines survive planning, preemption and transport delay."""
import json
import unittest
from unittest.mock import Mock
from GuideBot.gesture.catalog import Catalog, make_input
from GuideBot.gesture.planner import Planner
from GuideBot.gesture.scheduler import Scheduler
from GuideBot.runtime.workers.motion_executor import MotionExecutor


class FixedDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        self.now = 100.
        self.events = []
        self.scheduler = Scheduler(self.catalog, self.emit, clock=lambda: self.now, immediate=True)
        self.scheduler.text('r', '欢迎参观')
        self.scheduler.playback('r', 100.)

    def emit(self, kind, **event):
        self.events.append(dict(kind=kind, **event))
        if kind == 'gesture.reset':
            self.now += .6
        return dict(mode='robot', accepted=True)

    def add(self, action='greet_open', start=1., end=3.):
        plan = self.catalog.validate(dict(action=action, start_unit=0, arrival_unit=1,
                                          start_s=start, end_s=end), [0, 1], [])
        self.scheduler.add('r', plan, self.scheduler.replies['r'].units)

    def test_late_plan_keeps_original_deadline(self):
        self.now = 102.
        self.add()
        self.scheduler.tick()
        command = next(e for e in self.events if e['kind'] == 'gesture.command')
        self.assertEqual(command['end_monotonic'], 103.)
        self.assertEqual(command['start_monotonic'], 101.)

    def test_expired_action_is_never_dispatched(self):
        self.now = 103.
        self.add()
        self.scheduler.tick()
        self.assertFalse(any(e['kind'] == 'gesture.command' for e in self.events))
        self.assertEqual(self.events[-1]['reason'], 'end_deadline_passed')

    def test_preemption_does_not_move_new_deadline(self):
        self.now = 101.
        self.add(end=8.)
        self.scheduler.tick()
        self.add('present_left', start=2., end=5.)
        self.now = 102.
        self.scheduler.tick()
        commands = [e for e in self.events if e['kind'] == 'gesture.command']
        self.assertEqual(len(commands), 2)
        self.assertTrue(any(e['kind'] == 'gesture.reset' for e in self.events))
        self.assertEqual(commands[-1]['end_monotonic'], 105.)

    def test_expiry_during_braking_drops_new_action(self):
        self.now = 101.
        self.add(end=8.)
        self.scheduler.tick()
        self.add('present_left', start=2., end=2.5)
        self.now = 102.
        self.scheduler.tick()
        self.assertEqual(len([e for e in self.events if e['kind'] == 'gesture.command']), 1)
        self.assertEqual(self.events[-1]['reason'], 'end_deadline_passed')

    def test_worker_uses_remaining_window_and_recorded_core(self):
        executor = MotionExecutor(self.catalog, clock=lambda: self.now)
        self.now = 102.
        event = dict(action='emphasize_once', job_id='job', start_monotonic=101.,
                     arrival_monotonic=106., end_monotonic=106., duration_s=10.)
        payload = executor.sequence(event)
        self.assertEqual(payload['end_monotonic'], 106.)
        self.assertEqual(payload['序列']['steps'][0]['duration_ms'],
                         self.catalog.assets['emphasize_once']['metadata']['nominal_duration_ms'])
        self.now = 105.9
        with self.assertRaisesRegex(ValueError, 'deadline|remaining|Remaining|Insufficient'):
            executor.sequence(event)

    def test_invalid_or_partial_window_rejected(self):
        for fields in [dict(start_s=1), dict(start_s=3, end_s=1),
                       dict(start_s=0, end_s=float('nan'))]:
            with self.assertRaises(ValueError):
                self.catalog.validate(dict(action='greet_open', start_unit=0, arrival_unit=1,
                                           **fields), [0, 1], [])

    def test_backlog_dispatches_only_newest_due_action(self):
        self.add(start=0., end=8.)
        self.add('present_left', start=1., end=7.)
        self.now = 102.
        self.scheduler.tick()
        commands = [e for e in self.events if e['kind'] == 'gesture.command']
        self.assertEqual([e['action'] for e in commands], ['present_left'])

    def test_old_completion_cannot_release_replacement(self):
        self.now = 101.
        self.add(end=8.)
        self.scheduler.tick()
        self.add('present_left', start=2., end=7.)
        self.now = 102.
        self.scheduler.tick()
        self.scheduler.execution_result('r:0', False)
        self.assertEqual(self.scheduler.active['job'].id, 'r:1')
        self.scheduler.execution_result('r:1', True)
        self.assertIsNone(self.scheduler.active)

    def test_late_older_window_cannot_preempt_newer_action(self):
        self.now = 103.
        self.add('present_left', start=3., end=9.)
        self.scheduler.tick()
        self.add('greet_open', start=1., end=8.)
        self.scheduler.tick()
        self.assertFalse(any(e['kind'] == 'gesture.reset' for e in self.events))
        self.assertEqual(self.events[-1]['reason'], 'older_window_superseded')

    def test_streamed_planner_requires_fixed_window_and_accepts_recorded_core_without_duration(self):
        response = Mock(status_code=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        rows = [dict(action='greet_open', start_unit=0, arrival_unit=1),
                dict(action='emphasize_once', start_unit=0, arrival_unit=1, start_s=1., end_s=5.)]
        packet = dict(choices=[dict(delta=dict(content=json.dumps(dict(actions=rows))), finish_reason='stop')])
        response.iter_lines.return_value = ['data: '+json.dumps(packet), 'data: [DONE]']
        http = Mock()
        http.post.return_value = response
        planner = Planner(self.catalog, api_key='offline-test', session=http)
        payload = dict(make_input('r', '欢迎参观'), timing_contract='fixed_deadline',
                       playback_elapsed_s=2., playback_started=True)
        plans = []
        stats = planner.plan(payload, plans.append)
        self.assertEqual(stats['invalid_actions'], 1)
        self.assertEqual([plan.action for plan in plans], ['emphasize_once'])
        prompt = http.post.call_args.kwargs['json']['messages']
        self.assertEqual(len(prompt), 2)  # No contradictory legacy few-shots.
        self.assertIn('recorded_core_s', prompt[0]['content'])
