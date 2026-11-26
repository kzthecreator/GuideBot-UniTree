import json
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.motion import record_tasks as queue
from tools.motion.register_recording import replace
from drivers.unitree_motion.assets import asset_path, catalog_entries
from GuideBot.gesture.catalog import Catalog


class TaskRecordingTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'config').mkdir()
        (self.root/'config/motion_catalog.json').write_text('{"schema_version":1,"actions":[]}')
        self.tasks = queue.load_tasks(queue.DEFAULT_TASKS)

    def capture_file(self, destination):
        destination.write_text('2\n14\n' + ('0.3 ' + ' '.join(['0']*14) + '\n')*2)

    def test_recordable_presets_register_with_original_chinese_and_subclass(self):
        self.assertEqual(list(self.tasks), [f'{i:02}' for i in range(1,18) if i != 16])
        self.assertEqual(sum(x['group']=='semantic' for x in self.tasks.values()), 8)
        self.assertEqual(sum(x['group']=='prosody' for x in self.tasks.values()), 8)
        source = self.root/'capture.dat'
        self.capture_file(source)
        for key, task in self.tasks.items():
            if task.get('reuse_existing'):
                continue
            self.assertEqual(queue.task_status(self.root, task), ('待录制', False))
            queue.save_task(self.root, source, task)
            meta = json.loads((self.root/'metadata'/(task['name']+'.json')).read_text())
            for field, expected in [('label',task['label']),('description',task['description']),
                                    ('gesture_subcategory',task['subcategory']),('recording_task_id',key)]:
                self.assertEqual(meta[field], expected)
            self.assertEqual(queue.task_status(self.root, task), ('已录制待验收', True))
        catalog = Catalog(path=self.root/'actions.json', motion_root=self.root)
        self.assertEqual(len(catalog.definitions), 15)
        self.assertEqual(catalog.actions, {})
        prosody = json.loads((self.root/'prosody_catalog.json').read_text())['actions']
        self.assertEqual(len(prosody),7)
        self.assertEqual(prosody[-1]['family'],'posture')
        entries = catalog_entries(self.root/'config/motion_catalog.json')
        self.assertNotIn('B_Neutral_Return',entries)
        self.assertNotIn('B_Neutral_Rest',entries)

    def test_progress_requires_valid_asset_and_overwrite_resets_approval(self):
        source = self.root/'capture.dat'
        self.capture_file(source)
        task = self.tasks['01']
        queue.save_task(self.root, source, task)
        path = self.root/'metadata'/(task['name']+'.json')
        meta = json.loads(path.read_text())
        meta.update(status='approved',verified_by='tester',verified_at='today')
        replace(path, (json.dumps(meta)+'\n').encode())
        self.assertEqual(queue.task_status(self.root, task), ('已验收', True))
        with self.assertRaises(ValueError):
            queue.save_task(self.root, source, task)
        queue.save_task(self.root, source, task, overwrite=True)
        self.assertEqual(queue.task_status(self.root, task), ('已录制待验收', True))
        entry = catalog_entries(self.root/'config/motion_catalog.json')[task['name']]
        asset_path(entry,self.root/'motions',self.root/'poses').write_text('bad')
        self.assertEqual(queue.task_status(self.root,task),('资产异常，需检查',True))

    def test_loop_saves_then_cancel_returns_to_list_without_extra_prompts(self):
        calls=[]
        def capture(binary, root, destination):
            calls.append(destination)
            if len(calls)==1:
                self.capture_file(destination)
            return 0
        with patch('builtins.input',side_effect=['1','','2','','q']), patch.object(queue,'capture',side_effect=capture):
            queue.session(self.root,self.tasks,Path('/unused/binary'))
        self.assertEqual(len(calls),2)
        self.assertEqual(queue.task_status(self.root,self.tasks['01']),('已录制待验收',True))
        self.assertEqual(queue.task_status(self.root,self.tasks['02']),('待录制',False))
        self.assertFalse(calls[0].exists())

    def test_cancel_before_capture_and_failed_registration_retain_capture(self):
        with patch('builtins.input',side_effect=['01','c','q']), patch.object(queue,'capture') as capture:
            queue.session(self.root,self.tasks,Path('/unused'))
        capture.assert_not_called()
        def capture(binary,root,destination):
            self.capture_file(destination)
            return 0
        with patch('builtins.input',side_effect=['01','','q']), patch.object(queue,'capture',side_effect=capture), patch.object(queue,'save_task',side_effect=OSError('failure')):
            queue.session(self.root,self.tasks,Path('/unused'))
        self.assertEqual(len(list(self.root.glob('.recording-task-*.dat'))),1)
        self.assertEqual(catalog_entries(self.root/'config/motion_catalog.json'),{})

    def test_neutral_reference_never_captures_or_overwrites(self):
        source=self.root/'capture.dat'
        source.write_text('1\n14\n' + '0.3 ' + ' '.join(['0']*14) + '\n')
        from tools.motion.register_recording import register
        register(self.root,source,'B_Neutral_Rest','semantic')
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('builtins.input',side_effect=['17','q']), patch.object(queue,'capture') as capture:
            queue.session(self.root,self.tasks,Path('/unused'))
        capture.assert_not_called()
        with self.assertRaises(ValueError):
            queue.save_task(self.root,source,self.tasks['17'],overwrite=True)
        after={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        self.assertNotIn('16',self.tasks)

    def test_old_binary_is_rejected_without_execution(self):
        binary = self.root/'old_recorder'
        binary.write_bytes(b'old executable without capture mode')
        with patch('sys.argv',['record_tasks.py','--root',str(self.root),'--binary',str(binary)]), patch.object(queue.subprocess,'run') as run:
            self.assertEqual(queue.main(),1)
        run.assert_not_called()

    def test_list_only_does_not_launch_binary_or_register(self):
        with patch('sys.argv',['record_tasks.py','--root',str(self.root),'--list']), patch.object(queue.subprocess,'run') as run:
            self.assertEqual(queue.main(),0)
        run.assert_not_called()
        self.assertEqual(catalog_entries(self.root/'config/motion_catalog.json'),{})


if __name__=='__main__':
    unittest.main()
