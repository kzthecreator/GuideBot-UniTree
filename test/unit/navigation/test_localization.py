import contextlib
import io
import json
import socket
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import numpy as np

from GuideBot.navigation.localization import MapTracker, decode_cloud
from test.tools.navigation.localization_runtime import SensorInbox
from test.tools.navigation.localization_web import start


class LocalizationTests(unittest.TestCase):
    def tracker(self, pose=(.1,0,0), quality=(.9,.03)):
        return MapTracker(np.ones((50,3)),matcher=lambda *args:(np.array(pose),quality))

    def test_stale_pose_is_not_valid_and_yaw_wrap_is_continuous(self):
        guesses=[]
        def matcher(cloud,ref,guess):
            guesses.append(guess.copy())
            return guess, [.9,.03]
        tracker=MapTracker(np.ones((50,3)),matcher=matcher)
        tracker.match(np.ones((50,3)),1.,np.deg2rad(179),10.,now=10.)
        tracker.match(np.ones((50,3)),1.5,np.deg2rad(-179),10.5,now=10.5)
        self.assertAlmostEqual(guesses[-1][2],np.deg2rad(2))
        self.assertTrue(tracker.snapshot(11.)['valid'])
        stale=tracker.snapshot(13.)
        self.assertFalse(stale['valid']);self.assertEqual(stale['state'],'stale')
        self.assertEqual(stale['accepted'],2)

    def test_bad_quality_never_updates_accepted_pose_and_three_failures_latch_lost(self):
        tracker=self.tracker()
        tracker.match(np.ones((50,3)),1.,0.,10.,now=10.)
        accepted=tracker.pose.copy()
        tracker.matcher=lambda *args:(np.array([.2,0,0]),[.3,.04])
        for i in range(3):
            result=tracker.match(np.ones((50,3)),1.1+i*.1,0.,10.1+i*.1,now=10.1+i*.1)
        np.testing.assert_allclose(tracker.pose,accepted)
        self.assertFalse(result['valid']);self.assertEqual(result['state'],'lost')
        tracker.matcher=lambda *args:(np.zeros(3),[.9,.03])
        self.assertEqual(tracker.match(np.ones((50,3)),1.5,0.,10.5,now=10.5)['state'],'lost')
        self.assertEqual(tracker.state['accepted'],1)

    def test_large_jump_backward_clock_and_long_gap_are_rejected(self):
        for failure in ['jump','clock','gap']:
            tracker=self.tracker()
            tracker.match(np.ones((50,3)),1.,0.,10.,now=10.)
            if failure=='jump':tracker.matcher=lambda *args:(np.array([2.,0,0]),[.99,.01])
            stamp={'jump':1.1,'clock':.9,'gap':4.}[failure]
            result=tracker.match(np.ones((50,3)),stamp,0.,10.5,now=10.5)
            self.assertFalse(result['valid']);self.assertEqual(result['state'],'lost')
            self.assertEqual(result['accepted'],1)

    def test_delayed_input_and_processing_results_are_rejected(self):
        tracker=self.tracker()
        self.assertFalse(tracker.match(np.ones((50,3)),1.,0.,10.,now=13.)['valid'])
        def slow(cloud,ref,guess):
            return guess,[.9,.03]
        tracker=MapTracker(np.ones((50,3)),matcher=slow)
        with patch('GuideBot.navigation.localization.time.monotonic',side_effect=[10.,13.,13.,13.]):
            result=tracker.match(np.ones((50,3)),1.,0.,10.,now=10.)
        self.assertFalse(result['valid']);self.assertEqual(tracker.state['accepted'],0)

    def test_inbox_retains_latest_cloud_only_and_rejects_unbracketed_yaw(self):
        from runtime.ipc.sensor_wire import send
        a,b=socket.socketpair();inbox=SensorInbox(b,{})
        inbox.thread.start()
        send(a,dict(track='cloud',received_ns=1),b'first')
        send(a,dict(track='cloud',received_ns=2),b'latest')
        a.close();inbox.thread.join(timeout=2)
        try:
            self.assertTrue(inbox.done)
            self.assertEqual(inbox.take()[0],b'latest')
            self.assertIsNone(inbox.take());self.assertEqual(inbox.overwritten,1)
            inbox.odometry.extend([(1.,3.13),(2.,-3.13)])
            self.assertAlmostEqual(inbox.yaw_at(1.5),np.pi)
            with self.assertRaises(ValueError):inbox.yaw_at(2.2)
        finally:b.close()

    def test_browser_only_exposes_map_status_and_page(self):
        tracker=self.tracker()
        server,thread=start(b'png',dict(width=10),tracker.snapshot,0)
        try:
            base='http://127.0.0.1:'+str(server.server_port)
            with urllib.request.urlopen(base+'/status') as r:
                self.assertFalse(json.load(r)['valid'])
            with urllib.request.urlopen(base+'/map.png') as r:self.assertEqual(r.read(),b'png')
            with urllib.request.urlopen(base+'/') as r:self.assertIn('canvas',r.read().decode())
            for path in ['/samples.cdr','/../report.json','/status.json']:
                with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(base+path)
        finally:server.shutdown();server.server_close();thread.join(timeout=2)

    def test_invalid_cli_arguments_do_not_launch_or_request_enter(self):
        from test.tools.navigation.localize import main
        with tempfile.TemporaryDirectory() as tmp:
            with patch('sys.argv',['localize.py','live','--map-directory',tmp]),patch('subprocess.call') as launch,patch('builtins.input') as enter,contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):main()
                launch.assert_not_called();enter.assert_not_called()


if __name__=='__main__':unittest.main()
