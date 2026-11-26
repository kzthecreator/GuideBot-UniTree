"""Operator configuration wiring; no model calls or audio."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from GuideBot.configuration import USER_CONFIG_DIRECTORY, read_prompt
from GuideBot.conversation import knowledge as kb
from GuideBot.gesture.catalog import Catalog
from GuideBot.gesture.semantic import instructions, local_instructions
from GuideBot.gesture.semantic_planner import SemanticPlanner


class UserConfigTests(unittest.TestCase):
    def test_editable_prompt_and_internal_registry_are_composed(self):
        catalog = Catalog()
        catalog.actions['present_left']['description'] = 'INTERNAL_REGISTRY_SENTINEL'
        public = read_prompt('actions/prompt.md')
        visible, registry = instructions(catalog).rsplit('\n', 1)
        self.assertEqual(visible, public)
        self.assertEqual(local_instructions(catalog), instructions(catalog))
        self.assertTrue(all(set(row) == {'id', 'description', 'when_to_use', 'avoid_when'}
                            for row in json.loads(registry)))
        self.assertIn('# JSON 输出协议', public)
        for action_id in catalog.actions:
            self.assertNotIn(action_id, public)
        with tempfile.TemporaryDirectory() as root:
            prompt = Path(root) / 'actions' / 'prompt.md'
            prompt.parent.mkdir()
            prompt.write_text('优先选择克制的动作。', encoding='utf-8')
            with patch('GuideBot.gesture.semantic.read_prompt',
                       side_effect=lambda name: read_prompt(name, root)):
                first = instructions(catalog)
                self.assertTrue(first.startswith('优先选择克制的动作。'))
                self.assertIn('INTERNAL_REGISTRY_SENTINEL', first)
                prefix, registry = first.split('\n', 1)
                self.assertEqual(prefix, prompt.read_text())
                self.assertIsInstance(json.loads(registry), list)
                self.assertEqual(local_instructions(catalog), first)
                prompt.write_text('不要连续重复动作。', encoding='utf-8')
                self.assertTrue(instructions(catalog).startswith('不要连续重复动作。'))
                with patch('GuideBot.gesture.semantic_planner.requests.Session'):
                    client = SemanticPlanner(catalog, api_key='test-only')
                    self.assertEqual(client.instruct, instructions(catalog))
                    client.close()

    def test_old_knowledge_manifest_keeps_store_and_current_state_takes_priority(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            config = root / 'developer'
            new = (config / 'conversation' / 'knowledge').resolve()
            old = (root / 'GuideBot' / 'agent' / 'knowledge').resolve()
            state_root = root / 'state'
            state = dict(schema=1, directory=str(old), vector_store_id='existing-store',
                         files={'fact.md': {'sha256': 'hash', 'file_id': 'file-old'}},
                         pending={}, retired=[], ready=True)
            legacy_path = kb._manifest_path(old, state_root)
            legacy_path.parent.mkdir(parents=True)
            legacy_path.write_text(json.dumps(state))
            with patch.object(kb, 'USER_CONFIG_DIRECTORY', config), \
                    patch.object(kb, 'LEGACY_KNOWLEDGE_DIRECTORY', old):
                self.assertEqual(kb.load_knowledge(new, state_dir=state_root), 'existing-store')
                path = kb._manifest_path(new, state_root)
                migrated = kb._read_manifest(path, new)
                self.assertEqual(migrated['directory'], str(new))
                self.assertEqual(migrated['files'], state['files'])
                self.assertFalse(path.exists())  # Loading never uploads or writes.
                flat = (config / 'knowledge').resolve()
                flat_path = kb._manifest_path(flat, state_root)
                flat_path.parent.mkdir(parents=True)
                flat_state = dict(state, directory=str(flat), vector_store_id='flat-store')
                flat_path.write_text(json.dumps(flat_state))
                self.assertEqual(kb.load_knowledge(new, state_dir=state_root), 'flat-store')
                path.parent.mkdir(parents=True)
                migrated['vector_store_id'] = 'current-store'
                path.write_text(json.dumps(migrated))
                self.assertEqual(kb.load_knowledge(new, state_dir=state_root), 'current-store')

    def test_default_conversation_prompt_and_knowledge_are_relocated(self):
        self.assertEqual(kb.read_conversation_prompt(), read_prompt('conversation/prompt.md'))
        self.assertTrue(kb._scan(USER_CONFIG_DIRECTORY / 'conversation' / 'knowledge'))
        self.assertFalse((USER_CONFIG_DIRECTORY.parent / 'GuideBot' / 'agent').exists())

    def test_developer_layout_reuses_previous_user_config_state_without_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'developer'
            old = (root / 'user_config' / 'conversation' / 'knowledge').resolve()
            new = (config / 'conversation' / 'knowledge').resolve()
            state_root = root / 'state'
            previous = dict(schema=1, directory=str(old), vector_store_id='preserved-store',
                            files={'fact.md': {'sha256': 'hash', 'file_id': 'preserved-file'}},
                            pending={}, retired=[], ready=True)
            path = kb._manifest_path(old, state_root)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(previous))
            original = path.read_bytes()
            with patch.object(kb, 'USER_CONFIG_DIRECTORY', config):
                self.assertEqual(kb.load_knowledge(new, state_dir=state_root), 'preserved-store')
                migrated = kb._read_manifest(kb._manifest_path(new, state_root), new)
            self.assertEqual(migrated['files'], previous['files'])
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(kb._manifest_path(new, state_root).exists())
