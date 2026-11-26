"""Reuse upstream RViz + stock map_server/AMCL/pointcloud_to_laserscan, read-only.

SDK receives native sensors in its own process; ROS runs in a clean environment.
No simulator, learned gait, Nav2 controller or velocity bridge is started.
"""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import secrets
import select
import subprocess
import sys
import tempfile
import time

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))


def read_status(path):
    try:return json.loads(path.read_text())
    except (OSError,json.JSONDecodeError):return {}


def main():
    def terminated(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminated)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['live','replay'])
    parser.add_argument('--map-directory',required=True,type=Path)
    parser.add_argument('--capture',type=Path)
    parser.add_argument('--session-directory',type=Path,help='New private directory for this run')
    parser.add_argument('--headless',action='store_true',help='Run stock ROS localization without a GUI, for replay checks')
    parser.add_argument('--duration',type=float)
    parser.add_argument('--domain',type=int,default=140+os.getuid()%40,choices=range(233))
    parser.add_argument('--initial-x',type=float,default=0.)
    parser.add_argument('--initial-y',type=float,default=0.)
    parser.add_argument('--initial-yaw-deg',type=float,default=0.)
    parser.add_argument('--interface',default='eth0')
    parser.add_argument('--navigation',action='store_true',help='Start Nav2 planner/controller and RViz goal relay')
    parser.add_argument('--motion',action='store_true',help='Enable measured-geometry SDK bridge; still requires Enter, arm and a new goal')
    parser.add_argument('--hardware',type=Path,default=REPO/'developer/config/navigation/hardware.yaml')
    args=parser.parse_args()
    if args.motion and (not args.navigation or args.mode!='live'):
        parser.error('--motion requires live --navigation; replay can never move hardware')
    radius=.70;profile=None
    if args.motion:
        import yaml
        from GuideBot.navigation.velocity import hardware_profile,lidar_radius
        try:
            profile=hardware_profile(yaml.safe_load(args.hardware.expanduser().read_text()))
            radius=lidar_radius(profile)
        except (ValueError,OSError,TypeError) as error:parser.error(str(error))
    args.map_directory=args.map_directory.expanduser().resolve()
    for name in ('map.yaml','map.pgm','report.json'):
        if not (args.map_directory/name).is_file():parser.error('Missing map file: '+name)
    if not args.headless and not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        parser.error('RViz needs a graphical desktop or SSH X11 forwarding; use --headless for automated replay')
    if args.duration is not None and not 0<args.duration<=86400:parser.error('duration must be 0..86400')
    if not all(math.isfinite(x) for x in (args.initial_x,args.initial_y,args.initial_yaw_deg)):
        parser.error('Initial pose must be finite')
    if args.mode=='replay':
        if args.capture is None:parser.error('replay requires --capture')
        args.capture=args.capture.expanduser().resolve()
        for name in ('samples.cdr','samples.jsonl'):
            if not (args.capture/name).is_file():parser.error('Missing capture file: '+name)
    from runtime.app.environment import ros_environment,sdk_environment
    from test.tools.navigation.rviz_config import generate
    from test.tools.navigation.lab import stop
    base=Path.home()/'.local/state/guidebot/navigation';base.mkdir(parents=True,exist_ok=True)
    with (base/'capture.lock').open('a') as lease:
        try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another capture/localization is running') from None
        if args.session_directory:
            directory=args.session_directory.expanduser().resolve()
            directory.mkdir(mode=0o700,parents=True,exist_ok=False)
        else:
            directory=Path(tempfile.mkdtemp(prefix='rviz-',dir=base))
        directory.chmod(0o700)
        params,rviz=generate(directory,args.map_directory,
            (args.initial_x,args.initial_y,math.radians(args.initial_yaw_deg)),navigation=args.navigation)
        navparams=None
        if args.navigation:
            from test.tools.navigation.nav_config import generate as nav_generate
            navparams=nav_generate(directory,radius)
        socket_dir=Path(tempfile.mkdtemp(prefix='gb-rviz-'));socket_dir.chmod(0o700)
        endpoint=socket_dir/'sensors.sock'
        env=ros_environment(domain=args.domain);env['OPENBLAS_NUM_THREADS']='1'
        if args.navigation:
            env['GUIDEBOT_NAVIGATION']='1'
            # Foxy's localhost Cyclone default only scans participant indices 0..9;
            # localization + Nav2 + RViz legitimately needs more than ten processes.
            env['CYCLONEDDS_URI']='<CycloneDDS><Domain><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>40</MaxAutoParticipantIndex></Discovery></Domain></CycloneDDS>'
        env['ROS_LOG_DIR']=str(directory/'ros-logs')
        processes=[];logs=[];source=None;failed=None;interrupted=False;active_status={}
        def launch(name,command,environment=env):
            log=(directory/(name+'.log')).open('w');logs.append(log)
            process=subprocess.Popen(command,cwd=REPO,env=environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            processes.append((name,process));return process
        def healthy():
            for name,process in processes:
                if process is not source and process.poll() is not None:
                    raise RuntimeError(name+' exited; inspect '+str(directory/(name+'.log')))
        def wait_ready(predicate,timeout,label):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                healthy()
                if predicate():return
                time.sleep(.1)
            raise RuntimeError(label+' timeout; inspect logs at '+str(directory))
        try:
            print('会话目录：'+str(directory),flush=True)
            launch('sensors',[sys.executable,str(REPO/'test/tools/navigation/lab.py'),'ros',
                             '--directory',str(directory),'--endpoint',str(endpoint)])
            wait_ready(lambda:(directory/'ros.ready').exists(),12,'Sensor bridge')
            launch('frontend',[sys.executable,str(REPO/'test/tools/navigation/ros_lidar.py'),'--directory',str(directory)])
            def native(name,package,executable,extra=()):
                return launch(name,[str(Path('/opt/ros/foxy/lib')/package/executable),'--ros-args',
                                    '--params-file',str(params),'-r','__node:='+name,*extra])
            native('map_server','nav2_map_server','map_server')
            native('amcl','nav2_amcl','amcl')
            native('pointcloud_to_laserscan','pointcloud_to_laserscan','pointcloud_to_laserscan_node',
                   ['-r','cloud_in:=/guidebot/navigation/leveled_cloud','-r','scan:=/scan'])
            native('lifecycle_manager_localization','nav2_lifecycle_manager','lifecycle_manager')
            def ready():
                status=read_status(directory/'localization-status.json')
                return status.get('counts',{}).get('maps',0)>0 and all(status.get('lifecycles',{}).get(n)=='active' for n in ('map_server','amcl'))
            wait_ready(ready,30,'Map server / AMCL activation')
            if args.navigation:
                for name,package in (('planner_server','nav2_planner'),('controller_server','nav2_controller'),
                                     ('bt_navigator','nav2_bt_navigator'),('lifecycle_manager_navigation','nav2_lifecycle_manager')):
                    extra=['-r','cmd_vel:=/guidebot/navigation/nav2_cmd_vel'] if name=='controller_server' else []
                    launch(name,[str(Path('/opt/ros/foxy/lib')/package/('lifecycle_manager' if name.startswith('lifecycle_manager') else name)),
                                 '--ros-args','--params-file',str(navparams),'-r','__node:='+name,*extra])
            if not args.headless:
                launch('rviz',[str(Path('/opt/ros/foxy/lib/rviz2/rviz2')),'-d',str(rviz)])
                if args.mode=='replay':
                    def rendered():
                        try:return 'Trying to create a map' in (directory/'rviz.log').read_text()
                        except OSError:return False
                    wait_ready(rendered,25,'RViz map rendering before replay')
            print('RViz / AMCL 已启动；'+('Nav2 路径规划、点云避障已接入。' if args.navigation else '仅定位，无运动控制。'),flush=True)
            if args.navigation:
                print('真机速度出口：'+('已配置，仍需 arm 后选择新目标。' if args.motion else '关闭；可选目标验证规划，但机器人不会移动。'),flush=True)
            if args.mode=='live':
                print('请在采图起点附近保持初始朝向，启动后也可用 RViz 的 2D Pose Estimate 指定位置。',flush=True)
                try:input('按 Enter 开始接收实时雷达，Ctrl+C 结束：')
                except EOFError:raise RuntimeError('Interactive Enter required for live sensors') from None
            command=[sys.executable,str(REPO/'test/tools/navigation/lab.py'),
                     'source' if args.mode=='live' else 'replay-source','--directory',str(directory),
                     '--endpoint',str(endpoint),'--interface',args.interface]
            if args.mode=='replay':command+=['--capture',str(args.capture)]
            if args.duration:command+=['--duration',str(args.duration)]
            source=launch('source',command,sdk_environment())
            if args.navigation:
                token_file=socket_dir/'token';token_file.write_text(secrets.token_hex(24));token_file.chmod(0o600)
                velocity_endpoint=socket_dir/'velocity.sock'
                if args.motion:
                    # Pin the exact validated values for this run; never reread an edited profile.
                    import yaml
                    hardware=directory/'hardware.yaml';hardware.write_text(yaml.safe_dump(profile))
                    launch('velocity',[sys.executable,'-m','GuideBot.robot.navigation',
                        '--endpoint',str(velocity_endpoint),'--directory',str(directory),'--hardware',str(hardware),
                        '--token-file',str(token_file),'--interface',args.interface],sdk_environment())
                    wait_ready(lambda:(directory/'velocity.ready').exists(),15,'SDK velocity bridge')
                launch('navigation',[sys.executable,'-m','runtime.ros2.adapters.navigation_control',
                    '--directory',str(directory),'--endpoint',str(velocity_endpoint),'--token-file',str(token_file),
                    '--radius',str(radius),*(['--motion'] if args.motion else [])])
                wait_ready(lambda:(directory/'navigation.ready').exists(),12,'Navigation goal/velocity guard')
                print('终端命令：arm 启用下一次目标；stop 停止并取消目标；status 查看状态；Enter 结束。',flush=True)
            last=0.;started=time.monotonic()
            while source.poll() is None:
                healthy()
                if args.navigation and args.mode=='live' and select.select([sys.stdin],[],[],0)[0]:
                    line=sys.stdin.readline()
                    if not line or not line.strip():break
                    action=line.strip().lower()
                    if action in ('arm','stop','disarm'):
                        tmp=directory/'navigation-command.tmp'
                        tmp.write_text(json.dumps(dict(action=action,at=time.monotonic())))
                        tmp.replace(directory/'navigation-command.json')
                    elif action=='status':print(json.dumps(read_status(directory/'navigation-status.json'),ensure_ascii=False),flush=True)
                    else:print('可用命令：arm | stop | status | Enter 结束',flush=True)
                status=read_status(directory/'localization-status.json')
                active_status=status
                if status.get('velocity_publishers'):raise RuntimeError('Unexpected velocity publisher in isolated ROS graph')
                if status.get('lost'):raise RuntimeError('LiDAR odometry lost: '+status.get('reason',''))
                if time.monotonic()-started>8 and (status.get('cloud_age_s') is None or status['cloud_age_s']>5):
                    raise RuntimeError('No fresh LiDAR clouds')
                if time.monotonic()-started>8 and (status.get('counts',{}).get('processed',0)==0 or (status.get('odom_age_s') or 0)>3):
                    raise RuntimeError('No fresh measured LiDAR odometry')
                if time.monotonic()-last>3:
                    counts=status.get('counts',{});print('cloud=%s odom=%s scan=%s amcl=%s %s'%(
                        counts.get('raw_clouds',0),counts.get('processed',0),counts.get('scans',0),counts.get('amcl_poses',0),status.get('reason','')),flush=True);last=time.monotonic()
                    if args.navigation:
                        navstate=read_status(directory/'navigation-status.json')
                        print('导航：ready=%s armed=%s goal=%s %s'%(navstate.get('ready'),navstate.get('armed'),navstate.get('goal_state'),navstate.get('reason')),flush=True)
                time.sleep(.1)
            if source.poll() is not None and source.returncode:raise RuntimeError('Sensor source failed; inspect source.log')
            # Let the bridge and ROS scan/AMCL chain drain their last messages.
            time.sleep(1)
            status=read_status(directory/'localization-status.json')
            active_status=status
            if status.get('counts',{}).get('amcl_poses',0)==0:raise RuntimeError('AMCL produced no localization')
            if not status.get('map_to_lidar_fresh',False):raise RuntimeError('AMCL map-to-lidar TF missing/stale')
        except KeyboardInterrupt:interrupted=True
        except Exception as error:failed=type(error).__name__+': '+str(error)
        finally:
            # A second desktop-stop signal must not interrupt child cleanup.
            signal.signal(signal.SIGINT,signal.SIG_IGN)
            signal.signal(signal.SIGTERM,signal.SIG_IGN)
            stop(source)
            for name,process in reversed(processes):
                if process is not source:stop(process)
            for log in logs:log.close()
            if endpoint.exists():endpoint.unlink()
            for child in socket_dir.iterdir():child.unlink()
            socket_dir.rmdir()
            result=dict(directory=str(directory),mode=args.mode,error=failed,interrupted=interrupted,
                        ros_domain=int(env['ROS_DOMAIN_ID']),motion_commands=args.motion,audio_started=False,
                        navigation_enabled=args.navigation,navigation_ready=False,live_verified=False,
                        navigation=read_status(directory/'navigation-status.json'),
                        velocity=read_status(directory/'velocity-status.json'),
                        upstream_sha='ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff',
                        backend=['nav2_map_server','nav2_amcl','pointcloud_to_laserscan'],
                        last_active_localization=active_status,
                        localization=read_status(directory/'localization-status.json'))
            (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
        return int(failed is not None)


if __name__=='__main__':raise SystemExit(main())
