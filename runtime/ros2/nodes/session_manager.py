"""Authoritative ROS session lifecycle; host workers never start themselves."""
from runtime.ros2.nodes.common import *

from runtime.orchestrator.session import ROLES, SessionCoordinator


class SessionManager(Node, SessionCoordinator):
    def __init__(self):
        super().__init__('session_manager')
        offline = os.environ.get('GUIDEBOT_ROS_OFFLINE') == '1'
        self.initialize_session(offline=offline, managed_resources=(not offline or
            os.environ.get('GUIDEBOT_ROS_MANAGED_TEST') == '1'))
        self.control_clients = {role: self.create_client(SessionControl, '/guidebot/internal/'+role+'/control',
                       callback_group=ReentrantCallbackGroup()) for role in ROLES}
        self.control = self.create_service(SessionControl, '/guidebot/session/control', self.control_session,
                                          callback_group=ReentrantCallbackGroup())
        self.timer = self.create_timer(.5, self.check_health, callback_group=ReentrantCallbackGroup())

    def worker(self, op, timeout=60):
        return call(ROOT/'resources.sock', dict(op=op, session_id=self.session_id,
                                              generation=self.generation), timeout)

    def node_control(self, role, command):
        client = self.control_clients[role]
        if not client.wait_for_service(timeout_sec=5):
            raise RuntimeError('Required ROS node unavailable: '+role)
        result = wait(client.call_async(message(SessionControl.Request,
                      dict(session_id=self.session_id, generation=self.generation,
                           command=command, mode=self.mode))), 20)
        if not result.accepted:
            raise RuntimeError('ROS node rejected '+command+': '+role)

    def host_heartbeat(self):
        return call(ROOT/'host.sock', dict(op='heartbeat', session_id=self.session_id,
                                          generation=self.generation), 2)

    def log_health_error(self, message):
        self.get_logger().error(message)
