"""Isolated native Player harness. --offline-server is mandatory and hard-coded."""
import signal
import subprocess
import time
import uuid

from drivers.unitree_motion.paths import BUILD, ASSETS, server_arguments
from drivers.unitree_motion.client import request


class OfflineNative:
    def __init__(self, directory):
        self.name = 'guidebot_ros_offline_' + uuid.uuid4().hex
        self.socket = '\0' + self.name
        self.directory = directory
        self.process = self.log = None

    def call(self, payload):
        return request(self.socket, payload)

    def start(self):
        self.log = (self.directory/'native-offline.log').open('w')
        self.process = subprocess.Popen([str(BUILD/'motion_library_server'),
                  '--offline-server','--start-released','--socket-name',self.name,
                  *server_arguments()], cwd=ASSETS, stdout=self.log, stderr=self.log)
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Offline native server exited')
            try:
                self.call({'接管':True})
                break
            except OSError:
                time.sleep(.05)
        else:
            raise TimeoutError('Offline native socket unavailable')
        while self.call({'状态':True})['status']['ownership'] != 'owned':
            if time.monotonic()>deadline:
                raise TimeoutError('Offline acquire timed out')
            time.sleep(.05)
        return self

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.call({'退出':True})
                self.process.wait(timeout=3)
            except Exception:
                self.process.send_signal(signal.SIGINT)
                self.process.wait(timeout=3)
        if self.log:
            self.log.close()
