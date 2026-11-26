import json
from pathlib import Path
import tempfile
import unittest
from GuideBot.gesture.diagnostics import DialogueSummary


class DiagnosticsTests(unittest.TestCase):
    def test_interleaved_responses_preserve_rejections_and_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = DialogueSummary(directory)
            events = [
                dict(kind='gesture.text', response_id='a', text='你好', complete=True),
                dict(kind='gesture.text', response_id='b', text='再见'),
                dict(kind='gesture.planner_result', response_id='a', total_seconds=.4),
                dict(kind='gesture.planned', response_id='a', job_id='1', action='test'),
                dict(kind='gesture.alignment_snapshot', response_id='a', anchor_count=2, version=1),
                dict(kind='gesture.command', response_id='a', job_id='1', execution_error='rejected'),
                dict(kind='gesture.skipped', response_id='a', job_id='1', reason='execution_rejected'),
                dict(kind='gesture.cancelled', response_id='b', reason='interrupted')]
            for event in events:
                summary.observe(dict(event, monotonic=1.))
            rows = json.loads((Path(directory)/'gesture-summary.json').read_text())['responses']
            a, b = rows
            self.assertEqual(a['text'], '你好')
            self.assertEqual(a['planner_requests'][0]['total_seconds'], .4)
            self.assertEqual(a['alignment']['anchor_count'], 2)
            self.assertEqual(a['skipped'][0]['reason'], 'execution_rejected')
            self.assertEqual(len(a['dispatched']), 1)
            self.assertEqual(len(a['errors']), 1)
            self.assertEqual(a['completed'], [])
            self.assertEqual(b['cancelled'][0]['reason'], 'interrupted')
