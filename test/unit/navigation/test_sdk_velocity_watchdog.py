"""Exercise the actual SDK worker loop with a fake RPC sink, no robot imports."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


class SDKVelocityWatchdogTests(unittest.TestCase):
    def test_sender_loss_and_process_stop_send_zero_with_short_duration(self):
        with tempfile.TemporaryDirectory(prefix='gb-vtest-') as tmp:
            root=Path(tmp);endpoint=root/'v.sock';trace=root/'trace.jsonl'
            code='''
import json,sys,time
from pathlib import Path
from GuideBot.robot.navigation import run
root=Path(sys.argv[1])
class Fake:
    def GetFsmId(self):return 0,500
    def SetVelocity(self,*velocity,duration):
        with (root/'trace.jsonl').open('a') as f:f.write(json.dumps(dict(at=time.monotonic(),v=velocity,duration=duration))+'\\n')
        return 0
run(root/'v.sock',root,dict(confirmed=True,evidence='unit test fake only',body_x_in_lidar_m=0.,
    body_y_in_lidar_m=0.,body_yaw_in_lidar_rad=0.,body_radius_m=.4,waist_reference_rad=[0.,0.,0.]),'test',client=Fake())
'''
            process=subprocess.Popen([sys.executable,'-c',code,tmp],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            def rows():
                try:return [json.loads(line) for line in trace.read_text().splitlines()]
                except (OSError,ValueError):return []
            def wait(predicate):
                end=time.monotonic()+4
                while time.monotonic()<end:
                    if predicate():return
                    if process.poll() is not None:
                        self.fail(process.communicate()[1].decode())
                    time.sleep(.01)
                self.fail('Velocity worker test timeout')
            try:
                wait(lambda:(root/'velocity.ready').exists())
                with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as channel:
                    channel.sendto(json.dumps(dict(token='test',sequence=1,sent_at=time.monotonic(),
                        enabled=True,velocity=[.1,0.,0.])).encode(),str(endpoint))
                wait(lambda:any(row['v'][0]>.05 for row in rows()))
                moving=next(row for row in rows() if row['v'][0]>.05)
                wait(lambda:any(row['at']>moving['at'] and row['v']==[0.,0.,0.] for row in rows()))
                stopped=next(row for row in rows() if row['at']>moving['at'] and row['v']==[0.,0.,0.])
                self.assertLess(stopped['at']-moving['at'],.5)
                self.assertTrue(all(row['duration']<=.2 for row in rows()))
                process.terminate();process.wait(timeout=3)
                self.assertEqual(rows()[-1]['v'],[0.,0.,0.])
                self.assertTrue(json.loads((root/'velocity-status.json').read_text())['stopped'])
            finally:
                if process.poll() is None:process.kill();process.wait()
                process.communicate()


if __name__=='__main__':unittest.main()
