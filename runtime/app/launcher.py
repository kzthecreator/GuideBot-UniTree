"""Python deployment bootstrap. All conversation activation is requested through ROS."""
import argparse
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import uuid

from GuideBot.compat import boolean_option
from runtime.app.local_runtime import LocalRuntime
from runtime.app.environment import sdk_environment
from runtime.ipc.channel import call

REPO = Path(__file__).resolve().parents[2]




def parser():
    result = argparse.ArgumentParser(description='GuideBot: ROS2-managed voice and gesture system. Enter authorizes hardware.')
    boolean_option(result, 'diagnose-audio', default=True)
    result.add_argument('--vad-energy', type=int, choices=range(5001), default=4999, metavar='0..5000')
    result.add_argument('--sync-knowledge', dest='sync_knowledge_before_start', action='store_true')
    result.add_argument('--service', choices=('conversation','tour'), help='Choose a business service; omitted opens a menu')
    result.add_argument('--voice')
    boolean_option(result, 'timestamps', default=None)
    result.add_argument('--gestures', action='store_true', help='Enable simulated gesture planning')
    result.add_argument('--gesture-backend', choices=('simulated','unitree'))
    return result


def choose_service():
    while True:
        try:
            choice = input('选择服务：1 语音交互 / 2 导览（Ctrl+C取消）：').strip()
        except EOFError:
            raise RuntimeError('Interactive service selection required; use --service') from None
        if choice in {'1','conversation'}: return 'conversation'
        if choice in {'2','tour'}: return 'tour'
        print('请输入 1 或 2。', flush=True)


def tour_command(line):
    parts = line.split()
    if len(parts) == 1 and parts[0] in {'status','pause','resume'}:
        return dict(command=parts[0])
    if len(parts) in {2,3} and parts[0] == 'arrived':
        fields = dict(point_id=parts[1])
        if len(parts) == 3: fields['task_id'] = parts[2]
        return dict(command='arrived', fields=fields)
    raise ValueError('Use status, pause, resume, or arrived POINT_ID [TASK_ID]')


def session_control(root, session_id, command, mode, timeout=120):
    deadline = time.monotonic()+timeout
    while True:
        result = call(root/'ipc/ros.sock', dict(op='session', session_id=session_id,
                      generation=1, command=command, mode=mode), max(.1, deadline-time.monotonic()))
        if result['accepted']:
            return result
        if (command == 'stop' and result['reason'] == 'Session transition in progress'
                and time.monotonic() < deadline):
            time.sleep(.05)
            continue
        raise RuntimeError('ROS session rejected: '+result['reason'])


def stop_worker(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=65)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main(argv=None):
    args = parser().parse_args(argv)
    if args.service is None:
        args.service = choose_service()
    from runtime.app.services import validate_options
    validate_options(vars(args))
    if args.service == 'tour':
        from GuideBot.tour.assets import load_bundle
        load_bundle()  # Check offline assets before starting ROS or asking for activation.
    # Import-only bootstrap: no SDK initialization, models, recording or playback.
    from GuideBot.conversation.knowledge import load_secret
    load_secret()
    gestures = args.gestures or args.gesture_backend is not None
    if gestures and args.timestamps is False:
        raise ValueError('Gesture text alignment requires timestamps; remove --no-timestamps')
    if gestures:
        from GuideBot.gesture.provider import validate_configuration
        validate_configuration()
    mode = 'robot' if args.gesture_backend == 'unitree' else 'simulation' if gestures else 'voice'
    runtime = LocalRuntime(timing=os.environ.get('GUIDEBOT_GESTURE_TIMING_MODE', 'immediate'))
    session_id = uuid.uuid4().hex
    child = None
    activated = False
    from runtime.app.planner_server import PlannerServer
    planner_server = PlannerServer(runtime.root) if gestures else None
    try:
        if planner_server:
            planner_server.start()
        runtime.start()
        (runtime.root/'worker.json').write_text(json.dumps(dict(options=vars(args), session_id=session_id)))
        (runtime.root/'worker.json').chmod(0o600)
        (runtime.root/'session.json').write_text(json.dumps(dict(session_id=session_id, generation=1,
            mode=mode, state='standby', voice_directory=str(runtime.root/'session'),
            ros_log=str(runtime.root/'ros.log'))), encoding='utf-8')
        child = subprocess.Popen([sys.executable, '-m', 'runtime.app.worker', '--root', str(runtime.root)],
                                 cwd=REPO, env=dict(sdk_environment(), GUIDEBOT_GESTURE_TIMING_MODE=runtime.timing))
        deadline = time.monotonic()+25
        while not (runtime.root/'worker.ready').exists():
            if child.poll() is not None:
                raise RuntimeError('Host worker preparation failed')
            if time.monotonic() > deadline:
                raise TimeoutError('Host worker preparation timed out')
            time.sleep(.1)
        print(f'ROS2 system ready (standby). Session logs: {runtime.root}/session', flush=True)
        print('StepFun; LocalVQE v1.2 -> AGC2; gate disabled. Mode: '+mode, flush=True)
        try:
            input('Press Enter to start; Ctrl+C to cancel: ')
        except EOFError:
            raise RuntimeError('Interactive Enter required; hardware was not started') from None
        call(runtime.root/'ipc/resources.sock', dict(op='authorize', session_id=session_id, generation=1))
        session_control(runtime.root, session_id, 'start', mode)
        activated = True
        index = json.loads((runtime.root/'session.json').read_text())
        index['state'] = 'active'
        (runtime.root/'session.json').write_text(json.dumps(index), encoding='utf-8')
        print('ROS2 session active. Press Enter to stop.', flush=True)
        if args.service == 'tour':
            print('Tour commands: status | arrived POINT_ID | pause | resume. Empty Enter stops.', flush=True)
        while True:
            if child.poll() is not None:
                raise RuntimeError('Host worker exited')
            health = session_control(runtime.root, session_id, 'health', mode, 5)
            if health['state'] != 'active':
                raise RuntimeError('ROS session ended: '+health['state'])
            readable, _, _ = select.select([sys.stdin], [], [], .2)
            if readable:
                line = sys.stdin.readline().strip()
                if not line:
                    break
                if args.service == 'tour':
                    try:
                        request = tour_command(line)
                        value = call(runtime.root/'ipc/resources.sock', dict(op='tour',
                            session_id=session_id, generation=1, **request), 5)
                        print(json.dumps(value, ensure_ascii=False), flush=True)
                    except (ValueError, RuntimeError) as error:
                        print('Tour command rejected: '+str(error), flush=True)
                else:
                    print('Press an empty Enter to stop.', flush=True)
    finally:
        original_error = sys.exc_info()[1]
        try:
            if activated:
                try:
                    session_control(runtime.root, session_id, 'stop', mode)
                except Exception as cleanup_error:
                    if original_error is None:
                        raise
                    print('Session cleanup also failed: '+str(cleanup_error), flush=True)
        finally:
            # Resource watchdog and cleanup remain available if ROS is already gone.
            try:
                stop_worker(child)
            finally:
                try:
                    runtime.stop()
                finally:
                    if planner_server:
                        planner_server.stop()
        if (runtime.root/'session.json').exists():
            index = json.loads((runtime.root/'session.json').read_text())
            index['state'] = 'closed'
            (runtime.root/'session.json').write_text(json.dumps(index), encoding='utf-8')
        print(f'Session stopped. Logs: {runtime.root}', flush=True)
    result = runtime.root/'session/result.json'
    if result.exists() and json.loads(result.read_text()).get('errors'):
        raise RuntimeError('Voice session reported errors; inspect '+str(result))
    return 0
