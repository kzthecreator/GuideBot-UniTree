"""ROS2 acceptance entry. Sidecar is idle until the normal Enter prompt."""
import os
from pathlib import Path
import subprocess
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.ros2.sidecar import Sidecar


def host_environment():
    """Prepare the SDK worker without requiring a shell wrapper."""
    environment = dict(os.environ)
    sdk = environment.setdefault('UNITREE_SDK_PATH', '/opt/unitree_robotics/unitree_sdk2_python')
    dds = environment.get('GUIDEBOT_DDS_HOME') or environment.get('CYCLONEDDS_HOME') or str(
        Path.home()/'.local/share/guidebot/deps/cyclonedds')
    environment['CYCLONEDDS_HOME'] = dds
    for name, prefix in [('PYTHONPATH', sdk), ('LD_LIBRARY_PATH', str(Path(dds)/'lib'))]:
        entries = [value for value in environment.get(name, '').split(os.pathsep) if value]
        environment[name] = os.pathsep.join([prefix, *[value for value in entries if value != prefix]])
    return environment


def main():
    if '--help' in sys.argv:
        print('Usage (conda activate GuideBot): python tools/ros2/conversation.py '
              '[--gesture-backend simulated|unitree] [normal conversation options]\n'
              'Default: simulated gestures. Enter still authorizes audio/motion. '
              'Uses guidebot-ros2:runtime; host env GUIDEBOT_DOCKER_USE_SG=0 disables sg.')
        return
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'GuideBot/conversation'))
    from knowledge import load_secret
    load_secret()  # Existing credentials stay on host; only planner fields enter sidecar.
    timing = os.environ.get('GUIDEBOT_GESTURE_TIMING_MODE', 'immediate')
    sidecar = Sidecar(timing=timing)
    try:
        sidecar.start()
        environment = dict(host_environment(), GUIDEBOT_COMMUNICATION='ros2',
                           GUIDEBOT_ROS_IPC=str(sidecar.root/'ipc'),
                           GUIDEBOT_GESTURE_TIMING_MODE=timing)
        args = sys.argv[1:]
        if '--gesture-backend' not in args:
            args = ['--gesture-backend','simulated', *args]
        if '--gestures' not in args:
            args.append('--gestures')
        print(f'ROS2 sidecar ready (idle). Logs: {sidecar.root}', flush=True)
        child = subprocess.Popen([sys.executable, 'GuideBot/conversation/conversation.py', *args],
                                 cwd=Path(__file__).resolve().parents[2], env=environment)
        try:
            return child.wait()
        except BaseException:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
                child.wait(timeout=60)
            raise
    finally:
        sidecar.stop()


if __name__ == '__main__':
    raise SystemExit(main())
