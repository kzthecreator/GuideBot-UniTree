"""Action identity migration must preserve recordings, approvals and demo timing."""
import hashlib
import json
from pathlib import Path
import unittest

from GuideBot.gesture.catalog import Catalog, original_prompt_template

ROOT=Path(__file__).resolve().parents[1]


class ActionIdMigrationTests(unittest.TestCase):
    def setUp(self):
        self.manifest=json.loads((ROOT/'assets/motion/action-id-migration.json').read_text())

    def test_catalog_uses_one_canonical_style(self):
        catalog=Catalog()
        rows=json.loads((ROOT/'assets/motion/config/motion_catalog.json').read_text())['actions']
        for row in rows:
            self.assertRegex(row['name'],r'^[LRB]_[A-Z][A-Za-z0-9]*(?:_[A-Z][A-Za-z0-9]*)*$')
        self.assertEqual(len(catalog.actions),24)
        self.assertFalse(set(self.manifest['mapping']) & set(catalog.definitions))
        self.assertIn('B_Neutral_Rest',catalog.actions)
        self.assertIn('B_Parallel_Drop',catalog.actions)

    def test_trajectory_bytes_and_approval_configuration_are_preserved(self):
        mapping=self.manifest['mapping']
        for old,expected in self.manifest['trajectory_sha256_before'].items():
            path=ROOT/old
            path=path.with_name(mapping.get(path.stem,path.stem)+path.suffix)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),expected)
        def digest(value):
            return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
                separators=(',',':')).encode()).hexdigest()
        for name,expected in self.manifest['approval_identity_free_sha256'].items():
            meta=json.loads((ROOT/'assets/motion/metadata'/(name+'.json')).read_text())
            meta.pop('name',None);meta.pop('label',None)
            self.assertEqual(digest(meta),expected)
        for result,expected in self.manifest['migrated_example_sequence_sha256'].items():
            path=ROOT/'artifacts/gesture-from-audio/g1-self-introduction'/result/'sequence.json'
            if path.is_file():
                self.assertEqual(digest(json.loads(path.read_text())),expected)

    def test_original_prompt_backup_is_unchanged_but_runtime_uses_new_ids(self):
        original=(ROOT/'GuideBot/gesture/prompt_original.md').read_text()
        self.assertIn('neutral',original)
        runtime=original_prompt_template()
        self.assertIn('B_Neutral_Rest',runtime)
        self.assertNotRegex(runtime,r'(?<![A-Za-z0-9_])neutral(?![A-Za-z0-9_])')
