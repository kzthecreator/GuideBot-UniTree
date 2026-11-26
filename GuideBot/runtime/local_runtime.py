"""Manage the local Foxy launch process. Hardware remains idle until ROS activation."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

from .environment import REPO, ros_environment
from .ipc import call


class LocalRuntime:
    def __init__(self, *, offline=False, timing=None, managed_test=False):
        self.offline, self.timing, self.managed_test = offline, timing, managed_test
        base = Path.home()/'.local/state/guidebot/ros2'
        base.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='foxy-', dir=base))
        for name in ['ipc','session','secrets']:
            (self.root/name).mkdir(mode=0o700)
        self.process = self.log = None
        self.environment = None

    def start(self):
        secret = self.root/'secrets/planner.env'
        with secret.open('w') as output:
            for key in ('DEEPSEEK_API_KEY','DEEPSEEK_BASE_URL','DEEPSEEK_MODEL'):
                if key in os.environ and not self.offline:
                    output.write(key+'='+json.dumps(os.environ[key])+'\n')
        secret.chmod(0o600)
        self.environment = ros_environment()
        self.environment.update(GUIDEBOT_ROS_IPC=str(self.root/'ipc'),
            GUIDEBOT_SESSION_DIR=str(self.root/'session'), GUIDEBOT_PLANNER_ENV=str(secret),
            GUIDEBOT_ROS_OFFLINE=str(int(self.offline)), GUIDEBOT_ROS_MANAGED_TEST=str(int(self.managed_test)))
        if self.timing:
            self.environment['GUIDEBOT_GESTURE_TIMING_MODE'] = self.timing
        self.log = (self.root/'ros.log').open('w')
        try:
            self.process = subprocess.Popen([self.environment['GUIDEBOT_PYTHON'],'-m','GuideBot.ros2.launcher'],
                cwd=REPO, env=self.environment, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic()+30
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    break
                try:
                    if (call(self.root/'ipc/ros.sock', {'op':'health'})['ready']
                            and all((self.root/'session'/('node-'+role+'.json')).is_file()
                                    for role in ('session','conversation','gesture','motion'))):
                        return self
                except (OSError,RuntimeError):
                    pass
                time.sleep(.1)
            raise RuntimeError('Foxy graph startup failed; see '+str(self.root/'ros.log'))
        except BaseException:
            self.stop()
            raise

    def run(self, *args, check=True):
        return subprocess.run([self.environment['GUIDEBOT_PYTHON'],*args], cwd=REPO, env=self.environment,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)

    def pause(self):
        os.killpg(self.process.pid, signal.SIGSTOP)

    def resume(self):
        os.killpg(self.process.pid, signal.SIGCONT)

    def signal_node(self, role, signum):
        # Runner files are session-owned; never scan/kill unrelated ROS processes.
        path = self.root/'session'/('node-'+role+'.json')
        row = json.loads(path.read_text())
        os.kill(row['pid'], signum)

    def stop(self):
        try:
            process = self.process
            if process is not None:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGINT)
                    try:
                        process.wait(timeout=25)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
                # Descendants must not survive a failed launch leader.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                self.process = None
        finally:
            if self.log is not None:
                self.log.close()
                self.log = None
            secret = self.root/'secrets/planner.env'
            if secret.exists():
                secret.unlink()
