import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from tools.timestamps.optimize_realtime import evaluate, preview


class RealtimeEvaluationTests(unittest.TestCase):
    def test_missing_and_late_accurate_boundaries_fail(self):
        reference = [dict(text='甲', start=.5, end=.7), dict(text='乙', start=1., end=1.2)]
        case = dict(playback=0., tasks=[(0., 'text', '甲乙'), (0., 'audio', 96000)])
        events = [dict(elapsed=.8, kind='alignment.update', start_update=dict(
            anchors=[dict(index=0, text='甲', start=.5)]))]
        result = evaluate(case, events, reference)
        self.assertEqual(result['accurate'], 1)
        self.assertEqual(result['ready'], 0)
        self.assertEqual(result['passed'], 0)
        self.assertEqual(result['deadline_passed'], 0)

    def test_preview_revises_future_markers_but_never_moves_past_markers(self):
        def event(at, *rows):
            return dict(elapsed=at, start_update=dict(anchors=[dict(index=i,text=t,start=s) for i,t,s in rows]))
        events = [event(.1, (0,'甲',1.)), event(.2, (0,'甲',1.2)),
                  event(.8, (0,'甲',.9)), event(1.5, (0,'甲',1.8),(1,'乙',.4))]
        case = dict(playback=0., audio=np.zeros(32000, dtype=np.int16))
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            preview(case, {}, out, events)
            markers = json.loads((out/'markers.json').read_text())
            self.assertEqual([(r['index'],r['at'],r['late']) for r in markers],
                             [(0,.9,False),(1,1.5,True)])
            audio, rate = sf.read(out/'realtime-markers.wav')
            self.assertEqual((len(audio),rate), (32000,16000))


if __name__ == '__main__':
    unittest.main()
