import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from GuideBot.gesture.catalog import Catalog, DIRECTORY, make_input, messages, units_for
from GuideBot.gesture.planner import ActionStream, Planner
from GuideBot.gesture.scheduler import Scheduler
from GuideBot.gesture.service import GestureService


class GestureTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        self.text = '请注意这里的沙盘'
        self.units = units_for(self.text)
        self.targets = [{'id': 'sand_table'}]
        self.row = dict(action='point', target_id='sand_table', start_unit=0, arrival_unit=3)

    def plan(self, **changes):
        return self.catalog.validate({**self.row, **changes}, range(len(self.units)), self.targets)

    def test_registry_drives_new_actions_without_prompt_code_changes(self):
        self.assertEqual(len(self.catalog.actions), 8)
        examples = json.loads((DIRECTORY/'few_shots.json').read_text())
        shown = {a['action'] for e in examples for a in e['actions']}
        self.assertEqual(shown, {'wave', 'point'})
        with tempfile.TemporaryDirectory() as tmp:
            document = json.loads((DIRECTORY/'actions.json').read_text())
            document['actions'].append(dict(id='custom_pose', name='测试姿态', kind='pose',
                                            description='新增动作', parameters={}, required=[]))
            document['actions'][0]['enabled'] = False
            path = Path(tmp)/'actions.json'
            path.write_text(json.dumps(document))
            catalog = Catalog(path)
            prompt = messages(catalog, make_input('r', self.text))
            self.assertIn('custom_pose', prompt[0]['content'])
            self.assertNotIn('"action": "wave"', ''.join(m['content'] for m in prompt))
            plan = catalog.validate(dict(action='custom_pose', start_unit=0, arrival_unit=1), range(8), [])
            self.assertEqual(plan.action, 'custom_pose')

    def test_registry_rejects_duplicate_ids_and_pose_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'bad.json'
            document = json.loads((DIRECTORY/'actions.json').read_text())
            document['actions'].append(document['actions'][0])
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                Catalog(path)
            document['actions'].pop()
            document['actions'][1]['parameters']['duration_s'] = {'type':'number', 'minimum':1, 'maximum':2}
            path.write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                Catalog(path)

    def test_all_examples_follow_the_registry(self):
        messages(self.catalog, make_input('r', self.text, self.targets))
        for bad in [dict(action='nod'), dict(target_id='invented'), dict(start_unit=True),
                    dict(arrival_unit=99), dict(start_unit=4), dict(duration_s=1), dict(direction='left')]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.plan(**bad)
        for value in [True, float('nan'), float('inf'), -1, 10]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.catalog.validate(dict(action='wave', start_unit=0, arrival_unit=1, duration_s=value), range(8), [])

    def test_stream_decoder_handles_arbitrary_chunks_and_quoted_braces(self):
        value = {'actions': [self.row, dict(action='test', note='逗号, 括号{}与引号"') ]}
        data = json.dumps(value, ensure_ascii=False)
        stream = ActionStream()
        rows = []
        for char in data:
            rows.extend(stream.feed(char))
        stream.finish()
        self.assertEqual(rows, value['actions'])

    def test_stream_yields_action_before_final_envelope_and_rejects_bad_tail(self):
        stream = ActionStream()
        self.assertEqual(stream.feed('{"actions":['+json.dumps(self.row)), [self.row])
        stream.feed('],"extra":1}')
        with self.assertRaises(ValueError):
            stream.finish()
        for data in ['{"actions":[{"action":"wave","action":"point"}]}',
                     '{"actions":[{"value":NaN}]}']:
            with self.subTest(data=data), self.assertRaises(ValueError):
                ActionStream().feed(data)

    def scheduler(self):
        self.now = 100.
        self.events = []
        scheduler = Scheduler(self.catalog, lambda kind, **d: self.events.append(dict(kind=kind, **d)),
                              clock=lambda: self.now, dispatch_lead=.03)
        scheduler.text('r', self.text)
        scheduler.add('r', self.plan(), self.units)
        scheduler.playback('r', 100.)
        return scheduler

    def alignment(self, scheduler, version=1, start=1., arrival=2., indices=None):
        rows = [dict(index=i, text=u['text'], text_offset=u['text_offset'], start=start if i == 0 else arrival)
                for i, u in enumerate(self.units) if i in (indices if indices is not None else [0,3])]
        scheduler.alignment('r', dict(version=version, anchors=rows))

    def test_waits_for_both_anchors_and_clock_then_freezes(self):
        scheduler = self.scheduler()
        self.alignment(scheduler, indices=[0])
        self.now = 101.
        scheduler.tick()
        self.assertFalse(any(e['kind']=='gesture.command' for e in self.events))
        self.alignment(scheduler, version=2)
        scheduler.tick()
        command = next(e for e in self.events if e['kind']=='gesture.command')
        self.assertEqual(command['arrival_monotonic'], 102.)
        self.alignment(scheduler, version=3, arrival=3.)
        scheduler.tick()
        self.assertEqual(sum(e['kind']=='gesture.command' for e in self.events), 1)
        self.assertEqual(scheduler.replies['r'].jobs[0].timing, (1.,2.))

    def test_future_anchor_revision_and_retraction_change_pending_job(self):
        scheduler = self.scheduler()
        self.alignment(scheduler)
        scheduler.tick()
        self.alignment(scheduler, version=2, indices=[0])
        self.now = 101.
        scheduler.tick()
        self.assertEqual(scheduler.replies['r'].jobs[0].status, 'waiting')
        self.alignment(scheduler, version=3, start=1.5, arrival=2.5)
        self.now = 101.49
        scheduler.tick()
        command = next(e for e in self.events if e['kind']=='gesture.command')
        self.assertFalse(command['compressed'])
        self.assertEqual(command['arrival_monotonic'], 102.5)

    def test_alignment_arriving_before_text_is_retained_until_text_matches(self):
        scheduler = Scheduler(self.catalog, lambda *a, **k: None)
        self.alignment(scheduler)
        self.assertEqual(scheduler.replies['r'].anchors, {})
        scheduler.text('r', self.text)
        self.assertEqual(set(scheduler.replies['r'].anchors), {0,3})

    def test_invalid_snapshot_cannot_poison_version_or_cancel_valid_anchors(self):
        scheduler = self.scheduler()
        self.alignment(scheduler)
        self.alignment(scheduler, version=2, start=3, arrival=1)
        self.assertEqual(scheduler.replies['r'].version, 1)
        self.alignment(scheduler, version=2, arrival=3)
        self.assertEqual(scheduler.replies['r'].anchors[3]['start'], 3)

    def test_late_start_compresses_but_past_arrival_skips(self):
        scheduler = self.scheduler()
        self.alignment(scheduler)
        self.now = 101.5
        scheduler.tick()
        self.assertTrue(next(e for e in self.events if e['kind']=='gesture.command')['compressed'])
        scheduler = self.scheduler()
        self.alignment(scheduler)
        self.now = 102.1
        scheduler.tick()
        self.assertEqual(self.events[-1]['reason'], 'arrival_passed')

    def test_text_replacement_and_cancel_invalidate_pending_and_late_results(self):
        scheduler = self.scheduler()
        scheduler.text('r', '不要指向那个物体')
        self.assertEqual(scheduler.replies['r'].jobs[0].status, 'cancelled')
        scheduler.cancel('r')
        scheduler.add('r', self.plan(), self.units)
        scheduler.text('r', self.text)
        self.assertNotIn('r', scheduler.replies)

    def test_duplicate_and_failed_request_do_not_leave_pending_jobs(self):
        scheduler = self.scheduler()
        scheduler.add('r', self.plan(start_unit=1), self.units)
        self.assertEqual(len(scheduler.replies['r'].jobs), 1)
        scheduler.discard_request('r', 0)
        self.assertEqual(scheduler.replies['r'].jobs[0].status, 'cancelled')

    def test_motion_conflict_is_skipped_and_pose_can_be_superseded(self):
        scheduler = self.scheduler()
        wave = self.catalog.validate(dict(action='wave', start_unit=0, arrival_unit=1, duration_s=2), range(8), [])
        scheduler.replies['r'].jobs.clear()
        scheduler.add('r', wave, self.units)
        scheduler.add('r', self.plan(), self.units)
        rows = [dict(index=i, text=u['text'], text_offset=u['text_offset'], start=1.+i*.2)
                for i,u in enumerate(self.units)]
        scheduler.alignment('r', dict(version=1, anchors=rows))
        self.now = 100.98
        scheduler.tick()
        self.assertEqual(sum(e['kind']=='gesture.command' for e in self.events), 1)
        self.assertIn('upper_body_busy', [e.get('reason') for e in self.events])

    def test_pose_transition_holds_resources_until_arrival(self):
        scheduler = self.scheduler()
        self.alignment(scheduler)
        self.now = 100.98
        scheduler.tick()
        other = self.catalog.validate(dict(action='hold_object',start_unit=1,arrival_unit=2), range(8), [])
        scheduler.add('r', other, self.units)
        scheduler.alignment('r', dict(version=2, anchors=[
            dict(index=i,text=u['text'],text_offset=u['text_offset'],start=t)
            for i,u,t in [(0,self.units[0],1.),(1,self.units[1],1.2),
                          (2,self.units[2],1.8),(3,self.units[3],2.)]]))
        self.now = 101.18
        scheduler.tick()
        self.assertEqual(self.events[-1]['reason'],'upper_body_busy')

    def test_holding_pose_is_replaced_after_it_has_arrived(self):
        scheduler = self.scheduler()
        self.alignment(scheduler)
        self.now = 100.98
        scheduler.tick()
        other = self.catalog.validate(dict(action='hold_object',start_unit=4,arrival_unit=5), range(8), [])
        scheduler.add('r', other, self.units)
        rows = [dict(index=i,text=u['text'],text_offset=u['text_offset'],start=t)
                for i,u,t in [(0,self.units[0],1.),(3,self.units[3],2.),
                              (4,self.units[4],3.),(5,self.units[5],4.)]]
        scheduler.alignment('r',dict(version=2,anchors=rows))
        self.now = 102.98
        scheduler.tick()
        self.assertEqual(sum(e['kind']=='gesture.command' for e in self.events),2)
        self.assertTrue(any(e['kind']=='gesture.superseded' for e in self.events))

    def test_planner_sse_validates_actions_and_never_logs_error_body(self):
        response = Mock(status_code=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        data = json.dumps({'actions':[self.row, dict(action='nod', start_unit=0, arrival_unit=1)]})
        packets = [json.dumps({'choices':[{'delta':{'content':fragment},'finish_reason':None}]})
                   for fragment in [data[:30], data[30:]]]
        packets.append(json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}]}))
        response.iter_lines.return_value = ['data: '+p for p in packets]+['data: [DONE]']
        http = Mock()
        http.post.return_value = response
        planner = Planner(self.catalog, api_key='not-a-real-key', session=http)
        plans = []
        stats = planner.plan(make_input('r',self.text,self.targets), plans.append)
        self.assertEqual([p.action for p in plans], ['point'])
        self.assertEqual(stats['invalid_actions'], 1)
        response.status_code = 401
        response.text = 'private-server-response'
        with self.assertRaisesRegex(RuntimeError, '^DeepSeek HTTP 401$'):
            planner.plan(make_input('r',self.text), plans.append)

    @staticmethod
    def wait_for(predicate, timeout=2):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.01)
        raise AssertionError('Timed out waiting for gesture event')

    def test_service_keeps_ticking_during_network_wait_and_cancels_inflight(self):
        entered, release = threading.Event(), threading.Event()
        plan = self.plan()
        class BlockingPlanner:
            def plan(self, payload, callback, cancelled):
                entered.set()
                release.wait(2)
                callback(plan)  # Deliberately simulate an uncancellable late result.
                return {}
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            service = GestureService(tmp, lambda kind, **d: events.append(dict(kind=kind, **d)),
                                     planner=BlockingPlanner(), catalog=self.catalog, targets=self.targets)
            try:
                service.start()
                service.submit('text','r',text=self.text)
                service.submit('done','r')
                self.assertTrue(entered.wait(1))
                service.submit('playback','r',origin=time.monotonic())
                rows = [dict(index=i, text=u['text'], text_offset=u['text_offset'], start=.1 if i==0 else .8)
                        for i,u in enumerate(self.units) if i in (0,3)]
                service.submit('alignment','r',version=1,anchors=rows)
                service.submit('action','r',plan=plan,text=self.text,units=self.units,request_id=99)
                self.wait_for(lambda: any(e['kind']=='gesture.command' for e in events))
                self.assertFalse(release.is_set())
                service.submit('cancel','r')
                self.wait_for(lambda: any(e['kind']=='gesture.reset' for e in events))
                release.set()
                time.sleep(.05)
                self.assertEqual(sum(e['kind']=='gesture.planned' for e in events), 1)
            finally:
                release.set()
                service.close()


if __name__ == '__main__':
    unittest.main()
