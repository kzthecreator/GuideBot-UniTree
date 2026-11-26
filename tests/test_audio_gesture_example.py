import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from GuideBot.gesture.catalog import Catalog

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('audio_example',ROOT/'examples/gesture_from_audio/run.py')
example=importlib.util.module_from_spec(spec);spec.loader.exec_module(example)


class AudioExampleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        import numpy as np
        import soundfile as sf
        sf.write(str(self.root/'speech.wav'),np.zeros(16000*5,dtype='float32'),16000)
        self.doc=dict(text='你好机器人',duration_seconds=5.,timestamps=[
            dict(text=c,text_offset=i,start=float(i),end=i+.8) for i,c in enumerate('你好机器人')])
        example.dump(self.root/'timestamps.json',self.doc)
        self.config=dict(audio='speech.wav',timestamps='timestamps.json',stream_step_s=2.,text_lookahead_s=2.)
        example.dump(self.root/'scenario.json',self.config)
        self.catalog=Catalog()

    def row(self,**fields):
        return dict(dict(action='B_Open_Hold',start_unit=0,arrival_unit=1,start_s=1.,end_s=2.5),**fields)

    def test_validation_and_word_release(self):
        _,_,doc,validation=example.inputs(self.root/'scenario.json')
        self.assertEqual(validation['text_units'],5)
        self.assertEqual(validation['duration_seconds'],5.)
        text,count,complete=example.visible_text(doc,0,1.,'stream')
        self.assertEqual((text,count,complete),('你好',2,False))
        self.doc['timestamps'][2]['end']=9
        example.dump(self.root/'timestamps.json',self.doc)
        with self.assertRaises(ValueError):example.inputs(self.root/'scenario.json')

    def test_window_checks_and_late_arrival(self):
        valid=example.candidate(self.catalog,self.row(),self.doc,0.,[],'preplan')
        self.assertEqual(valid['status'],'accepted')
        for row,arrival,existing in [(self.row(end_s=6),0,[]),(self.row(),3,[]),(self.row(),0,[valid]),
                                      (self.row(action='not_recorded'),0,[])]:
            self.assertEqual(example.candidate(self.catalog,row,self.doc,arrival,existing,'stream')['status'],'rejected')

    def test_plan_report_without_network_and_audio_autoplay(self):
        from GuideBot.gesture.catalog import Plan
        class FakePlanner:
            def plan(self,payload,callback):
                callback(Plan('B_Open_Hold',0,1,{},1.,2.5))
                return dict(total_seconds=.1,valid_actions=1,invalid_actions=0)
        _,audio,doc,validation=example.inputs(self.root/'scenario.json')
        out=self.root/'result';out.mkdir()
        with patch.object(example,'RecordedHTTP',side_effect=AssertionError('network must not run')), patch.object(example,'native_checks'):
            summary=example.plan_run(self.config,audio,doc,validation,out,'preplan',self.catalog,
                                     planner_factory=lambda directory:FakePlanner())
        self.assertEqual(len(summary['actions']),1)
        page=(out/'report.html').read_text()
        self.assertIn('controls',page);self.assertNotIn('autoplay',page)
        self.assertTrue((out/'request-00/messages.json').is_file())
        self.assertEqual(json.loads((out/'simulated-events.json').read_text())[0]['action'],'B_Open_Hold')

    def test_three_action_limit_is_per_request_not_whole_reply(self):
        from GuideBot.gesture.catalog import Plan
        class FakePlanner:
            def plan(self,payload,callback):
                elapsed=payload['playback_elapsed_s']
                if elapsed<4:
                    for start in (elapsed+.2,elapsed+1.1):
                        callback(Plan('B_Open_Hold',0,1,{},start,start+.8))
                return dict(total_seconds=.1,valid_actions=2 if elapsed<4 else 0,invalid_actions=0)
        _,audio,doc,validation=example.inputs(self.root/'scenario.json')
        out=self.root/'stream';out.mkdir()
        with patch.object(example,'native_checks'):
            summary=example.plan_run(self.config,audio,doc,validation,out,'stream',self.catalog,
                                    planner_factory=lambda directory:FakePlanner())
        self.assertEqual(len(summary['actions']),4)
        self.assertEqual(summary['max_actions_per_request'],3)

    def test_raw_response_capture_records_actual_messages(self):
        from unittest.mock import Mock
        wire=example.RecordedHTTP(self.root)
        response=Mock()
        response.iter_lines.return_value=['data: '+json.dumps(dict(choices=[dict(delta=dict(content='{"actions":[]}'))])),
                                         'data: [DONE]']
        wire.session.post=Mock(return_value=response)
        result=wire.post('https://example.invalid',json=dict(messages=[dict(role='system',content='test')]))
        list(result.iter_lines())
        self.assertEqual((self.root/'raw-response.txt').read_text(),'{"actions":[]}')
        sent=json.loads((self.root/'messages.json').read_text())
        self.assertIn('word_timestamps',sent[0]['content'])
        wire.close()


if __name__=='__main__':unittest.main()
