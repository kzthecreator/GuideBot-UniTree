import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from drivers.unitree_motion.assets import asset_path,catalog_entries
from drivers.unitree_motion.planning import confirmed_timing
from tools.motion import motion_timing_ui as ui
from tools.motion.register_recording import register
from GuideBot.gesture.catalog import Catalog, messages, make_input
from GuideBot.runtime.workers.motion_executor import MotionExecutor, MotionTimingRejected


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'config').mkdir()
        (self.root/'config/motion_catalog.json').write_text('{"schema_version":1,"actions":[]}')
        (self.root/'actions.json').write_text('{"version":1,"actions":[]}')
        self.source=self.root/'capture.dat'
        self.source.write_text('3\n14\n'+('0.3 '+' '.join(['0']*14)+'\n')*3)
        for name,group in [('Custom','semantic'),('Beat','prosody')]:
            register(self.root,self.source,name,group,description='双臂抬起后落下',label='测试动作')
        self.root_patch=patch.object(ui,'ROOT',self.root)
        self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.app=ui.App()

    def payload(self,name='Custom'):
        detail=self.app.detail(name)
        return dict(name=name,sha256=detail['sha256'],version=detail['version'],total_ms=4000,minimum_total_ms=2000,offline=False)

    def finished_preview(self,payload,offline=False,phase='completed',code=0):
        # Exercise real watcher completion, using a fake process rather than hardware.
        prepared=self.app.simple_payload(payload)
        signature=(payload['name'],payload['sha256'],payload['version'],prepared['timing_profile'],payload['total_ms'])
        class Finished:
            stdout=[json.dumps(dict(event='preview',preview=dict(state=phase,planned_seconds=4)))]
            def wait(self):return code
        self.app.state['running']=True
        self.app.watch(Finished(),signature,offline)

    def test_no_saved_profile_needed_and_duration_is_exact(self):
        p=self.payload()
        before=(self.root/'metadata/Custom.json').read_bytes()
        with patch.object(self.app,'launch') as launch:
            self.app.simple_preview(p)
        cmd=launch.call_args.args[0]
        profile=json.loads(cmd[cmd.index('--timing-profile-json')+1])
        self.assertEqual(profile['minimum_total_ms'],2000)
        self.assertEqual(cmd[cmd.index('--total-ms')+1],'4000')
        self.assertEqual((self.root/'metadata/Custom.json').read_bytes(),before)

    def test_real_success_confirmation_enables_both_groups_and_preserves_trajectory(self):
        for name in ('Custom','Beat'):
            p=self.payload(name)
            entries=catalog_entries(self.root/'config/motion_catalog.json')
            path=asset_path(entries[name],self.root/'motions',self.root/'poses')
            original=path.read_bytes()
            self.finished_preview(p)
            self.assertTrue(self.app.confirm_available(p)['enabled'])
            catalog=Catalog(path=self.root/'actions.json',motion_root=self.root)
            self.assertIn(name,catalog.actions)
            self.assertEqual(catalog.actions[name]['semantic_intents'],[])
            self.assertEqual(catalog.actions[name]['interaction_functions'],[])
            self.assertEqual(path.read_bytes(),original)
            timing=catalog.execution_timing(name)
            self.assertEqual(timing['minimum_total_ms'],2000)
            self.assertEqual(timing['minimum_remaining_s'],2.0)
            self.assertEqual(timing['recorded_core_s'],1.0)
            event=dict(action=name,start_monotonic=100,arrival_monotonic=102,
                       end_monotonic=110,job_id='test')
            executor=MotionExecutor(catalog,clock=lambda:100)
            step=executor.sequence(event)['序列']['steps'][0]
            self.assertEqual(step,dict(type='motion',name=name,total_ms=9950))
            self.assertEqual(executor.sequence(dict(event,end_monotonic=108))['序列']['steps'][0]['total_ms'],7950)
            with self.assertRaises(MotionTimingRejected):
                executor.sequence(dict(event,end_monotonic=101.99))
            payload=make_input('r','这里介绍机器人',complete=True)
            payload['timing_contract']='fixed_deadline'
            prompt=messages(catalog,payload)
            self.assertIn(name,prompt[0]['content'])
            if name=='Beat':self.assertEqual(catalog.actions[name]['gesture_group'],'prosody')

    def test_offline_failure_cancel_and_unplayed_cannot_confirm(self):
        p=self.payload()
        with self.assertRaises(ValueError):self.app.confirm_available(p)
        for offline,phase,code in [(True,'completed',0),(False,'failed',1),(False,'cancelled',0)]:
            self.finished_preview(p,offline,phase,code)
            with self.assertRaises(ValueError):self.app.confirm_available(p)
        self.app.cancelled=True
        self.finished_preview(p)
        with self.assertRaises(ValueError):self.app.confirm_available(p)
        self.assertEqual(Catalog(path=self.root/'actions.json',motion_root=self.root).actions,{})

    def test_changed_duration_or_revision_cannot_reuse_confirmation(self):
        p=self.payload();self.finished_preview(p)
        with self.assertRaises(ValueError):self.app.confirm_available(dict(p,total_ms=5000))
        with self.assertRaises(ValueError):self.app.confirm_available(dict(p,minimum_total_ms=1000))
        meta_path=self.root/'metadata/Custom.json'
        meta=json.loads(meta_path.read_text());meta['version']+=1
        meta_path.write_text(json.dumps(meta))
        with self.assertRaises(ValueError):self.app.confirm_available(p)
        self.assertEqual(json.loads(meta_path.read_text())['status'],'draft')

    def test_confirmation_write_failure_rolls_back_metadata_and_registry(self):
        from tools.motion import register_recording
        p=self.payload();self.finished_preview(p)
        before={name:(self.root/name).read_bytes() for name in ('metadata/Custom.json','actions.json')}
        original=register_recording.replace;calls=[]
        def fail_once(path,data):
            calls.append(path)
            if len(calls)==2:raise OSError('simulated registry failure')
            return original(path,data)
        with patch.object(register_recording,'replace',side_effect=fail_once):
            with self.assertRaises(OSError):self.app.confirm_available(p)
        for name,data in before.items():self.assertEqual((self.root/name).read_bytes(),data)

    def test_native_sequence_stretches_and_clamps_to_minimum_without_hardware(self):
        import subprocess
        from drivers.unitree_motion.assets import JOINT_NAMES
        binary=ui.BUILD/'motion_library_server'
        if not binary.is_file():self.skipTest('native motion server not built')
        p=self.payload();self.finished_preview(p);self.app.confirm_available(p)
        limits=self.root/'limits.json'
        limits.write_text(json.dumps(dict(schema_version=1,verified=True,verified_by='test',
            verified_at='test',joint_names=list(JOINT_NAMES),min_rad=[-6]*14,max_rad=[6]*14)))
        for requested,expected in ((1000,2),(4000,4),(7000,7)):
            result=subprocess.run([str(binary),'--check-sequence','-',
                '--catalog',str(self.root/'config/motion_catalog.json'),
                '--dir',str(self.root/'motions'),'--poses',str(self.root/'poses'),
                '--metadata',str(self.root/'metadata'),'--limits',str(limits)],
                input=json.dumps(dict(sequence_name='confirmed_test',steps=[
                    dict(type='motion',name='Custom',total_ms=requested)])),
                text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(f'{expected} s from first entry pose',result.stdout)

    def test_failure_survives_buffered_banner_and_full_output_is_saved(self):
        class Failed:
            stdout=['试播失败：接管被服务端拒绝\n', 'Play-style linear preview: 2 ms commands\n']
            def wait(self):return 1
        log=self.root/'preview.log'
        self.app.watch(Failed(),None,False,log_path=log)
        self.assertIn('接管被服务端拒绝',self.app.state['message'])
        self.assertEqual(self.app.state['exit_code'],1)
        self.assertIn('Play-style',log.read_text())
        self.assertFalse(self.app.state['eligible'])

    def test_preview_below_minimum_and_changed_minimum(self):
        p=dict(self.payload(),total_ms=1000,minimum_total_ms=5000)
        self.finished_preview(p)
        self.app.confirm_available(p)
        catalog=Catalog(path=self.root/'actions.json',motion_root=self.root)
        meta=catalog.assets['Custom']['metadata']
        self.assertEqual(meta['preview_confirmation']['total_ms'],5000)
        self.assertEqual(catalog.execution_timing('Custom')['minimum_remaining_s'],5.0)

    def test_rerecord_requires_new_confirmation_and_auto_disables(self):
        p=self.payload('Beat');self.finished_preview(p);self.app.confirm_available(p)
        register(self.root,self.source,'Beat','prosody',overwrite=True)
        self.assertNotIn('Beat',Catalog(path=self.root/'actions.json',motion_root=self.root).actions)
        meta=json.loads((self.root/'metadata/Beat.json').read_text())
        self.assertNotIn('preview_confirmation',meta)


if __name__=='__main__':unittest.main()
