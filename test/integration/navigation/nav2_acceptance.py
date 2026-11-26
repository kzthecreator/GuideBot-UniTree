"""Real ROS Nav2 action round-trip against an isolated fake server; no motion.

Source a ROS environment with nav2_msgs. This tool publishes no cmd_vel/lowcmd,
imports no robot SDK and uses a private action name on a localhost-only domain.
"""
import json
import os
from pathlib import Path
import sys
import subprocess
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def main():
    if not os.environ.get('GUIDEBOT_NAV_ACCEPTANCE_CHILD'):
        from runtime.app.environment import ros_environment
        environment = ros_environment()
        environment['GUIDEBOT_NAV_ACCEPTANCE_CHILD'] = '1'
        return subprocess.call([sys.executable, '-u', __file__], env=environment)
    # Set before importing ROS/DDS; never use the robot's domain zero.
    os.environ['ROS_DOMAIN_ID'] = str(180+os.getuid()%20)
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    os.environ.pop('CYCLONEDDS_URI', None)
    import rclpy
    from rclpy.action import ActionServer, GoalResponse
    from rclpy.executors import MultiThreadedExecutor
    from nav2_msgs.action import NavigateToPose
    from GuideBot.navigation.nav2 import Nav2Navigator
    from runtime.ros2.adapters.nav2 import RosNav2Transport

    rclpy.init()
    node=rclpy.create_node('guidebot_nav2_acceptance_'+str(os.getpid()))
    action='/guidebot_test_'+str(os.getpid())+'/navigate_to_pose'

    def execute(handle):
        if handle.request.pose.pose.position.x < 0:
            handle.abort()
        else:
            handle.succeed()
        return NavigateToPose.Result()

    server=ActionServer(node, NavigateToPose, action, execute_callback=execute,
        goal_callback=lambda goal: GoalResponse.REJECT if goal.pose.pose.position.x == 99 else GoalResponse.ACCEPT)
    executor=MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    thread=threading.Thread(target=executor.spin,daemon=True);thread.start()
    transport=RosNav2Transport(node, action)
    done=threading.Event();events=[]
    def notify(kind,**fields):
        events.append(dict(kind=kind,**fields));done.set()
    waypoints={name:dict(frame_id='map',x=x,y=0,yaw=.2)
               for name,x in [('success',1),('abort',-1),('reject',99)]}
    navigator=Nav2Navigator(transport,waypoints,notify)
    try:
        if not transport.ready(5.):raise RuntimeError('Fake action server discovery failed')
        for point,expected in [('success','arrived'),('abort','navigation_failed'),('reject','navigation_failed')]:
            done.clear();navigator.go_to(point,'task-'+point)
            if not done.wait(5):raise RuntimeError('Action result timeout: '+point)
            if events[-1]['kind']!=expected:raise RuntimeError('Unexpected action result')
        print(json.dumps(dict(passed=True,events=events,robot_sdk=False,
                              velocity_publishers=False,domain_id=os.environ['ROS_DOMAIN_ID']),indent=2))
    finally:
        navigator.close();transport.close();server.destroy()
        executor.shutdown();thread.join(timeout=3);node.destroy_node();rclpy.shutdown()


if __name__=='__main__':raise SystemExit(main())
