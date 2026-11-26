"""ROS-only Nav2 action transport; run in the navigation ROS environment.

No Unitree SDK imports, velocity publications or lowcmd ownership. The caller
owns spinning the supplied node. Compatible with PoseStamped NavigateToPose.
"""
import math


class RosNav2Transport:
    def __init__(self, node, action_name='/navigate_to_pose'):
        from rclpy.action import ActionClient
        from nav2_msgs.action import NavigateToPose
        self.node, self.action_type = node, NavigateToPose
        self.client = ActionClient(node, NavigateToPose, action_name)

    def ready(self, timeout=0.):
        return self.client.wait_for_server(timeout_sec=timeout)

    def send(self, pose, done):
        if not self.ready():
            raise RuntimeError('NavigateToPose action server is unavailable')
        goal = self.action_type.Goal()
        goal.pose.header.frame_id = pose['frame_id']
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(pose['x'])
        goal.pose.pose.position.y = float(pose['y'])
        goal.pose.pose.orientation.z = math.sin(pose['yaw']/2)
        goal.pose.pose.orientation.w = math.cos(pose['yaw']/2)
        ticket = dict(handle=None, canceled=False, done=done)
        future = self.client.send_goal_async(goal)
        future.add_done_callback(lambda value: self._accepted(ticket, value))
        return ticket

    def _accepted(self, ticket, future):
        try:
            handle = future.result()
            ticket['handle'] = handle
            if not handle.accepted:
                ticket['done']('rejected')
            elif ticket['canceled']:
                handle.cancel_goal_async()
            else:
                result = handle.get_result_async()
                result.add_done_callback(lambda value: self._result(ticket, value))
        except Exception:
            ticket['done']('aborted')

    @staticmethod
    def _result(ticket, future):
        try:
            # action_msgs/msg/GoalStatus, stable across Foxy and Jazzy.
            status = {4: 'succeeded', 5: 'canceled'}.get(future.result().status, 'aborted')
        except Exception:
            status = 'aborted'
        ticket['done'](status)

    @staticmethod
    def cancel(ticket):
        ticket['canceled'] = True
        if ticket['handle'] is not None and ticket['handle'].accepted:
            ticket['handle'].cancel_goal_async()

    def close(self):
        self.client.destroy()
