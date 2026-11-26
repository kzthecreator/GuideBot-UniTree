"""Verify speech alignment, continuity and the exact native command contract."""
import copy
import unittest

from GuideBot.gesture.catalog import Catalog, messages, make_input
from GuideBot.gesture.scheduler import Scheduler
from GuideBot.gesture.timing import compile_intent, phases
from GuideBot.runtime.workers.motion_executor import MotionExecutor


class StreamKeyframeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        self.asset = self.catalog.assets['R_Upright_Split']

    def test_core_extends_to_keywords_and_ignores_geometry(self):
        keys = [dict(frame=0,unit=0),dict(frame=self.asset['frames']-1,unit=1)]
        anchors = {0:dict(start=3.),1:dict(start=4.2)}
        result = compile_intent(self.asset,keys,anchors)
        self.assertAlmostEqual(result['start_s'],2.)
        self.assertAlmostEqual(result['core_s'],1.2)
        changed = copy.deepcopy(self.asset)
        changed['metadata'].pop('safety',None)
        changed['points'] = [(t,[999]*14) for t,_ in changed['points']]
        self.assertEqual(result,compile_intent(changed,keys,anchors))
        anchors[1]['start'] = 3.01
        with self.assertRaisesRegex(ValueError,'too_close'):
            compile_intent(self.asset,keys,anchors)

    def test_native_frame_weight_ratios_define_internal_anchors(self):
        asset = dict(metadata=dict(timing_profile=dict(minimum_total_ms=1000,
            phase_weights=dict(transition=1,core=1,hold=0),frame_weights=[1,3])),
            frames=3,points=[(0,[]),(100,[]),(200,[])])
        result = compile_intent(asset,[dict(frame=1,unit=0),dict(frame=2,unit=1)],
                                {0:dict(start=3.),1:dict(start=4.5)})
        self.assertAlmostEqual(result['core_s'],2.)
        self.assertAlmostEqual(result['arrival_s'],2.5)

    def test_scheduler_revises_pending_and_never_preempts(self):
        now = [100.]
        events = []
        scheduler = Scheduler(self.catalog,lambda kind,**kw: events.append(dict(kind=kind,**kw)),
                              clock=lambda:now[0])
        scheduler.text('r','视觉语音')
        units = scheduler.replies['r'].units
        def add(name,unit):
            frame = self.catalog.assets[name]['frames']-1
            plan = self.catalog.validate(dict(action=name,keyframes=[dict(frame=frame,unit=unit)]),range(4),[])
            scheduler.add('r',plan,units)
        add('R_Upright_Split',1)
        add('L_Short_Nudge',2)
        scheduler.playback('r',100.)
        def align(version,times):
            scheduler.alignment('r',dict(version=version,anchors=[dict(index=i,start=t,
                text=units[i]['text'],text_offset=units[i]['text_offset']) for i,t in enumerate(times)]))
        align(0,[2.,3.,3.1,5.])
        scheduler.tick()
        first = scheduler.replies['r'].jobs[0]
        old = first.timing['start_s']
        align(1,[2.,4.,4.1,5.])
        scheduler.tick()
        self.assertGreater(first.timing['start_s'],old)
        now[0] = 100.+first.timing['start_s']
        scheduler.tick()
        self.assertEqual(first.status,'committed')
        command = next(e for e in events if e['kind']=='gesture.command')
        payload = MotionExecutor(self.catalog,clock=lambda:now[0]).sequence(command)
        self.assertEqual(payload['序列']['steps'][0]['transition_ms'],1000)
        self.assertTrue(payload['序列']['preserve_transition'])
        self.assertFalse(any(e['kind']=='gesture.reset' for e in events))
        self.assertEqual(scheduler.replies['r'].jobs[1].status,'skipped')

    def test_prompt_and_validation_require_semantic_intents(self):
        payload = dict(make_input('r','你好'),timing_contract='semantic_keyframes')
        system = messages(self.catalog,payload)[0]['content']
        self.assertIn('固定1秒',system)
        self.assertIn('不要填写 start_s/end_s',system)
        with self.assertRaises(ValueError):
            self.catalog.validate(dict(action='R_Upright_Split',keyframes=[dict(frame=999,unit=0)]),[0],[])

    def test_executor_refuses_late_start_without_shortening_core(self):
        entry,core,hold = phases(self.asset)
        event = dict(action='R_Upright_Split',job_id='j',timing_mode='semantic_keyframes',
            start_monotonic=100.,arrival_monotonic=101.,end_monotonic=101.+core+hold+.1,
            core_s=core,hold_s=hold)
        with self.assertRaises(ValueError):
            MotionExecutor(self.catalog,clock=lambda:100.2).sequence(event)

    def test_fragmented_deepseek_sse_uses_production_intent_validator(self):
        import json
        from GuideBot.gesture.planner import Planner
        text = json.dumps(dict(actions=[dict(action='R_Upright_Split',
            keyframes=[dict(frame=0,unit=0),dict(frame=1,unit=1)],hold_s=.3)]))
        class Response:
            status_code=200
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def iter_lines(self,**kwargs):
                for offset in range(0,len(text),3):
                    yield 'data: '+json.dumps(dict(choices=[dict(delta=dict(content=text[offset:offset+3]))]))
                yield 'data: '+json.dumps(dict(choices=[dict(delta={},finish_reason='stop')]))
                yield 'data: [DONE]'
        class Session:
            def post(self,*args,**kwargs): return Response()
        payload = dict(make_input('r','视音'),timing_contract='semantic_keyframes')
        received=[]
        stats=Planner(self.catalog,api_key='fixture',session=Session()).plan(payload,received.append)
        self.assertEqual(stats['valid_actions'],1)
        self.assertEqual(received[0].parameters['keyframes'][1],dict(frame=1,unit=1))

    def test_startup_buffer_does_not_change_pcm_or_prevent_cancellation(self):
        import threading
        from unittest.mock import patch
        from GuideBot.conversation.playback import StreamingSpeaker
        speaker=StreamingSpeaker(threading.Event(),lambda error:None,gain=1,startup_buffer_s=3.)
        try:
            with patch('GuideBot.conversation.playback.time.monotonic',return_value=100.):
                pcm=speaker.feed('r',b'\x00\x00'*2400)
            entry=speaker.responses['r']
            self.assertEqual(entry.buffer_until,103.)
            self.assertEqual(len(pcm),entry.received_bytes)
            speaker.interrupt()
            self.assertTrue(entry.data.closed)
            self.assertEqual(speaker.buffered_bytes,0)
        finally:
            speaker.close()
