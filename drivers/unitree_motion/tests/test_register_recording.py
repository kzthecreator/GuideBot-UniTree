import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.motion import register_recording as recording
from drivers.unitree_motion import assets
from GuideBot.gesture.catalog import Catalog


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()
        (self.root / 'config/motion_catalog.json').write_text('{"schema_version":1,"actions":[]}')
        self.source = self.root / 'capture.dat'
        self.capture(2)

    def capture(self, count):
        self.source.write_text(str(count) + '\n14\n' + ('0.3 ' + ' '.join(['0']*14) + '\n')*count)

    def read(self, path):
        return json.loads((self.root / path).read_text())

    def test_overwrite_inherits_prompt_and_requires_web_review(self):
        from tools.motion.descriptions import effective,save_review
        from tools.motion.confirm_motion import confirm
        recording.register(self.root,self.source,'Custom','semantic','初始任务描述')
        old=self.read('metadata/Custom.json')
        (self.root/'prompt_descriptions.json').write_text(json.dumps(dict(version=1,actions={
            'Custom':dict(description='人工润色的两帧动作',sha256=old['sha256'])})))
        self.capture(3)
        recording.register(self.root,self.source,'Custom','semantic','不应覆盖的任务文字',overwrite=True,task_id='01')
        meta=self.read('metadata/Custom.json')
        self.assertEqual(meta['description'],'人工润色的两帧动作')
        self.assertTrue(meta['description_review']['pending'])
        self.assertEqual(meta['description_review']['previous_frames'],2)
        self.assertEqual(meta['description_review']['new_frames'],3)
        entries=assets.catalog_entries(self.root/'config/motion_catalog.json')
        with self.assertRaisesRegex(ValueError,'待校对'):
            confirm(self.root,entries,'Custom',meta['sha256'],meta['version'],{},3000,'test')
        with self.assertRaises(ValueError):
            save_review(self.root,'Custom',meta['sha256'],meta['version'],'新描述',False)
        reviewed=save_review(self.root,'Custom',meta['sha256'],meta['version'],'校对后的三帧轨迹',True)
        self.assertFalse(reviewed['description_review']['pending'])
        self.assertEqual(effective(self.root,'Custom',reviewed),'校对后的三帧轨迹')
        self.assertEqual(reviewed['status'],'draft')
        with self.assertRaisesRegex(ValueError,'已变化'):
            save_review(self.root,'Custom',meta['sha256'],meta['version'],'过期窗口',True)

    def test_semantic_draft_is_valid_and_not_selectable(self):
        path = recording.register(self.root, self.source, 'custom_wave', 'semantic', '挥动')
        entries = assets.catalog_entries(self.root / 'config/motion_catalog.json')
        result, errors, _ = assets.inspect('custom_wave', entries, self.root/'motions', self.root/'poses', self.root/'metadata')
        self.assertEqual(errors, [])
        self.assertEqual(path.parent.name, 'semantic')
        self.assertEqual(result[1]['status'], 'draft')
        catalog = Catalog(path=self.root/'actions.json', motion_root=self.root)
        self.assertIn('custom_wave', catalog.definitions)
        self.assertNotIn('custom_wave', catalog.actions)

    def test_single_frame_prosody_and_overwrite(self):
        self.capture(1)
        path = recording.register(self.root, self.source, 'custom_accent', 'prosody', family='accent')
        self.assertEqual(path, self.root/'poses/basic/custom_accent.dat')
        self.assertEqual(self.read('prosody_catalog.json')['actions'][0]['family'], 'accent')
        with self.assertRaises(ValueError):
            recording.register(self.root, self.source, 'custom_accent', 'prosody')
        meta = self.read('metadata/custom_accent.json')
        meta.update(status='approved', verified_by='tester', verified_at='today')
        (self.root/'metadata/custom_accent.json').write_text(json.dumps(meta))
        recording.register(self.root, self.source, 'custom_accent', 'prosody', overwrite=True)
        meta = self.read('metadata/custom_accent.json')
        self.assertEqual(meta['version'], 2)
        self.assertEqual(meta['status'], 'draft')
        self.assertEqual(meta['verified_by'], '')
        self.assertFalse(self.read('prosody_catalog.json')['actions'][0]['enabled'])

    def test_write_failure_rolls_back(self):
        original = recording.replace
        calls = []
        def fail_once(path, data):
            calls.append(path)
            if len(calls) == 3:
                raise OSError('simulated write failure')
            return original(path, data)
        before = (self.root/'config/motion_catalog.json').read_bytes()
        with patch.object(recording, 'replace', side_effect=fail_once):
            with self.assertRaises(OSError):
                recording.register(self.root, self.source, 'hello', 'semantic')
        self.assertEqual((self.root/'config/motion_catalog.json').read_bytes(), before)
        self.assertFalse((self.root/'metadata/hello.json').exists())
        self.assertFalse((self.root/'motions/semantic/hello.dat').exists())

    def test_cli_interactive_registration_and_live_inventory(self):
        import subprocess
        import sys
        from tools.motion import motion_timing_ui as ui
        with patch.object(ui, 'ROOT', self.root):
            app = ui.App()
            self.assertEqual(app.inventory(), [])
            result = subprocess.run(
                [sys.executable, str(Path(recording.__file__)), '--root', str(self.root),
                 '--recording', str(self.source)],
                input='new_gesture\n1\n介绍动作\n自我介绍\n大家好\n',
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            inventory = app.inventory()
            self.assertEqual([x['name'] for x in inventory], ['new_gesture'])
            self.assertTrue(inventory[0]['available'])
            self.assertEqual(self.read('actions.json')['actions'][0]['semantic_intents'], ['自我介绍'])

    def test_names_can_start_with_uppercase_digit_or_underscore(self):
        for name in ('Wave', '1_wave', '_wave', '123'):
            with self.subTest(name=name):
                recording.register(self.root, self.source, name, 'semantic')
                catalog = Catalog(path=self.root/'actions.json', motion_root=self.root)
                self.assertIn(name, catalog.definitions)

    def test_cancel_and_bad_name(self):
        with patch('builtins.input', return_value='c'):
            recording.prompt(self.root, self.source)
        with self.assertRaises(ValueError):
            recording.register(self.root, self.source, '../escape', 'semantic')
        self.assertEqual(self.read('config/motion_catalog.json')['actions'], [])


if __name__ == '__main__':
    unittest.main()
