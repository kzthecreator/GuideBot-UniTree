"""Manual launcher for the fork motion service; conversation normally manages it."""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from GuideBot.robot.motion.paths import ASSETS, BUILD, server_arguments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--socket-name', default='g1_arm_motion_library')
    args = parser.parse_args()
    binary = BUILD/'motion_library_server'
    command = [str(binary), '--start-released', *server_arguments(), '--socket-name', args.socket_name]
    if args.offline:
        command.append('--offline-server')
    os.chdir(ASSETS)
    os.execv(str(binary), command)


if __name__ == '__main__':
    main()
