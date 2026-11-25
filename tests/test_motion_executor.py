import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from GuideBot.gesture.catalog import Catalog, MOTION_ROOT, DIRECTORY, make_input, messages
from GuideBot.runtime.workers.motion_executor import MotionExecutor
from GuideBot.gesture.scheduler import Scheduler


class MotionExecutorTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()

    def event(self, action, now=100, arrival=103, **parameters):
        return dict(action=action, job_id='job', start_monotonic=100,
                    arrival_monotonic=arrival, **parameters)

    def test_inventory_and_physical_mapping(self):
        self.assertEqual(len(self.catalog.assets), 10)
        self.assertEqual(len(self.catalog.actions), 9)
        self.assertIn('present_center', self.catalog.actions)
        self.assertNotIn('neutral', self.catalog.actions)
        self.assertEqual(self.catalog.assets['greet_open']['frames'], 1)
        self.assertEqual(self.catalog.actions['greet_open']['kind'], 'pose')
        self.assertEqual(self.catalog.actions['greet_open']['asset_type'], 'motion')
        self.assertEqual(self.catalog.assets['greet_open']['entry']['type'], 'motion')
        for name in self.catalog.actions:
            asset = self.catalog.assets[name]
            self.assertEqual(asset['entry']['name'], self.catalog.actions[name]['motion_name'])
            self.assertEqual(asset['metadata']['sha256'],
                             self.catalog.library.checksum(self.catalog.library.asset_path(
                                 asset['entry'], MOTION_ROOT / 'motions', MOTION_ROOT / 'poses')))

    def test_few_shots_and_prompt(self):
        examples = json.loads((MOTION_ROOT / 'conversation-few-shots.json').read_text())
        counts = {name: 0 for name in self.catalog.actions}
        for example in examples:
            for row in example['actions']:
                counts[row['action']] += 1
        self.assertTrue(all(count >= 2 for count in counts.values()))
        sequence = next(example for example in examples if len(example['actions']) == 2)
        self.assertEqual([row['action'] for row in sequence['actions']],
                         ['present_right', 'greet_open'])
        self.assertLess(sequence['actions'][0]['arrival_unit'],
                        sequence['actions'][1]['start_unit'])
        cases = json.loads((Path(__file__).resolve().parents[1] / 'tools/gesture/evaluation.json').read_text())
        definitions = {item['id']: item for item in self.catalog.document['actions']}
        for action in counts:
            self.assertEqual({case['group'] for case in cases if case['expected'] == [action]},
                             {'seen', 'unseen'})
        evaluated_functions = {case.get('interaction') for case in cases}
        for item in definitions.values():
            for function in item['interaction_functions']:
                self.assertIn(function['function'], evaluated_functions)
        self.assertTrue(any(case['group'] == 'negative' for case in cases))
        system = messages(self.catalog, make_input('r', '欢迎大家'))[0]['content']
        self.assertIn('semantic_intents', system)
        self.assertIn('"id": "present_center"', system)
        self.assertNotIn('"id": "neutral"', system)
        definitions = {item['id']: item for item in self.catalog.document['actions']}
        self.assertFalse(definitions['neutral']['llm_selectable'])
        self.assertTrue(definitions['neutral']['enabled'])
        for item in definitions.values():
            for function in item['interaction_functions']:
                self.assertTrue(function['function'])
                self.assertTrue(function['description'])
                self.assertTrue(function['example_phrases'])
                self.assertTrue(function['context_requirements'])
                self.assertTrue(function['avoid_when'])
        greet_functions = {item['function'] for item in definitions['greet_open']['interaction_functions']}
        self.assertTrue({'welcome_reception', 'invite_question', 'invite_participation',
                         'invite_feedback'} <= greet_functions)
        for name in ('wave', 'point', 'hold_object', 'present_sweep'):
            self.assertNotIn(name, self.catalog.actions)

    def test_invalid_metadata_is_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(MOTION_ROOT, root / 'library')
            library = root / 'library'
            meta_path = library / 'metadata/greet_open.json'
            meta = json.loads(meta_path.read_text())
            meta['sha256'] = '0' * 64
            meta_path.write_text(json.dumps(meta))
            catalog = Catalog(motion_root=library)
            self.assertNotIn('greet_open', catalog.actions)
            self.assertIn('greet_wave', catalog.actions)

    def test_sequence_and_expiry(self):
        executor = MotionExecutor(self.catalog, mode='simulation', clock=lambda: 100)
        pose = executor.handle('gesture.command', self.event('greet_open'))
        self.assertEqual(pose['sequence']['序列']['steps'][0]['type'], 'motion')
        center = executor.handle('gesture.command', self.event('present_center'))
        self.assertEqual(center['sequence']['序列']['steps'][0]['type'], 'motion')
        self.assertNotIn('duration_ms', pose['sequence']['序列']['steps'][0])
        motion = executor.sequence(self.event('greet_wave', duration_s=2))
        self.assertEqual(motion['序列']['steps'][0]['duration_ms'], 2000)
        with self.assertRaisesRegex(ValueError, 'deadline'):
            MotionExecutor(self.catalog, mode='simulation', clock=lambda: 104).sequence(
                self.event('greet_wave', duration_s=2))
        with self.assertRaisesRegex(ValueError, 'transition'):
            executor.sequence(self.event('greet_wave', arrival=100.1, duration_s=2))

    def test_robot_gate_and_mock_socket(self):
        sent = []
        def request(payload):
            sent.append(payload)
            return {'ok': True, 'status': {'ownership': 'owned', 'state': 'idle'}}
        executor = MotionExecutor(self.catalog, mode='robot', request=request, clock=lambda: 100)
        with patch('GuideBot.runtime.workers.motion_executor.json.loads', return_value={'verified': False}):
            with self.assertRaisesRegex(ValueError, 'Joint limits'):
                executor.handle('gesture.command', self.event('greet_open'))
        self.assertEqual(sent, [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'library'
            shutil.copytree(MOTION_ROOT, root)
            limits_path = root / 'config/arm_joint_limits.json'
            from drivers.unitree_motion.paths import LIMITS
            limits = json.loads(LIMITS.read_text())
            limits.update(verified=True, verified_by='test', verified_at='test')
            limits_path.write_text(json.dumps(limits))
            catalog = Catalog(motion_root=root, limits_path=limits_path)
            executor = MotionExecutor(catalog, mode='robot', request=request, clock=lambda: 100)
            executor.handle('gesture.command', self.event('greet_open'))
            self.assertEqual(sent[0], {'状态': True})
            self.assertIn('序列', sent[1])
            executor.handle('gesture.reset', {})
            self.assertEqual(sent[2], {'停止': True})

    def test_dispatch_rejection_releases_scheduler_resource(self):
        events = []
        def emit(kind, **details):
            events.append(kind)
            return {'execution_error': 'joint limits unverified'} if kind == 'gesture.command' else None
        scheduler = Scheduler(self.catalog, emit, clock=lambda: 100.99)
        from GuideBot.gesture.catalog import units_for
        text = '欢迎大家'
        units = units_for(text)
        plan = self.catalog.validate(
            {'action': 'greet_open', 'start_unit': 0, 'arrival_unit': 1},
            range(len(units)), [], {'stage': 'welcome'})
        scheduler.text('r', text)
        scheduler.add('r', plan, units)
        scheduler.playback('r', 100)
        scheduler.alignment('r', {'version': 1, 'anchors': [
            {'index': i, 'text': units[i]['text'], 'text_offset': units[i]['text_offset'],
             'start': start} for i, start in ((0, 1), (1, 2))]})
        scheduler.tick()
        self.assertIsNone(scheduler.active)
        self.assertIn('gesture.skipped', events)

    def test_immediate_dispatch_does_not_wait_for_alignment_or_playback(self):
        events = []
        def emit(kind, **details):
            events.append((kind, details))
            return {'mode': 'robot'} if kind == 'gesture.command' else None
        scheduler = Scheduler(self.catalog, emit, clock=lambda: 100, immediate=True)
        from GuideBot.gesture.catalog import units_for
        units = units_for('欢迎大家')
        plan = self.catalog.validate(
            {'action': 'greet_open', 'start_unit': 0, 'arrival_unit': 1},
            range(len(units)), [], {'stage': 'welcome'})
        scheduler.text('r', '欢迎大家')
        scheduler.add('r', plan, units)
        scheduler.tick()
        command = next(details for kind, details in events if kind == 'gesture.command')
        self.assertEqual(command['timing_mode'], 'immediate')
        self.assertEqual(command['start_monotonic'], 100)
        self.assertEqual(command['arrival_monotonic'], 102)
        self.assertFalse(any(kind == 'gesture.skipped' for kind, _ in events))
        scheduler.add('r', plan, units)
        scheduler.tick()
        self.assertEqual(sum(kind == 'gesture.command' for kind, _ in events), 1)

    def test_immediate_dispatch_failure_releases_scheduler_resource(self):
        events = []
        def emit(kind, **details):
            events.append((kind, details))
            return {'execution_error': 'motion service busy'} if kind == 'gesture.command' else None
        scheduler = Scheduler(self.catalog, emit, clock=lambda: 100, immediate=True)
        from GuideBot.gesture.catalog import units_for
        units = units_for('欢迎大家')
        plan = self.catalog.validate(
            {'action': 'greet_open', 'start_unit': 0, 'arrival_unit': 1},
            range(len(units)), [], {'stage': 'welcome'})
        scheduler.text('r', '欢迎大家')
        scheduler.add('r', plan, units)
        scheduler.tick()
        self.assertIsNone(scheduler.active)
        self.assertEqual(next(details['reason'] for kind, details in events
                              if kind == 'gesture.skipped'), 'execution_rejected')

    def test_robot_service_defaults_to_immediate_timing(self):
        from GuideBot.gesture.service import GestureService
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', {'GUIDEBOT_GESTURE_EXECUTION_MODE': 'robot'}, clear=False):
                service = GestureService(directory, catalog=self.catalog)
                self.assertTrue(service.scheduler.immediate)
            with patch.dict('os.environ', {'GUIDEBOT_GESTURE_EXECUTION_MODE': 'robot',
                                           'GUIDEBOT_GESTURE_TIMING_MODE': 'aligned'}, clear=False):
                service = GestureService(directory, catalog=self.catalog)
                self.assertFalse(service.scheduler.immediate)

    def test_scheduler_can_explicitly_request_neutral_without_auto_reset(self):
        events = []
        def emit(kind, **details):
            events.append((kind, details))
            return {'mode': 'simulation'} if kind == 'gesture.command' else None
        scheduler = Scheduler(self.catalog, emit, clock=lambda: 100)
        scheduler.tick()
        self.assertFalse(any(kind == 'gesture.command' for kind, _ in events))
        scheduler.request_base_pose('guest_question_started')
        command = next(details for kind, details in events if kind == 'gesture.command')
        self.assertEqual(command['action'], 'neutral')
        self.assertTrue(command['scheduler_managed'])
        executor = MotionExecutor(self.catalog, mode='simulation', clock=lambda: 100)
        with self.assertRaisesRegex(ValueError, 'Unknown or disabled'):
            executor.sequence({**command, 'scheduler_managed': False,
                               'start_monotonic': 100, 'arrival_monotonic': 100.5})
        seq = executor.sequence({**command, 'start_monotonic': 100, 'arrival_monotonic': 100.5})
        self.assertEqual(seq['序列']['steps'][0]['name'], 'neutral')
        cases = json.loads((Path(__file__).resolve().parents[1] / 'tools/gesture/evaluation.json').read_text())
        listening = next(case for case in cases if case['id'] == 'qa_user_turn_scheduler_base')
        self.assertEqual(listening['scheduler_action'], 'neutral')
        self.assertEqual(listening['expected'], [])

    def test_interaction_context_is_included_in_planner_input(self):
        context = {'stage': 'qa_invitation', 'history': ['本段讲解已结束'], 'facts': []}
        payload = make_input('r', '大家还有什么问题吗？', interaction_context=context)
        self.assertEqual(payload['interaction_context'], context)
        system_and_user = messages(self.catalog, payload)
        self.assertIn('"stage": "qa_invitation"', system_and_user[-1]['content'])

    def test_latest_semantic_descriptions_and_release_contract(self):
        definitions = {item['id']: item for item in self.catalog.document['actions']}
        self.assertIn('左手保持相对固定', definitions['emphasize_once']['description'])
        self.assertIn('上下及前后摆动', definitions['emphasize_once']['description'])
        repeat = definitions['request_repeat']['description']
        self.assertIn('右手位于头部上方或附近', repeat)
        self.assertIn('头部没有主动运动', repeat)
        expected = {
            'please_wait': {'task_completed', 'task_cancelled', 'maximum_hold_time'},
            'request_repeat': {'new_valid_input', 'clarification_completed', 'interaction_cancelled', 'maximum_hold_time'},
            'greet_open': {'visitor_responded', 'interaction_changed', 'maximum_hold_time'},
            'present_center': {'display_target_changed', 'explanation_ended', 'action_switch_needed'},
            'present_left': {'display_target_changed', 'explanation_ended', 'action_switch_needed'},
            'present_right': {'display_target_changed', 'explanation_ended', 'action_switch_needed'},
        }
        for action, conditions in expected.items():
            self.assertTrue(conditions <= set(definitions[action]['release_conditions']))


if __name__ == '__main__':
    unittest.main()
