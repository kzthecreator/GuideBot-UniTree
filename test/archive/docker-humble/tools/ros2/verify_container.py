"""Run the isolated ROS/host-IPC smoke test, without robot SDK access."""
import argparse
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import tempfile
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='guidebot-ros2:humble-stage1')
    parser.add_argument('--docker-group', action='store_true',
                        help='Refresh docker group for an existing login using sg')
    args = parser.parse_args()
    state = Path.home() / '.local/state/guidebot/ros2'
    state.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ipc-', dir=str(state)) as directory:
        path = Path(directory) / 'echo.sock'
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(path))
            server.listen(1)
            server.settimeout(40)
            errors = []

            def echo():
                try:
                    connection, _ = server.accept()
                    with connection:
                        connection.settimeout(5)
                        with connection.makefile('rb') as reader:
                            data = reader.readline(128)
                        connection.sendall(data)
                except Exception as error:
                    errors.append(str(error))

            thread = threading.Thread(target=echo, daemon=True)
            thread.start()
            command = ['docker', 'run', '--rm', '--network', 'host',
                       '--user', f'{os.getuid()}:{os.getgid()}',
                       '-e', 'HOME=/tmp',
                       '--mount', f'type=bind,src={directory},dst=/guidebot-ipc',
                       args.image, 'python3', '/opt/guidebot/smoke_test.py',
                       '--host-socket', '/guidebot-ipc/echo.sock']
            if args.docker_group:
                command = ['sg', 'docker', '-c', shlex.join(command)]
            result = subprocess.run(command, check=False)
            if result.returncode:
                raise SystemExit(result.returncode)
            thread.join(timeout=6)
            if thread.is_alive() or errors:
                raise RuntimeError(f'Host IPC failed: {errors}')
            print(json.dumps({'ok': True, 'host_echo': True, 'hardware': False}))


if __name__ == '__main__':
    main()
