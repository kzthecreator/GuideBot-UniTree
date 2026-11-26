"""Build local Foxy interface/launch packages outside the repository."""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from runtime.app.environment import REPO, FOXY, DEFAULT_INSTALL, _clean_ros_base


def main():
    install = Path(os.environ.get('GUIDEBOT_ROS_INSTALL', DEFAULT_INSTALL)).expanduser()
    work = install.parent
    work.mkdir(parents=True, exist_ok=True)
    raw = subprocess.check_output(['bash','--noprofile','--norc','-c',
        'source "$1" >/dev/null && /usr/bin/env -0','guidebot-build',str(FOXY/'setup.bash')], env=_clean_ros_base())
    env = dict(item.decode().split('=',1) for item in raw.split(b'\0') if b'=' in item)
    env['PATH'] = '/usr/bin:/bin:/usr/local/bin'
    command = ['/usr/bin/python3','/usr/bin/colcon','--log-base',str(work/'log'),'build',
        '--base-paths',str(REPO/'runtime/interfaces/guidebot_interfaces'),str(REPO/'runtime/ros2'),
        '--build-base',str(work/'build-layout'),'--install-base',str(install),
        '--parallel-workers','1','--event-handlers','console_direct+',
        '--cmake-args','-DPYTHON_EXECUTABLE=/usr/bin/python3','-DPython3_EXECUTABLE=/usr/bin/python3']
    env.update(MAKEFLAGS='-j2',CMAKE_BUILD_PARALLEL_LEVEL='2')
    subprocess.run(command,cwd=work,env=env,check=True)
    print('Foxy packages installed: '+str(install))


if __name__ == '__main__':
    main()
