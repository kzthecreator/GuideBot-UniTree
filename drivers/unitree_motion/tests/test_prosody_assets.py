"""Prosody authoring stays on the existing physical asset pipeline; no hardware."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from drivers.unitree_motion import assets
from drivers.unitree_motion.paths import ASSETS

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools/motion'))
import motion_library

PROSODY = {
    'B_Down_Beat': 'beat', 'B_Double_Beat': 'beat', 'R_Single_Beat': 'beat',
    'B_Open_Accent': 'accent', 'B_Forward_Accent': 'accent',
    'B_Arc_Flow': 'flow', 'R_Sweep_Flow': 'flow', 'B_Lower_Cadence': 'cadence',
}
LEGACY = {
    'basic': ['B_Neutral_Rest'],
    'reception': ['B_Open_Hold', 'L_Greeting_Wave', 'B_Guiding_Swing', 'B_Question_Invite'],
    'presentation': ['R_Center_Present', 'L_Side_Present', 'R_Side_Present',
                     'B_Forward_Indicate', 'L_Side_Indicate', 'R_Side_Indicate'],
    'interaction': ['B_Question_Acknowledge', 'B_Answer_Open', 'L_Front_Hold', 'R_Head_Side_Hold',
                    'B_Staff_Refer', 'B_Single_Emphasis', 'B_Double_Emphasis', 'B_Thanks'],
    'elevator': ['R_Elevator_Panel_Indicate', 'R_Elevator_Button_Prepose', 'B_Elevator_Boarding_Invite'],
}


class ProsodyAssetsTest(unittest.TestCase):
    def setUp(self):
        self.entries = assets.catalog_entries(ASSETS / 'config/motion_catalog.json')

    def test_legacy_22_and_prosody_8_paths(self):
        self.assertGreaterEqual(len(self.entries), 30)
        for category, names in LEGACY.items():
            for name in names:
                entry = self.entries[name]
                kind = 'pose' if name == 'B_Neutral_Rest' else 'motion'
                self.assertEqual((entry['category'], entry['type']), (category, kind))
                directory = 'poses' if kind == 'pose' else 'motions'
                self.assertEqual(assets.asset_path(entry, ASSETS/'motions', ASSETS/'poses'),
                                 ASSETS / directory / category / (name + '.dat'))
        for name in PROSODY:
            self.assertEqual(self.entries[name]['type'], 'motion')
            self.assertEqual(assets.asset_path(self.entries[name], ASSETS/'motions', ASSETS/'poses'),
                             ASSETS/'motions/prosody'/(name + '.dat'))

    def test_prosody_descriptions_disabled_and_no_placeholder_assets(self):
        document = json.loads((ASSETS/'prosody_catalog.json').read_text())
        self.assertEqual(document['version'], 1)
        self.assertGreaterEqual(len(document['actions']), 8)
        self.assertEqual({row['id']: row['family'] for row in document['actions'] if row['id'] in PROSODY}, PROSODY)
        for row in document['actions']:
            if row['id'] not in PROSODY:
                continue
            self.assertIs(row['enabled'], False)
            self.assertTrue(row['description'])
            result, errors, _ = assets.inspect(row['id'], self.entries, ASSETS/'motions',
                                              ASSETS/'poses', ASSETS/'metadata')
            self.assertIsNone(result)
            self.assertEqual(errors, ['动作文件不存在'])

    def test_dynamic_catalog_and_invalid_categories_or_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'catalog.json'
            for names in (['B_Neutral_Rest'], list(PROSODY), list(self.entries)):
                path.write_text(json.dumps(dict(schema_version=1,
                                                actions=[self.entries[n] for n in names])))
                self.assertEqual(set(assets.catalog_entries(path)), set(names))
            for category, kind in [('prosody', 'pose'), ('unknown', 'motion'), ('basic', 'motion')]:
                entry = dict(self.entries['B_Down_Beat'], category=category, type=kind)
                path.write_text(json.dumps(dict(schema_version=1, actions=[entry])))
                with self.assertRaises(ValueError):
                    assets.catalog_entries(path)

    def test_all_30_use_existing_parser_and_metadata_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, entry in self.entries.items():
                path = assets.asset_path(entry, root/'motions', root/'poses')
                path.parent.mkdir(parents=True, exist_ok=True)
                frames = 1 if entry['type'] == 'pose' else 3
                path.write_text(f'{frames}\n14\n' + ('0.3 ' + ' '.join(['0']*14) + '\n')*frames)
                points, errors, _ = assets.parse_motion(path)
                self.assertFalse(errors)
                motion_library.write_meta(root/'metadata'/(name+'.json'),
                                          motion_library.metadata_for(entry, path, points))
                result, errors, _ = assets.inspect(name, self.entries, root/'motions',
                                                  root/'poses', root/'metadata')
                self.assertFalse(errors, (name, errors))
                self.assertEqual(result[1]['category'], entry['category'])
