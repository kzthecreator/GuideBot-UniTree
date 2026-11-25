"""Start/stop an idle Humble sidecar. No authorization to use robot devices."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import uuid

from GuideBot.host_bridge.ipc import call


class Sidecar:
    def __init__(self, *, image='guidebot-ros2:runtime', offline=False, timing=None, managed_test=False):
        self.image, self.offline, self.timing = image, offline, timing
        self.managed_test = managed_test
        self.name = 'guidebot-ros-' + uuid.uuid4().hex[:12]
        base = Path.home()/'.local/state/guidebot/ros2'
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='run-', dir=base))
        (self.root/'ipc').mkdir(mode=0o700)
        (self.root/'session').mkdir()
        (self.root/'secrets').mkdir(mode=0o700)
        self.started = False

    def docker(self, *args, check=True, capture=True):
        command = ['docker', *args]
        if os.environ.get('GUIDEBOT_DOCKER_USE_SG', '1') == '1':
            command = ['sg','docker','-c', shlex.join(command)]
        return subprocess.run(command, check=check, text=True,
                              stdout=subprocess.PIPE if capture else None,
                              stderr=subprocess.PIPE if capture else None)

    def start(self):
        secrets = self.root/'secrets/planner.env'
        allowed = ('DEEPSEEK_API_KEY','DEEPSEEK_BASE_URL','DEEPSEEK_MODEL')
        with secrets.open('w') as output:
            for key in allowed:
                if key in os.environ and not self.offline:
                    output.write(key+'='+json.dumps(os.environ[key])+'\n')
        secrets.chmod(0o600)
        command = ['run','-d','--name',self.name,'--network','host',
                   '--user',f'{os.getuid()}:{os.getgid()}', '-e','HOME=/tmp',
                   '-e',f'GUIDEBOT_ROS_OFFLINE={int(self.offline)}',
                   '-e',f'GUIDEBOT_ROS_MANAGED_TEST={int(self.managed_test)}',
                   '--mount',f'type=bind,src={Path(__file__).resolve().parents[2]/"assets/motion"},dst=/opt/guidebot_repo/assets/motion,readonly',
                   '--mount',f'type=bind,src={Path(__file__).resolve().parents[2]/"drivers/unitree_motion/config"},dst=/opt/guidebot_repo/drivers/unitree_motion/config,readonly',
                   '--mount',f'type=bind,src={self.root/"ipc"},dst=/guidebot-ipc',
                   '--mount',f'type=bind,src={self.root/"session"},dst=/guidebot-session',
                   '--mount',f'type=bind,src={self.root/"secrets"},dst=/guidebot-secrets,readonly']
        if self.timing:
            command += ['-e',f'GUIDEBOT_GESTURE_TIMING_MODE={self.timing}']
        command.append(self.image)
        self.docker(*command)
        self.started = True
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            try:
                if call(self.root/'ipc/ros.sock', {'op':'health'})['ready']:
                    return self
            except (OSError, RuntimeError):
                pass
            state = self.docker('inspect','--format','{{.State.Running}}',self.name,check=False)
            if state.stdout.strip() == 'false':
                break
            time.sleep(.1)
        logs = self.docker('logs', self.name, check=False)
        (self.root/'container.log').write_text(logs.stdout+logs.stderr)
        self.stop()
        raise RuntimeError(f'ROS sidecar startup failed; see {self.root}/container.log')

    def stop(self):
        try:
            if self.started:
                self.docker('stop', '--time', '15', self.name, check=False)
                logs = self.docker('logs', self.name, check=False)
                (self.root/'container.log').write_text(logs.stdout+logs.stderr)
                self.docker('rm', self.name, check=False)
                self.started = False
        finally:
            secrets = self.root/'secrets/planner.env'
            if secrets.exists():
                secrets.unlink()
