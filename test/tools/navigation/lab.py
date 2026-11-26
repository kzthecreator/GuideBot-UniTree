"""Read-only lab sensor visualization/recording. Never commands the robot.

live: Enter starts existing sensor subscriptions; Ctrl+C stops and closes bags.
probe: bounded automated reception check, without audio, motor or mode commands.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))


def stop(process):
    if process is None or process.poll() is not None:return
    process.send_signal(signal.SIGINT)
    try:process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('live','probe','replay','info','source','replay-source','ros'))
    parser.add_argument('--interface',default='eth0')
    parser.add_argument('--capture',type=Path)
    parser.add_argument('--duration',type=float)
    parser.add_argument('--record',action='store_true')
    parser.add_argument('--rviz',action='store_true')
    parser.add_argument('--web',action='store_true')
    parser.add_argument('--web-port',type=int,default=8765)
    parser.add_argument('--directory',type=Path)
    parser.add_argument('--endpoint')
    args=parser.parse_args()
    if args.duration is not None and not 0 < args.duration <= 86400:parser.error('duration must be 0..86400 seconds')
    if args.mode in ('replay','replay-source','info') and args.capture is None:
        parser.error('this mode requires --capture CAPTURE_DIRECTORY')
    if args.mode in ('replay','replay-source','info'):
        args.capture=args.capture.expanduser().resolve()
        required=('result.json',) if args.mode=='info' else ('samples.cdr','samples.jsonl')
        for name in required:
            if not (args.capture/name).is_file():
                parser.error('Capture file not found: '+str(args.capture/name))
    if args.mode=='info':
        print((args.capture/'result.json').read_text());return 0
    if args.mode=='replay-source':
        from test.tools.navigation.replay import run
        run(args.capture,args.endpoint,args.directory,args.duration);return 0
    if args.mode=='source':
        from GuideBot.robot.sensors.runtime import run
        run(args.endpoint,args.interface,args.directory,args.duration);return 0
    if args.mode=='ros':
        from runtime.ros2.adapters.sensors import run
        run(args.endpoint,args.directory);return 0
    from runtime.app.environment import sdk_environment,ros_environment
    if args.rviz and not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        parser.error('--rviz needs a graphical desktop terminal; omit it for recording over SSH')
    if args.mode=='live':
        try:input('只读雷达采集，不控制机器人。按 Enter 开始，Ctrl+C结束：')
        except EOFError:raise RuntimeError('Interactive Enter required for live capture') from None
    base=Path.home()/'.local/state/guidebot/navigation';base.mkdir(parents=True,exist_ok=True)
    lease=(base/'capture.lock').open('a')
    try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('Another sensor capture/replay is already running for this account') from None
    root=args.directory or Path(tempfile.mkdtemp(prefix='replay-' if args.mode=='replay' else 'lab-',dir=base))
    if args.directory:
        root.mkdir(parents=True,exist_ok=False)
    root.chmod(0o700)
    # A short private socket path avoids AF_UNIX's 108-byte path limit.
    socket_root=Path(tempfile.mkdtemp(prefix='guidebot-sensors-'))
    socket_root.chmod(0o700);endpoint=socket_root/'sensors.sock'
    if args.record:(root/'record.enabled').touch()
    rosenv=ros_environment(domain=140+os.getuid()%40);rosenv['ROS_LOCALHOST_ONLY']='1'
    processes=[];logs=[];source=None;bag=None;failed=None;web=None;web_thread=None
    print('采集目录：'+str(root),flush=True)
    def launch(command,env,name):
        log=(root/(name+'.log')).open('w');logs.append(log)
        process=subprocess.Popen(command,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        processes.append(process);return process
    try:
        if args.web:
            from test.tools.navigation.web_preview import start
            web,web_thread=start(root,args.web_port)
            print('点云预览：http://127.0.0.1:'+str(web.server_port),flush=True)
        bridge=launch([sys.executable,str(Path(__file__).resolve()),'ros','--directory',str(root),
                       '--endpoint',str(endpoint)],rosenv,'ros')
        deadline=time.monotonic()+12
        while not (root/'ros.ready').exists():
            if bridge.poll() is not None:raise RuntimeError('ROS bridge startup failed; see ros.log')
            if time.monotonic()>deadline:raise RuntimeError('ROS bridge startup timeout')
            time.sleep(.05)
        if args.record:
            bag=launch([sys.executable,'/opt/ros/foxy/bin/ros2','bag','record','-o',str(root/'bag'),
                '--qos-profile-overrides-path',str(REPO/'developer/config/navigation/record_qos.yaml'),
                '/guidebot/sensors/cloud','/guidebot/sensors/imu','/guidebot/sensors/odom'],rosenv,'bag')
            deadline=time.monotonic()+8
            while not list((root/'bag').glob('*.db3')):
                if bag.poll() is not None:raise RuntimeError('Bag startup failed; see bag.log')
                if time.monotonic()>deadline:raise RuntimeError('Bag startup timeout')
                time.sleep(.05)
        if args.rviz:
            launch([str(Path('/opt/ros/foxy/lib/rviz2/rviz2')),'-d',str(REPO/'developer/config/navigation/lab.rviz')],rosenv,'rviz')
        command=[sys.executable,str(Path(__file__).resolve()),'replay-source' if args.mode=='replay' else 'source','--directory',str(root),
                 '--endpoint',str(endpoint),'--interface',args.interface]
        if args.mode=='replay':command+=['--capture',str(args.capture)]
        duration=args.duration or (8 if args.mode=='probe' else None)
        if duration:command+=['--duration',str(duration)]
        source=launch(command,sdk_environment(),'source')
        last=0
        while source.poll() is None:
            if bridge.poll() is not None:raise RuntimeError('ROS bridge exited; see ros.log')
            if bag is not None and bag.poll() is not None:raise RuntimeError('Bag recorder exited; see bag.log')
            now=time.monotonic()
            if now-last>3:
                last=now
                status=root/'source-status.json'
                if status.exists():
                    try:
                        data=json.loads(status.read_text())
                        print('已接收 '+', '.join(k+'='+str(v['count']) for k,v in data['sources'].items()),flush=True)
                    except json.JSONDecodeError:pass
            time.sleep(.1)
        if source.returncode:raise RuntimeError('Sensor source failed; see source.log')
    except KeyboardInterrupt:pass
    except Exception as error:
        failed=str(error)
    finally:
        stop(source)
        # Let ROS publish the final received samples before closing rosbag.
        drain_until=time.monotonic()+2
        while source is not None and time.monotonic()<drain_until:
            try:
                counts=json.loads((root/'source-status.json').read_text())['sources']
                bridge_state=json.loads((root/'bridge-status.json').read_text())
                if all(bridge_state['published'].get(k,0)+bridge_state['overwritten'].get(k,0)>=v['count']
                       for k,v in counts.items()):break
            except (OSError,KeyError,json.JSONDecodeError):break
            time.sleep(.03)
        # Close the recorder before the publisher so rosbag writes metadata.
        for process in reversed(processes):
            if process is not source:stop(process)
        for log in logs:log.close()
        if web:
            web.shutdown();web.server_close();web_thread.join(timeout=2)
        try:endpoint.unlink()
        except FileNotFoundError:pass
        socket_root.rmdir()
    result=dict(directory=str(root),ros_domain=int(rosenv['ROS_DOMAIN_ID']),motion_commands=False,audio_started=False,error=failed)
    for name in ('source-status','bridge-status'):
        path=root/(name+'.json')
        if path.exists():result[name]=json.loads(path.read_text())
    received=result.get('source-status',{}).get('sources',{})
    published=result.get('bridge-status',{}).get('published',{})
    result['all_streams_received']=all(received.get(k,{}).get('count',0)>0 and published.get(k,0)>0
                                       for k in ('cloud','imu','odom'))
    if result.get('bridge-status', {}).get('errors') and failed is None:
        result['error']='ROS bridge reported sensor errors; inspect bridge-status.json'
    if not result['all_streams_received'] and failed is None:
        result['error']='Not all cloud/IMU/odometry streams are available; inspect capture status'
    (root/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return int(result['error'] is not None)


if __name__=='__main__':raise SystemExit(main())
