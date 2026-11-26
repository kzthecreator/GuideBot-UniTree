import queue
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from drivers.timestamps.runtime import StreamingTimestamps, _worker
from GuideBot.gesture.service import planning_anchors


class StreamingBacklogTests(unittest.TestCase):
    def test_full_ipc_coalesces_without_losing_audio_or_text(self):
        worker=StreamingTimestamps('/tmp/unused',Mock())
        worker.enabled=True
        worker.incoming=queue.Queue(maxsize=1)
        worker.incoming.put(('busy',None,None,0))
        for _ in range(1000):
            worker.send('audio','r',b'\x01\x00'*16)
            worker.send('text_delta','r','字')
        self.assertTrue(worker.enabled)
        self.assertEqual(len(worker.pending),1)
        worker.incoming.get()
        with worker.pending_lock:worker._flush_pending()
        action,rid,bundle,_=worker.incoming.get()
        self.assertEqual(action,'bundle')
        self.assertEqual(bytes(bundle['audio']),b'\x01\x00'*16000)
        self.assertEqual(bundle['text'],'字'*1000)

    def test_cancel_drops_pending_old_audio_before_next_reply(self):
        worker=StreamingTimestamps('/tmp/unused',Mock());worker.enabled=True
        worker.incoming=queue.Queue(maxsize=1);worker.incoming.put(('busy',None,None,0))
        worker.send('audio','old',b'\x00\x00'*16)
        worker.send('cancel','old');worker.send('audio','new',b'\x01\x00'*16)
        self.assertEqual(list(worker.pending),['old','new'])
        self.assertEqual(worker.pending['old'][0],'cancel')
        self.assertNotIn('old',worker.sent_audio_samples)

    def test_new_alignment_reopens_middle_text_without_replanning_covered(self):
        reply=SimpleNamespace(playback_origin=100.,units=[None]*223,jobs=[],
                              anchors={i:dict(start=8.+i*.1) for i in range(50,65)})
        self.assertEqual(planning_anchors(reply,105.),list(range(50,65)))
        reply.jobs=[SimpleNamespace(status='scheduled',plan=SimpleNamespace(start_unit=53,arrival_unit=57))]
        self.assertNotIn(55,planning_anchors(reply,105.))
        self.assertEqual(planning_anchors(reply,120.),[])

    def test_missing_timestamps_are_not_guessed(self):
        reply=SimpleNamespace(playback_origin=None,units=[None]*223,jobs=[],anchors={})
        self.assertEqual(planning_anchors(reply,0.),[])

    def test_scheduled_time_window_excludes_other_uncovered_words(self):
        job=SimpleNamespace(status='scheduled',plan=SimpleNamespace(start_unit=1,arrival_unit=1),
                            timing=dict(start_s=4.,deadline_s=6.))
        reply=SimpleNamespace(playback_origin=None,units=[None]*10,jobs=[job],
            anchors={2:dict(start=5.),3:dict(start=8.)})
        self.assertEqual(planning_anchors(reply,0.),[3])

    def test_whole_reply_burst_is_processed_in_bounded_windows(self):
        incoming=queue.Queue();seen=[];events=[]
        incoming.put(('bundle','r',dict(text='一'*20,audio=bytes(20*32000),done=True),0.))
        class Backend:
            def align(self,pcm,labels,final=False):
                duration=len(pcm)/32000;seen.append(duration)
                count=min(len(labels),int(duration))
                return [dict(unit,start=i+duration%1,end=i+duration%1+.5) for i,unit in enumerate(labels[:count])],float(count)
        class Output:
            def put(self,event):
                events.append(event)
                if event['kind']=='alignment.final':incoming.put(('stop','',None,0.))
        with tempfile.TemporaryDirectory() as directory, patch('drivers.timestamps.runtime.MonotonicBackend',return_value=Backend()):
            _worker(incoming,Output(),'unused',str(Path(directory)/'worker.log'),
                    dict(window=12.,step=.5,tail=.1,resync_every=0.,final_repair=False,cursor_from_starts=True))
        self.assertLessEqual(max(seen),14.)
        self.assertEqual(len(events[-1]['timestamps']),20)
        self.assertFalse(any(e['kind']=='alignment.warning' for e in events))
