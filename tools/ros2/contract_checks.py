"""Run typed ROS rejection probes against an already active simulated session."""
import argparse
from copy import deepcopy
import json
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from guidebot_interfaces.action import ExecuteGesture
from GuideBot.ros2.codec import message, planning_message
from GuideBot.gesture.catalog import make_input


def resolve(node, future, timeout=8):
    rclpy.spin_until_future_complete(node, future, timeout_sec=timeout)
    if not future.done():
        raise AssertionError('Probe timeout')
    return future.result()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('session')
    args = parser.parse_args()
    # Regression: set_message_fields mutates input lists unless copied.
    payload = make_input('probe','欢迎参观。',complete=True)
    original = deepcopy(payload)
    planning_message(payload,args.session,1)
    assert payload == original, 'ROS conversion mutated planner snapshot'
    rclpy.init()
    node = Node('guidebot_contract_probe')
    client = ActionClient(node,ExecuteGesture,'/guidebot/motion/execute_gesture')
    assert client.wait_for_server(timeout_sec=5)
    defaults = dict(session_id=args.session,generation=1,response_id='probe',
                    job_id='probe-job',action='greet_open',start_monotonic=time.monotonic(),
                    arrival_monotonic=time.monotonic()+2)
    try:
        for overrides in [dict(job_id='r1:0'),dict(session_id='wrong-session'),
                          dict(arrival_monotonic=time.monotonic()-1)]:
            goal = resolve(node,client.send_goal_async(message(ExecuteGesture.Goal,dict(defaults,**overrides))))
            assert not goal.accepted, overrides
        # A context-gated action must fail before touching the native executor.
        request = dict(defaults,action='present_left',job_id='context-reject',
                       arrival_monotonic=time.monotonic()+2)
        goal = resolve(node,client.send_goal_async(message(ExecuteGesture.Goal,request)))
        assert goal.accepted
        result = resolve(node,goal.get_result_async()).result
        assert not result.success and result.outcome == 'failed'
        print(json.dumps({'ok':True,'checks':['immutable_text_snapshot','duplicate_job_rejected',
                          'wrong_session_rejected','expired_goal_rejected','missing_context_rejected']}))
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
