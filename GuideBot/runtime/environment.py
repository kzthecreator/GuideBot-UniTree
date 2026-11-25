"""Independent Foxy and Unitree process environments; no global library mutation."""
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

REPO = Path(__file__).resolve().parents[2]
FOXY = Path('/opt/ros/foxy')
DEFAULT_INSTALL = Path.home()/'.local/share/guidebot/ros2/foxy/install'


def _clean_ros_base():
    result = dict(os.environ)
    for key in list(result):
        if key.startswith(('ROS_', 'RMW_', 'AMENT_', 'COLCON_', 'CYCLONEDDS', 'DEEPSEEK_', 'STEP_', 'DOUBAO_')) or key in {
                'PYTHONPATH','PYTHONHOME','LD_LIBRARY_PATH','CMAKE_PREFIX_PATH'}:
            result.pop(key, None)
    return result


def ros_environment(*, install=None, domain=None):
    """Read ROS setup with a clean shell; run nodes with the explicit Conda Python."""
    install = Path(install or os.environ.get('GUIDEBOT_ROS_INSTALL', DEFAULT_INSTALL))
    scripts = [FOXY/'setup.bash', install/'local_setup.bash']
    for script in scripts:
        if not script.is_file():
            raise FileNotFoundError(str(script)+'; run python tools/ros2/build.py first')
    # Paths are argv, never interpolated shell code. No environment values are printed.
    command = ['bash','--noprofile','--norc','-c',
               'source "$1" >/dev/null && source "$2" >/dev/null && /usr/bin/env -0',
               'guidebot-env', *map(str, scripts)]
    raw = subprocess.check_output(command, env=_clean_ros_base())
    environment = dict(item.decode().split('=',1) for item in raw.split(b'\0') if b'=' in item)
    environment['PYTHONPATH'] = os.pathsep.join([str(REPO), sysconfig.get_paths()['purelib'], environment.get('PYTHONPATH',''), '/usr/lib/python3/dist-packages'])
    environment['LD_LIBRARY_PATH'] = os.pathsep.join(filter(None,[environment.get('LD_LIBRARY_PATH',''), str(Path(sys.prefix)/'lib')]))
    # Internal localhost graph only; separate account defaults avoid joining
    # another user's graph and exhausting the same DDS participant range.
    default_domain = 50 + os.getuid() % 40
    environment.update(ROS_DOMAIN_ID=str(domain if domain is not None else
                                        os.environ.get('GUIDEBOT_ROS_DOMAIN_ID', default_domain)),
                       ROS_LOCALHOST_ONLY='1', RMW_IMPLEMENTATION='rmw_cyclonedds_cpp',
                       GUIDEBOT_PYTHON=sys.executable, PYTHONNOUSERSITE='1')
    return environment


def sdk_environment():
    environment = dict(os.environ)
    for key in list(environment):
        if key.startswith(('ROS_', 'RMW_', 'AMENT_', 'COLCON_')) or key in {'PYTHONPATH','LD_LIBRARY_PATH','PYTHONHOME','CMAKE_PREFIX_PATH'}:
            environment.pop(key, None)
    sdk = environment.setdefault('UNITREE_SDK_PATH', '/opt/unitree_robotics/unitree_sdk2_python')
    dds = environment.get('GUIDEBOT_DDS_HOME') or environment.get('CYCLONEDDS_HOME') or '/opt/unitree_robotics/cyclonedds'
    environment.update(CYCLONEDDS_HOME=dds, PYTHONPATH=os.pathsep.join([str(REPO),sdk]),
                       LD_LIBRARY_PATH=os.pathsep.join([str(Path(dds)/'lib'),str(Path(sys.prefix)/'lib')]),
                       PYTHONNOUSERSITE='1')
    return environment
