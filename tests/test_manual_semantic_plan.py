import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from GuideBot.gesture.catalog import Catalog

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'examples/gesture_from_audio'))
from manual_plan import arrange
from complete_plan import native_validate
from rehearse import load_plan


class ManualSemanticTests(unittest.TestCase):
    def setUp(self):
        path=ROOT/'examples/gesture_from_audio/data/g1_selfprompt.timestamps.json'
        if not path.is_file():self.skipTest('local example audio assets are not restored')
        self.doc=json.loads(path.read_text());self.catalog=Catalog()

    def test_phrase_alignment_approved_core_and_native_continuous_check(self):
        padding,rows,sequence=arrange(self.catalog,self.doc)
        self.assertEqual(padding,.8)
        self.assertEqual(len(rows),8)
        self.assertTrue(all(r['core_s']>=r['approved_core_s'] for r in rows))
        for a,b in zip(rows,rows[1:]):self.assertLessEqual(a['end_s'],b['start_s'])
        self.assertEqual(rows[1]['hold_s'],.3)
        self.assertEqual(rows[5]['hold_s'],.5)
        self.assertEqual(rows[6]['core_s'],.88)
        self.assertAlmostEqual(rows[1]['target_s'],self.doc['timestamps'][17]['start']+padding)
        with tempfile.TemporaryDirectory() as tmp:
            result=native_validate(sequence,Path(tmp))
            self.assertIn('9 steps',result)

    def test_explicit_neutral_closing_compiles_and_passes_rehearsal_gate(self):
        import hashlib
        padding,rows,sequence=arrange(self.catalog,self.doc,closing='B_Neutral_Rest')
        self.assertEqual(len(rows),9)
        self.assertEqual(rows[-1]['action'],'B_Neutral_Rest')
        self.assertEqual(sequence['steps'][-1]['name'],'B_Neutral_Rest')
        self.assertAlmostEqual(rows[-1]['target_s'],self.doc['timestamps'][112]['start']+padding)
        self.assertLess(rows[-1]['end_s'],self.doc['duration_seconds']+padding)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'audio.wav';audio.write_bytes(b'fixture audio')
            snapshot={name:{k:self.catalog.assets[name]['metadata'][k] for k in ('sha256','version')}
                      for name in {'B_Neutral_Rest','B_Parallel_Drop',*(a['action'] for a in rows)}}
            summary=dict(mode='complete',replay_ready=True,missing_assets=[],action_limit=None,
                initial_pose='B_Parallel_Drop',audio_file='audio.wav',sequence=sequence,actions=rows,
                trajectory_seconds=rows[-1]['end_s'],timestamps=self.doc['timestamps'],
                validation=dict(duration_seconds=self.doc['duration_seconds']+padding,
                                audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest()))
            (root/'summary.json').write_text(json.dumps(summary))
            (root/'motion-snapshot.json').write_text(json.dumps(snapshot))
            checked,_=load_plan(root,self.catalog)
            self.assertTrue(checked['replay_ready'])
            self.assertIn('10 steps',json.loads((root/'native-continuous-check.json').read_text())['stdout'])

    def test_unfinished_closing_cannot_start_hardware(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'summary.json').write_text(json.dumps(dict(mode='complete',replay_ready=False,missing_assets=['R_Center_Rest'])))
            with self.assertRaisesRegex(ValueError,'R_Center_Rest'):load_plan(root,self.catalog)


if __name__=='__main__':unittest.main()
