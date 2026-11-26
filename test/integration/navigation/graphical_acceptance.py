"""Native RViz + Nav2 + recorded sensors + actual VNC pixels, never live inputs.

Fails on the user's GL-buffer crash, desktop disconnect, or navigation replay
failure. Requires no keyboard events and never enables the hardware velocity sink.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import signal
import shutil
import sys
import time

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))


def main():
    from test.tools.navigation.browser_rviz import BASE,current
    from test.tools.navigation.probe_browser_rviz import capture
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--duration',type=float,default=12.)
    p.add_argument('--terminate-rviz',action='store_true',help='Verify RViz failure leaves the browser terminal available')
    p.add_argument('--capture',type=Path,default=Path.home()/'.local/state/guidebot/navigation/lab-lv280ttd')
    p.add_argument('--map-directory',type=Path,default=Path.home()/'.local/state/guidebot/navigation/maps/lab-lv280ttd')
    a=p.parse_args()
    if current()[0] is not None:p.error('Stop the existing browser desktop before the graphical replay test')
    cli=[sys.executable,str(REPO/'test/tools/navigation/browser_rviz.py')]
    directory=None;result=dict(passed=False,keyboard_events_sent=0,motion_commands=False)
    try:
        subprocess.run(cli+['start','--navigation','--mode','replay','--duration',str(a.duration),
            '--capture',str(a.capture),'--map-directory',str(a.map_directory),'--port','6081'],check=True)
        directory=(BASE/'current').resolve();result['directory']=str(directory)
        deadline=time.monotonic()+a.duration+45;frames=0;next_probe=0.;terminated=False
        while time.monotonic()<deadline:
            status=json.loads((directory/'status.json').read_text())
            log=directory/'localization/rviz.log'
            text=log.read_text() if log.exists() else ''
            if 'Cannot create GL vertex buffer' in text:
                raise RuntimeError('Native RViz GL vertex buffer crash after sensor/costmap input')
            if status.get('state')!='running':raise RuntimeError('Browser desktop disconnected: '+str(status.get('error')))
            path=directory/'localization/result.json'
            if path.exists():
                replay=json.loads(path.read_text())
                if a.terminate_rviz:
                    if not terminated or not replay.get('error'):raise RuntimeError('Expected RViz failure was not observed')
                    if status.get('session_state')!='failed':time.sleep(.2);continue
                    capture(directory)
                    result.update(passed=True,rviz_failure_retains_browser=True,frames=frames)
                    break
                if replay.get('error'):raise RuntimeError(replay['error'])
                counts=replay['last_active_localization'].get('counts',{})
                if counts.get('processed',0)<5:raise RuntimeError('Insufficient rendered sensor input')
                footprints=replay.get('navigation',{}).get('footprint_messages',{})
                if footprints.get('local',0)<1:raise RuntimeError('No real costmap footprint was sent to MarkerDisplay')
                result.update(passed=True,frames=frames,replay_counts=counts,footprint_messages=footprints,
                              rviz_log_maps=text.count('Trying to create a map'))
                break
            if time.monotonic()>=next_probe:
                capture(directory);frames+=1;next_probe=time.monotonic()+2.
                # Preserve a frame while RViz is active, not the intentionally
                # empty right side during normal replay shutdown/cleanup.
                if frames==3:shutil.copyfile(directory/'browser-framebuffer.png',directory/'navigation-rendered.png')
                if a.terminate_rviz and not terminated:
                    config=str(directory/'localization/navigation.rviz').encode()
                    for proc in Path('/proc').glob('[0-9]*'):
                        try:
                            command=(proc/'cmdline').read_bytes().split(b'\0')
                            if proc.stat().st_uid==os.getuid() and command[0]==b'/opt/ros/foxy/lib/rviz2/rviz2' and config in command:
                                os.kill(int(proc.name),signal.SIGTERM);terminated=True;break
                        except OSError:pass
                    if not terminated:raise RuntimeError('Owned RViz process not found for failure test')
            time.sleep(.2)
        else:raise RuntimeError('Graphical replay completion timeout')
        # Replay completion must leave browser transport and terminal available.
        capture(directory);result['browser_connected_after_replay']=True
    except Exception as error:result['error']=type(error).__name__+': '+str(error)
    finally:
        subprocess.run(cli+['stop'],check=False,stdout=subprocess.DEVNULL)
        if directory is not None:
            def remaining():
                found=[]
                for proc in Path('/proc').glob('[0-9]*'):
                    try:
                        command=(proc/'cmdline').read_bytes().split(b'\0')
                        if proc.stat().st_uid==os.getuid() and any(str(directory/'localization').encode() in arg for arg in command):
                            found.append(int(proc.name))
                    except OSError:pass
                return found
            deadline=time.monotonic()+5
            while remaining() and time.monotonic()<deadline:time.sleep(.1)
            result['owned_children_after_stop']=remaining()
            if result['owned_children_after_stop']:
                result.update(passed=False,error='Replay cleanup left owned processes running')
            (directory/'graphical-acceptance.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));return int(not result['passed'])


if __name__=='__main__':raise SystemExit(main())
