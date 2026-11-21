"""Start the motion server with repository asset paths; the server still asks RUN."""
import argparse
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-joint-limits', action='store_true')
    parser.add_argument('--socket-name', default='g1_arm_motion_library')
    parser.add_argument('--offline', action='store_true', help='No robot connection (protocol checks only)')
    args = parser.parse_args()
    build = Path(os.environ.get('GUIDEBOT_MOTION_BUILD_DIR',
                                Path.home()/'.local/share/guidebot/deps/motion/build-reorganized'))
    command = [str(build/'motion_library_server'), '--dir', str(REPO/'assets/motion/motions'),
        '--poses', str(REPO/'assets/motion/poses'), '--metadata', str(REPO/'assets/motion/metadata'),
        '--catalog', str(REPO/'assets/motion/config/motion_catalog.json'),
        '--limits', str(REPO/'drivers/unitree_motion/config/arm_joint_limits.json'),
        '--socket-name', args.socket_name]
    if args.skip_joint_limits:
        command.append('--skip-joint-limits')
    if args.offline:
        command.append('--offline-server')
    os.execv(command[0], command)


if __name__ == '__main__':
    main()
