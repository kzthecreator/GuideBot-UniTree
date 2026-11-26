"""Private native RViz desktop over noVNC; Mac needs only browser + SSH tunnel.

Dependencies are extracted Ubuntu packages under the current user's data dir.
No system installation, robot/audio startup, or public network listener is needed.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
DEPS=Path.home()/'.local/share/guidebot/deps/browser-rviz'
BASE=Path.home()/'.local/state/guidebot/navigation/browser-rviz'
PACKAGES=('xvfb','x11vnc','libvncserver1','fluxbox','libimlib2','novnc','python3-websockify')


def private_write(path,text):
    fd=os.open(str(path),os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(text)


def install():
    archives=DEPS/'debs';archives.mkdir(parents=True,exist_ok=True)
    root=DEPS/'root';root.mkdir(exist_ok=True)
    subprocess.run(['apt-get','download',*PACKAGES],cwd=archives,check=True)
    manifest=[]
    for archive in sorted(archives.glob('*.deb')):
        subprocess.run(['dpkg-deb','-x',str(archive),str(root)],check=True)
        manifest.append(dict(file=archive.name,sha256=hashlib.sha256(archive.read_bytes()).hexdigest()))
    (DEPS/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Private desktop dependencies ready: '+str(DEPS))


def worker_matches(pid,directory):
    try:
        path=Path('/proc')/str(pid)
        command=(path/'cmdline').read_bytes().split(b'\0')
        return path.stat().st_uid==os.getuid() and b'--worker' in command and str(directory).encode() in command
    except OSError:return False


def current():
    try:
        directory=(BASE/'current').resolve(strict=True)
        data=json.loads((directory/'status.json').read_text())
        if worker_matches(data['pid'],directory):return directory,data
    except (OSError,KeyError,ValueError):pass
    return None,None


def stop_process(process):
    if process.poll() is not None:return
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)


def stop_runner(directory):
    try:
        pid=int((directory/'rviz.pid').read_text())
        proc=Path('/proc')/str(pid)
        command=(proc/'cmdline').read_bytes()
        if proc.stat().st_uid!=os.getuid() or b'/navigation/rviz.py' not in command or str(directory/'localization').encode() not in command:return
        children=[]
        for path in Path('/proc').glob('[0-9]*/status'):
            try:
                fields=dict(line.split(':',1) for line in path.read_text().splitlines() if ':' in line)
                if int(fields['PPid'])==pid and path.stat().st_uid==os.getuid():children.append(int(path.parent.name))
            except (OSError,KeyError,ValueError):pass
        os.kill(pid,signal.SIGINT)
        deadline=time.monotonic()+12
        while proc.exists() and time.monotonic()<deadline:time.sleep(.1)
        if proc.exists():
            # Only processes captured as direct children of our own RViz runner.
            for child in children:
                try:os.kill(child,signal.SIGTERM)
                except ProcessLookupError:pass
            os.kill(pid,signal.SIGTERM)
    except (OSError,ValueError):pass


def serve(args):
    directory=args.directory
    root=DEPS/'root'
    env=dict(os.environ)
    # Do not propagate SSH display or SDK/ROS libraries into the private X server.
    for name in ('DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','PYTHONPATH','LD_LIBRARY_PATH','PYTHONHOME'):
        env.pop(name,None)
    env['LD_LIBRARY_PATH']=str(root/'usr/lib/aarch64-linux-gnu')
    display=None
    for number in range(200,250):
        if not Path('/tmp/.X11-unix/X'+str(number)).exists() and not Path('/tmp/.X'+str(number)+'-lock').exists():
            display=':'+str(number);break
    if display is None:raise RuntimeError('No free private X display')
    cookie=secrets.token_hex(16)
    authority=directory/'Xauthority'
    private_write(authority,'')
    subprocess.run(['xauth','-f',str(authority)],input=('add '+display+' . '+cookie+'\n').encode(),check=True,stdout=subprocess.DEVNULL)
    env.update(DISPLAY=display,XAUTHORITY=str(authority),LIBGL_ALWAYS_SOFTWARE='1',
               __GLX_VENDOR_LIBRARY_NAME='mesa',GUIDEBOT_RVIZ_BROWSER='1',
               LP_NUM_THREADS='2',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',
               PATH=str(Path(sys.executable).parent)+os.pathsep+env.get('PATH',''))
    password=secrets.token_urlsafe(8)[:8]
    private_write(directory/'vnc-password',password+'\n')
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0));vnc_port=reserve.getsockname()[1]
    url='http://127.0.0.1:%d/vnc.html?autoconnect=1&resize=scale#password=%s\n'%(args.port,password)
    private_write(directory/'url',url)
    (directory/'fluxbox-init').write_text('session.screen0.toolbar.visible: false\nsession.screen0.workspaces: 1\nsession.screen0.focusModel: ClickFocus\nsession.menuFile: '+str(directory/'menu')+'\nsession.styleFile: '+str(root/'usr/share/fluxbox/styles/Flux')+'\n')
    (directory/'menu').write_text('[begin] (GuideBot)\n[end]\n')
    processes=[];logs=[];stopping=False;failed=None
    def launch(name,command,environment=env):
        log=(directory/(name+'.log')).open('w');logs.append(log)
        p=subprocess.Popen(command,env=environment,cwd=REPO,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        processes.append((name,p));return p
    def shutdown(signum,frame):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    def check():
        for name,p in processes:
            # Closing the optional parameter window must not end the desktop.
            if name=='parameters':continue
            if p.poll() is not None:raise RuntimeError(name+' exited; inspect '+str(directory/(name+'.log')))
    try:
        launch('xvfb',[str(root/'usr/bin/Xvfb'),display,'-screen','0','1600x1000x24','-nolisten','tcp','-auth',str(authority),'+extension','GLX','+render','-noreset'])
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            check()
            if subprocess.run(['xdpyinfo'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
            time.sleep(.1)
        else:raise RuntimeError('Private X display startup timeout')
        launch('window-manager',[str(root/'usr/bin/fluxbox'),'-rc',str(directory/'fluxbox-init')])
        launch('vnc',[str(root/'usr/bin/x11vnc'),'-display',display,'-auth',str(authority),
                      '-localhost','-rfbport',str(vnc_port),'-passwdfile',str(directory/'vnc-password'),
                      '-forever','-shared','-noxdamage','-quiet','-defer','40'])
        web_env=dict(env)
        web_env['PYTHONPATH']=str(root/'usr/lib/python3/dist-packages')
        launch('web',[sys.executable,'-m','websockify','--web',str(root/'usr/share/novnc'),
                      '127.0.0.1:'+str(args.port),'127.0.0.1:'+str(vnc_port)],web_env)
        command=[sys.executable,str(REPO/'test/tools/navigation/rviz.py'),args.mode,
                 '--map-directory',str(args.map_directory),'--session-directory',str(directory/'localization'),
                 '--domain',str(180+os.getuid()%20)]
        if args.navigation:command+=['--navigation']
        if args.motion:command+=['--motion','--hardware',str(args.hardware)]
        if args.mode=='replay':command+=['--capture',str(args.capture)]
        if args.duration is not None:command+=['--duration',str(args.duration)]
        launcher='import os;from pathlib import Path;Path(%r).write_text(str(os.getpid()));os.execv(%r,%r)'%(str(directory/'rviz.pid'),sys.executable,command)
        # xterm provides the actual interactive Enter gate, also visible in the browser.
        launch('terminal',['xterm','-T','GuideBot Control - click here then Enter','-geometry','60x55+0+0',
                           '-fa','Monospace','-fs','10','-bg','#14202b','-fg','#e4edf7','-hold',
                           '-e',sys.executable,'-c',launcher])
        started=time.monotonic();rviz_ready=False;session_error=None;parameters=None;parameter_error=None
        while not stopping:
            check()
            request=directory/'parameters.request'
            if request.exists():
                request.unlink()
                if parameters is None or parameters.poll() is not None:
                    try:
                        from runtime.app.environment import ros_environment
                        parameter_env=ros_environment(domain=180+os.getuid()%20)
                        parameter_env.update(DISPLAY=display,XAUTHORITY=str(authority),LIBGL_ALWAYS_SOFTWARE='1',
                            __GLX_VENDOR_LIBRARY_NAME='mesa',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
                        # The full navigation graph needs more than Foxy's default 10 participants.
                        parameter_env['CYCLONEDDS_URI']='<CycloneDDS><Domain><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>40</MaxAutoParticipantIndex></Discovery></Domain></CycloneDDS>'
                        parameters=launch('parameters',[sys.executable,'/opt/ros/foxy/lib/rqt_reconfigure/rqt_reconfigure'],parameter_env)
                        parameter_error=None
                    except Exception as error:
                        parameter_error=type(error).__name__+': '+str(error)
                        print('Optional parameter window failed: '+parameter_error,flush=True)
            result=directory/'localization/result.json'
            session_state='active'
            if result.exists():
                try:
                    reason=json.loads(result.read_text()).get('error')
                    session_state='failed' if reason else 'completed'
                    if reason and reason!=session_error:
                        print('RViz session failed; keeping browser/terminal available: '+reason,flush=True)
                    session_error=reason
                except (OSError,ValueError):pass
            try:
                with (directory/'localization/rviz.log').open() as stream:
                    rviz_ready=rviz_ready or 'Trying to create a map' in stream.read(65536)
            except OSError:pass
            status=dict(pid=os.getpid(),display=display,port=args.port,vnc_port=vnc_port,
                        directory=str(directory),state='running',mode=args.mode,
                        elapsed_s=time.monotonic()-started,rviz_ready=rviz_ready and session_state=='active',
                        session_state=session_state,session_error=session_error,
                        parameters_open=parameters is not None and parameters.poll() is None,
                        parameter_error=parameter_error,
                        awaiting_enter=args.mode=='live' and not (directory/'localization/source.log').exists(),
                        navigation_enabled=args.navigation,motion_enabled=args.motion)
            (directory/'status.tmp').write_text(json.dumps(status,indent=2))
            (directory/'status.tmp').replace(directory/'status.json')
            time.sleep(.5)
    except Exception as error:
        failed=type(error).__name__+': '+str(error)
        print(failed,flush=True)
    finally:
        stop_runner(directory)
        for name,p in reversed(processes):stop_process(p)
        for log in logs:log.close()
        (directory/'status.json').write_text(json.dumps(dict(pid=os.getpid(),state='stopped',error=failed),indent=2))
    return int(failed is not None)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['setup','start','status','stop','parameters'])
    p.add_argument('--mode',choices=['live','replay'],default='live')
    p.add_argument('--map-directory',type=Path,default=Path.home()/'.local/state/guidebot/navigation/maps/lab-lv280ttd')
    p.add_argument('--capture',type=Path)
    p.add_argument('--duration',type=float)
    p.add_argument('--port',type=int,default=6080)
    p.add_argument('--navigation',action='store_true',help='Start Nav2 planning, avoidance and goal relay')
    p.add_argument('--motion',action='store_true',help='Enable calibrated hardware velocity sink, gated by Enter + arm + new goal')
    p.add_argument('--hardware',type=Path,default=REPO/'developer/config/navigation/hardware.yaml')
    p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--directory',type=Path,help=argparse.SUPPRESS)
    args=p.parse_args()
    if args.action=='setup':install();return 0
    BASE.mkdir(parents=True,exist_ok=True);BASE.chmod(0o700)
    if args.worker:return serve(args)
    with (BASE/'start.lock').open('a') as lease:
        fcntl.flock(lease,fcntl.LOCK_EX)
        active,data=current()
        if args.action=='status':
            print(json.dumps(data or dict(state='not_running'),indent=2));return 0
        if args.action=='stop':
            if active:
                os.kill(data['pid'],signal.SIGTERM)
                deadline=time.monotonic()+25
                while worker_matches(data['pid'],active) and time.monotonic()<deadline:time.sleep(.1)
                if worker_matches(data['pid'],active):raise RuntimeError('Desktop cleanup timeout; inspect logs')
            print('Browser RViz desktop stopped');return 0
        if args.action=='parameters':
            if active is None:p.error('Start the browser desktop first')
            if not Path('/opt/ros/foxy/lib/rqt_reconfigure/rqt_reconfigure').is_file():
                p.error('The existing ROS environment has no rqt_reconfigure executable')
            private_write(active/'parameters.request','')
            print('Parameter window requested in the browser desktop; no parameters were changed.');return 0
        if active:
            if bool(data.get('navigation_enabled'))!=args.navigation or bool(data.get('motion_enabled'))!=args.motion:
                p.error('Existing desktop uses a different mode; stop it before changing navigation/motion settings')
            print('Already running: '+str(active));print('Browser URL is in '+str(active/'url'));return 0
        root=DEPS/'root'
        for name in ('Xvfb','x11vnc','fluxbox'):
            if not (root/'usr/bin'/name).exists():p.error('Run setup first; missing '+name)
        if not 1024<=args.port<=65535:p.error('port must be 1024..65535')
        if args.motion:
            if not args.navigation or args.mode!='live':p.error('--motion requires live --navigation')
            from GuideBot.navigation.velocity import hardware_profile
            import yaml
            try:hardware_profile(yaml.safe_load(args.hardware.expanduser().read_text()))
            except (ValueError,OSError,TypeError) as error:p.error(str(error))
            args.hardware=args.hardware.expanduser().resolve()
        args.map_directory=args.map_directory.expanduser().resolve()
        for name in ('map.yaml','map.pgm','report.json'):
            if not (args.map_directory/name).is_file():p.error('Missing map file: '+name)
        if args.mode=='replay':
            if args.capture is None:p.error('replay needs --capture')
            args.capture=args.capture.expanduser().resolve()
            for name in ('samples.jsonl','samples.cdr'):
                if not (args.capture/name).is_file():p.error('Missing capture file: '+name)
        if args.duration is not None and not 0<args.duration<=86400:p.error('invalid duration')
        directory=Path(tempfile.mkdtemp(prefix='desktop-',dir=BASE));directory.chmod(0o700)
        command=[sys.executable,str(Path(__file__).resolve()),'start','--worker','--directory',str(directory),
                 '--mode',args.mode,'--map-directory',str(args.map_directory),'--port',str(args.port)]
        if args.navigation:command+=['--navigation']
        if args.motion:command+=['--motion','--hardware',str(args.hardware)]
        if args.capture:command+=['--capture',str(args.capture)]
        if args.duration is not None:command+=['--duration',str(args.duration)]
        with (directory/'desktop.log').open('w') as log:
            worker=subprocess.Popen(command,cwd=REPO,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            if worker.poll() is not None:raise RuntimeError('Desktop startup failed: '+str(directory/'desktop.log'))
            if (directory/'status.json').exists():
                try:
                    with urllib.request.urlopen('http://127.0.0.1:%d/vnc.html'%args.port,timeout=1) as response:
                        status=json.loads((directory/'status.json').read_text())
                        if response.status==200 and (status.get('rviz_ready') or status.get('session_state')=='failed'):break
                except OSError:pass
            time.sleep(.2)
        else:
            worker.terminate();worker.wait(timeout=20);raise RuntimeError('Desktop startup timeout')
        link=BASE/'current.tmp'
        if link.is_symlink():link.unlink()
        link.symlink_to(directory);link.replace(BASE/'current')
        print('Browser RViz desktop ready: '+str(directory))
        print('Connect Mac SSH tunnel to 127.0.0.1:'+str(args.port))
        print('Browser URL (includes session password) saved in '+str(BASE/'current/url'))
        return 0


if __name__=='__main__':raise SystemExit(main())
