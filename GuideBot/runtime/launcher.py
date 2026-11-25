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
from .local_runtime import LocalRuntime
from .environment import sdk_environment
from .ipc import call

REPO = Path(__file__).resolve().parents[2]




def parser():
    result = argparse.ArgumentParser(description='GuideBot: ROS2-managed voice and gesture system. Enter authorizes hardware.')
    boolean_option(result, 'diagnose-audio', default=True)
    result.add_argument('--vad-energy', type=int, choices=range(5001), default=4999, metavar='0..5000')
    result.add_argument('--sync-knowledge', dest='sync_knowledge_before_start', action='store_true')
    result.add_argument('--voice')
    boolean_option(result, 'timestamps', default=False)
    result.add_argument('--gestures', action='store_true', help='Enable simulated gesture planning')
    result.add_argument('--gesture-backend', choices=('simulated','unitree'))
    return result


def session_control(root, session_id, command, mode, timeout=120):
    result = call(root/'ipc/ros.sock', dict(op='session', session_id=session_id,
                  generation=1, command=command, mode=mode), timeout)
    if not result['accepted']:
        raise RuntimeError('ROS session rejected: '+result['reason'])
    return result


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
    # Import-only bootstrap: no SDK initialization, models, recording or playback.
    from GuideBot.conversation.knowledge import load_secret
    load_secret()
    gestures = args.gestures or args.gesture_backend is not None
    if gestures and not os.environ.get('DEEPSEEK_API_KEY', '').strip():
        raise ValueError('DEEPSEEK_API_KEY is required for gestures')
    mode = 'robot' if args.gesture_backend == 'unitree' else 'simulation' if gestures else 'voice'
    runtime = LocalRuntime(timing=os.environ.get('GUIDEBOT_GESTURE_TIMING_MODE', 'immediate'))
    session_id = uuid.uuid4().hex
    child = None
    activated = False
    try:
        runtime.start()
        (runtime.root/'worker.json').write_text(json.dumps(dict(options=vars(args), session_id=session_id)))
        (runtime.root/'worker.json').chmod(0o600)
        (runtime.root/'session.json').write_text(json.dumps(dict(session_id=session_id, generation=1,
            mode=mode, state='standby', voice_directory=str(runtime.root/'session'),
            ros_log=str(runtime.root/'ros.log'))), encoding='utf-8')
        child = subprocess.Popen([sys.executable, '-m', 'GuideBot.runtime.worker', '--root', str(runtime.root)],
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
        while True:
            if child.poll() is not None:
                raise RuntimeError('Host worker exited')
            health = session_control(runtime.root, session_id, 'health', mode, 5)
            if health['state'] != 'active':
                raise RuntimeError('ROS session ended: '+health['state'])
            readable, _, _ = select.select([sys.stdin], [], [], .2)
            if readable:
                sys.stdin.readline()
                break
    finally:
        try:
            if activated:
                session_control(runtime.root, session_id, 'stop', mode)
        finally:
            # Resource watchdog and cleanup remain available if ROS is already gone.
            try:
                stop_worker(child)
            finally:
                runtime.stop()
        if (runtime.root/'session.json').exists():
            index = json.loads((runtime.root/'session.json').read_text())
            index['state'] = 'closed'
            (runtime.root/'session.json').write_text(json.dumps(index), encoding='utf-8')
        print(f'Session stopped. Logs: {runtime.root}', flush=True)
    result = runtime.root/'session/result.json'
    if result.exists() and json.loads(result.read_text()).get('errors'):
        raise RuntimeError('Voice session reported errors; inspect '+str(result))
    return 0
