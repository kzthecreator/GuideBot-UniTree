import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from test.tools.navigation.browser_rviz import private_write,worker_matches
from test.tools.navigation.rviz_config import generate
from test.tools.navigation.probe_browser_rviz import capture


class BrowserRvizTests(unittest.TestCase):
    def test_browser_profile_only_uses_available_foxy_plugins_and_readable_map_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);maps=root/'map';maps.mkdir()
            (maps/'report.json').write_text(json.dumps(dict(status='offline_draft_consistent')))
            with patch.dict(os.environ,{'GUIDEBOT_RVIZ_BROWSER':'1'}):
                params,rviz=generate(root,maps)
            manager=yaml.safe_load(rviz.read_text())['Visualization Manager']
            self.assertEqual(manager['Global Options']['Frame Rate'],5)
            self.assertEqual(manager['Views']['Current']['Class'],'rviz_default_plugins/TopDownOrtho')
            def classes(displays):
                result=[]
                for item in displays:
                    result.append(item['Class']);result.extend(classes(item.get('Displays',[])))
                return result
            self.assertNotIn('rviz_default_plugins/DepthCloud',classes(manager['Displays']))
            self.assertIn('rviz_default_plugins/Map',classes(manager['Displays']))

    def test_session_files_are_private_and_pid_guard_does_not_accept_unrelated_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'session-secret'
            private_write(path,'test-credential')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertFalse(worker_matches(os.getpid(),Path(tmp)))
            self.assertFalse(worker_matches(99999999,Path(tmp)))

    def test_navigation_footprint_avoids_foxy_polygon_background_gl_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);maps=root/'map';maps.mkdir()
            (maps/'report.json').write_text(json.dumps(dict(status='offline_draft_consistent')))
            _,rviz=generate(root,maps,navigation=True)
            nav=next(d for d in yaml.safe_load(rviz.read_text())['Visualization Manager']['Displays'] if d['Name']=='Nav2')
            local=next(d for d in nav['Displays'] if d['Name']=='Footprint')
            self.assertEqual(local['Class'],'rviz_default_plugins/Marker')
            self.assertTrue(local['Enabled'])
            self.assertEqual(local['Topic']['Value'],'/guidebot/navigation/local_footprint')
            self.assertFalse(any(d['Class']=='rviz_default_plugins/Polygon' for d in nav['Displays']))

    def test_disconnected_desktop_reports_failure_without_missing_port_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'status.json').write_text(json.dumps(dict(state='stopped',error='test RViz failure')))
            with self.assertRaisesRegex(RuntimeError,'Browser desktop is not running: test RViz failure'):
                capture(root)


if __name__=='__main__':unittest.main()
