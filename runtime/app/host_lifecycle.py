"""Voice-only host endpoint for managed ROS heartbeats; no gesture or SDK dependencies."""
from pathlib import Path
import time

from runtime.ipc.channel import Server


class HostLifecycleEndpoint:
    def __init__(self, root, session_id, generation=1):
        self.root, self.session_id, self.generation = Path(root), session_id, generation
        self.server = None
        self.last_heartbeat = None

    def start(self):
        if self.server is not None:
            raise RuntimeError('Host endpoint is already running')
        self.server = Server(self.root/'host.sock', self.handle)

    def handle(self, request):
        if (request.get('session_id'), request.get('generation')) != (self.session_id, self.generation):
            raise ValueError('Host session fence rejected')
        if request['op'] == 'heartbeat':
            self.last_heartbeat = time.monotonic()
            return True
        if request['op'] == 'event':
            return True  # Voice-only ROS notifications carry no execution authority.
        if request['op'] == 'stop_motion':
            return dict(stopped=True, mode='voice')
        raise ValueError('Voice-only host does not authorize motion')

    def close(self):
        if self.server is not None:
            self.server.close()
            self.server = None
            (self.root/'host.sock').unlink()
