import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from GuideBot.gesture.catalog import Catalog

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('g1_rehearsal',ROOT/'examples/gesture_from_audio/rehearse.py')
rehearsal=importlib.util.module_from_spec(spec);spec.loader.exec_module(rehearsal)


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.catalog=Catalog()
        self.catalog.limits_path=self.root/'limits.json'
        self.catalog.limits_path.write_text(json.dumps(dict(verified=True,verified_by='test',verified_at='test')))
        self.audio=self.root/'audio.mp3';self.audio.write_bytes(b'fixture audio')
        self.summary=dict(mode='stream',validation=dict(audio_sha256=hashlib.sha256(self.audio.read_bytes()).hexdigest(),duration_seconds=3.),
            timestamps=[{},{}],actions=[dict(action='B_Open_Hold',start_unit=0,arrival_unit=1,start_s=1.,end_s=2.5,dispatch_s=1.)])
        (self.root/'summary.json').write_text(json.dumps(self.summary))
        meta=self.catalog.assets['B_Open_Hold']['metadata']
        (self.root/'motion-snapshot.json').write_text(json.dumps(dict(B_Open_Hold={k:meta[k] for k in ('sha256','version')})))
        self.clock_value=100.
        self.runtime=SimpleNamespace(process=SimpleNamespace(poll=lambda:None),started=False,stopped=False)
        self.runtime.start=lambda:setattr(self.runtime,'started',True)
        self.runtime.stop=lambda:setattr(self.runtime,'stopped',True)
        self.runtime._status=lambda:dict(ownership='owned',state='idle')
        self.sent=[]
        def request(payload):
            self.sent.append(payload)
            return dict(status=self.runtime._status(),accepted=True)
        self.runtime.request=request
        test=self
        class Speaker:
            closed=False
            returncode=0
            def start(self,audio,logdir):return 100.
            def poll(self):return 0 if test.clock_value>=103 else None
            def close(self):self.closed=True
        self.speaker=Speaker()

    def run_rehearsal(self):
        def sleep(seconds):self.clock_value+=seconds
        with contextlib.redirect_stdout(io.StringIO()):
            rehearsal.rehearse(self.root,self.catalog,self.summary,self.audio,self.root/'logs',
                runtime_factory=lambda:self.runtime,speaker_factory=lambda:self.speaker,
                clock=lambda:self.clock_value,sleep=sleep)

    def test_plan_checks_reject_preplan_changed_assets_and_audio(self):
        rehearsal.load_plan(self.root,self.catalog)
        self.summary['mode']='preplan'
        (self.root/'summary.json').write_text(json.dumps(self.summary))
        with self.assertRaises(ValueError):rehearsal.load_plan(self.root,self.catalog)
        self.summary['mode']='stream';(self.root/'summary.json').write_text(json.dumps(self.summary))
        self.audio.write_bytes(b'changed')
        with self.assertRaises(ValueError):rehearsal.load_plan(self.root,self.catalog)

    def test_playback_origin_and_cleanup_with_fake_hardware(self):
        self.run_rehearsal()
        self.assertTrue(self.runtime.started);self.assertTrue(self.runtime.stopped);self.assertTrue(self.speaker.closed)
        commands=[r for r in self.sent if '序列' in r]
        self.assertEqual(len(commands),1)
        self.assertEqual(commands[0]['end_monotonic'],102.5)
        log=[json.loads(r) for r in (self.root/'logs/events.jsonl').read_text().splitlines()]
        self.assertIn('G1 SDK',log[0]['clock_reference'])
        self.assertTrue(any(r['event']=='submitted' for r in log))

    def test_sdk_start_failure_releases_arms(self):
        self.speaker.start=lambda *a:(_ for _ in ()).throw(RuntimeError('speaker failed'))
        with self.assertRaises(RuntimeError):self.run_rehearsal()
        self.assertTrue(self.runtime.stopped);self.assertTrue(self.speaker.closed)
        self.assertFalse(any('序列' in r for r in self.sent))

    def test_busy_action_is_skipped_not_shifted(self):
        self.runtime._status=lambda:dict(ownership='owned',state='running')
        self.run_rehearsal()
        log=[json.loads(r) for r in (self.root/'logs/events.jsonl').read_text().splitlines()]
        self.assertTrue(any(r['event']=='skipped' for r in log))
        self.assertFalse(any('序列' in r for r in self.sent))

    def test_keyboard_interrupt_stops_sdk_and_releases_arms(self):
        self.speaker.start=lambda *a:(_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):self.run_rehearsal()
        self.assertTrue(self.runtime.stopped);self.assertTrue(self.speaker.closed)

    def test_default_cli_does_not_initialize_hardware(self):
        with patch('sys.argv',['rehearse.py','--result',str(self.root),'--legacy-stream']), patch.object(rehearsal,'Catalog',return_value=self.catalog), patch.object(rehearsal,'rehearse') as run, contextlib.redirect_stdout(io.StringIO()):
            rehearsal.main()
        run.assert_not_called()

    def test_robot_cli_requires_explicit_enter(self):
        with patch('sys.argv',['rehearse.py','--result',str(self.root),'--robot','--legacy-stream']), patch.object(rehearsal,'Catalog',return_value=self.catalog), patch('builtins.input',return_value='cancel'), patch.object(rehearsal,'rehearse') as run, contextlib.redirect_stdout(io.StringIO()):
            rehearsal.main()
        run.assert_not_called()


class G1SpeakerWorkerTests(unittest.TestCase):
    def test_production_speaker_uses_playstream_and_playstop_with_fake_sdk(self):
        import numpy as np
        import soundfile as sf
        from speaker_g1 import play_file
        calls=[]
        class Client:
            def SetTimeout(self,x):pass
            def Init(self):pass
            def SetVolume(self,x):return 0
            def GetVolume(self):return (0,{'volume':100})
            def PlayStream(self,app,stream,chunk):calls.append(('PlayStream',len(chunk)));return (0,{})
            def PlayStop(self,app):calls.append(('PlayStop',app));return (0,{})
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'audio.wav';sf.write(str(source),np.zeros(240,dtype='float32'),24000)
            with patch('GuideBot.conversation.playback.load_audio_sdk',return_value=(lambda *a:None,Client)), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(play_file(source),0)
        self.assertTrue(any(c[0]=='PlayStream' for c in calls))
        self.assertTrue(any(c[0]=='PlayStop' for c in calls))


if __name__=='__main__':unittest.main()
