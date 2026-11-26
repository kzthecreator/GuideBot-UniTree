import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from GuideBot.gesture.catalog import Catalog

ROOT=Path(__file__).resolve().parents[1]
DIRECTORY=ROOT/'examples/gesture_from_audio'
spec=importlib.util.spec_from_file_location('complete_plan',DIRECTORY/'complete_plan.py')
complete=importlib.util.module_from_spec(spec);spec.loader.exec_module(complete)
spec=importlib.util.spec_from_file_location('rehearse_complete',DIRECTORY/'rehearse.py')
rehearse=importlib.util.module_from_spec(spec);spec.loader.exec_module(rehearse)


class CompletePlanTests(unittest.TestCase):
    def setUp(self):
        self.catalog=Catalog()
        self.doc=dict(text='测'*40,duration_seconds=21.,timestamps=[
            dict(text='测',text_offset=i,start=i*.5,end=i*.5+.3) for i in range(40)])
        self.intents=[dict(action='B_Open_Hold',anchor_unit=8),dict(action='R_Center_Present',anchor_unit=20),
                      dict(action='L_Side_Present',anchor_unit=32)]
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def test_whole_sequence_native_duration_matches_all_transitions_and_waits(self):
        sequence,actions,conflicts=complete.compile_timeline(self.catalog,self.doc,self.intents)
        self.assertEqual(conflicts,[]);self.assertEqual(len(actions),3)
        self.assertTrue(sequence['preserve_transition'])
        self.assertEqual(sequence['steps'][0]['name'],'B_Neutral_Rest')
        self.assertGreater(actions[0]['transition_s'],.5)
        result=complete.native_validate(sequence,self.root)
        duration=float(result.split(' steps, ')[1].split(' s ')[0])
        self.assertAlmostEqual(duration,actions[-1]['end_s'],places=3)
        for a,b in zip(actions,actions[1:]):self.assertLessEqual(a['end_s'],b['start_s'])

    def test_conflicts_are_resolved_before_playback_not_turned_into_executable_plan(self):
        intents=[dict(action='L_Side_Present',anchor_unit=0),dict(action='R_Side_Present',anchor_unit=1)]
        sequence,actions,conflicts=complete.compile_timeline(self.catalog,self.doc,intents)
        self.assertIsNone(sequence);self.assertFalse(actions);self.assertEqual(len(conflicts),2)
        with self.assertRaises(ValueError):complete.compile_timeline(self.catalog,self.doc,self.intents*2)

    def test_unlimited_allows_more_than_three_and_repeated_actions(self):
        intents=[dict(action='B_Open_Hold',anchor_unit=i) for i in (8,14,20,26,32)]
        sequence,actions,conflicts=complete.compile_timeline(self.catalog,self.doc,intents,
            action_limit=None,allow_repeats=True)
        self.assertEqual(len(actions),5);self.assertEqual(conflicts,[])
        native=complete.native_validate(sequence,self.root)
        self.assertIn('6 steps',native)
        import hashlib
        audio=self.root/'audio.mp3';audio.write_bytes(b'fixture')
        snapshot={name:{key:self.catalog.assets[name]['metadata'][key] for key in ('sha256','version')}
                  for name in ('B_Neutral_Rest','B_Open_Hold')}
        summary=dict(mode='complete',action_limit=None,allow_repeated_actions=True,sequence=sequence,
            trajectory_seconds=actions[-1]['end_s'],timestamps=self.doc['timestamps'],
            validation=dict(duration_seconds=self.doc['duration_seconds'],audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest()),
            actions=[dict(a,dispatch_s=a['start_s'],start_unit=a['anchor_unit'],arrival_unit=a['anchor_unit']) for a in actions])
        (self.root/'motion-snapshot.json').write_text(json.dumps(snapshot))
        (self.root/'summary.json').write_text(json.dumps(summary))
        checked,_=rehearse.load_plan(self.root,self.catalog)
        self.assertEqual(len(checked['actions']),5)
        summary['action_limit']=3;(self.root/'summary.json').write_text(json.dumps(summary))
        with self.assertRaises(ValueError):rehearse.load_plan(self.root,self.catalog)

    def test_unlimited_prompt_removes_count_and_reuse_restrictions(self):
        prompt=complete.intent_messages(self.catalog,self.doc,[],unlimited=True)[0]['content']
        self.assertIn('不设置动作数量上限',prompt)
        self.assertIn('重复使用同一动作',prompt)
        self.assertNotIn('最多3个',prompt)
        limited=complete.intent_messages(self.catalog,self.doc,[],unlimited=False)[0]['content']
        self.assertIn('最多3个',limited)

    def test_model_receives_fixed_transition_and_core_budgets_before_selecting(self):
        prompt=complete.intent_messages(self.catalog,self.doc,[],unlimited=True,transition_s=1.)
        self.assertIn('入口切换固定为1秒',prompt[0]['content'])
        timing=json.loads(prompt[1]['content'])['execution_timing']
        self.assertEqual({r['id'] for r in timing},set(self.catalog.actions))
        self.assertTrue(all(r['transition_s']==1. for r in timing))
        self.assertTrue(any(r['core_s']>0 for r in timing))
        self.assertTrue(all(r['minimum_hold_s']>=.3 for r in timing))

    def test_transition_is_fixed_one_second_regardless_of_joint_distance(self):
        asset=self.catalog.assets['L_Side_Present']
        for pose in ([0.]*14,[2.]*14):
            entry,_,_=complete.phase_times(asset,pose)
            self.assertEqual(entry,1.)
        sequence,actions,_=complete.compile_timeline(self.catalog,self.doc,self.intents)
        self.assertTrue(all(a['transition_s']==1. for a in actions))
        self.assertTrue(all(step['transition_ms']==1000 for step in sequence['steps'][1:]))
        with self.assertRaises(ValueError):complete.phase_times(asset,[0.]*14,transition_s=0)

    def test_phase_times_do_not_read_joint_geometry_or_motion_limits(self):
        import copy
        asset=copy.deepcopy(self.catalog.assets['R_Draw_In_Hold'])
        expected=complete.phase_times(asset,[0.]*14)
        asset['metadata'].pop('safety',None)
        asset['points']=[(duration,[100.]*14) for duration,_ in asset['points']]
        self.assertEqual(complete.phase_times(asset,[-100.]*14),expected)
        self.assertEqual(expected[0],1.)
        self.assertLess(expected[1],.5)

    def test_core_duration_comes_from_approved_timing(self):
        asset=self.catalog.assets['L_Greeting_Wave'];entry,core,hold=complete.phase_times(asset,self.catalog.assets['B_Neutral_Rest']['points'][0][1])
        self.assertGreaterEqual(core,asset['metadata']['nominal_duration_ms']/1000)
        self.assertGreater(entry,0);self.assertGreater(hold,0)

    def test_rehearsal_prepares_neutral_then_submits_one_timeline_and_cleans_up(self):
        sequence,actions,_=complete.compile_timeline(self.catalog,self.doc,self.intents)
        summary=dict(sequence=sequence,validation=dict(duration_seconds=21.))
        now=[100.2];commands=[];runtime=SimpleNamespace(process=SimpleNamespace(poll=lambda:None),job=None,stopped=False)
        runtime.start=lambda:None;runtime.stop=lambda:setattr(runtime,'stopped',True)
        def request(command):commands.append(command);runtime.job=command['job_id'];return {'ok':True}
        runtime.request=request
        runtime._status=lambda:dict(ownership='owned',state='idle',commanded_arm=self.catalog.assets['B_Neutral_Rest']['points'][0][1],execution=dict(job_id=runtime.job,state='completed'))
        speaker=SimpleNamespace(closed=False,returncode=0)
        speaker.start=lambda *a:100.
        speaker.poll=lambda:0 if now[0]>=103 else None
        speaker.close=lambda:setattr(speaker,'closed',True)
        def sleep(dt):now[0]+=dt
        with contextlib.redirect_stdout(io.StringIO()):
            rehearse.complete_rehearsal(self.catalog,summary,self.root/'unused.mp3',self.root/'logs',
                runtime_factory=lambda:runtime,speaker_factory=lambda:speaker,clock=lambda:now[0],sleep=sleep)
        self.assertEqual(len(commands),2)
        self.assertEqual(commands[0]['job_id'],'prepare-neutral')
        self.assertEqual(commands[1]['job_id'],'complete-timeline')
        self.assertEqual(commands[1]['序列']['steps'][1:],sequence['steps'][1:])
        self.assertLess(commands[1]['序列']['steps'][0]['hold_ms'],sequence['steps'][0]['hold_ms'])
        self.assertTrue(runtime.stopped);self.assertTrue(speaker.closed)


if __name__=='__main__':unittest.main()
