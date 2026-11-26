"""Run typed ROS rejection probes against an already active simulated session."""
import argparse
from copy import deepcopy
import json
import time

import rclpy
from rclpy.action import ActionClient
from rclpy.action.graph import get_action_names_and_types
from rclpy.node import Node
from guidebot_interfaces.action import ExecuteGesture
from guidebot_interfaces.msg import ConversationInput
from runtime.ros2.codec import message


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
    payload = dict(session_id=args.session,generation=1,kind='alignment',
                   anchors=[dict(index=0,text='欢',text_offset=0,start=.2)])
    original = deepcopy(payload)
    message(ConversationInput,payload)
    assert payload == original, 'ROS conversion mutated planner snapshot'
    rclpy.init()
    node = Node('guidebot_contract_probe')
    names = set(node.get_node_names())
    assert {'session_manager','conversation','gesture','motion'} <= names, names
    assert not names & {'gesture_planner','gesture_scheduler','interaction_manager','voice_gateway','motion_gateway'}, names
    assert not any(name == '/guidebot/gesture/plan' for name, _ in get_action_names_and_types(node)), 'Remote planning Action remains'
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
        # Context no longer gates action selection (2026-11-25 policy).
        request = dict(defaults,action='present_left',job_id='context-reject',
                       arrival_monotonic=time.monotonic()+2)
        goal = resolve(node,client.send_goal_async(message(ExecuteGesture.Goal,request)))
        assert goal.accepted
        result = resolve(node,goal.get_result_async()).result
        assert result.success, result.reason
        print(json.dumps({'ok':True,'checks':['immutable_input_snapshot','four_core_nodes','no_remote_planning_action','duplicate_job_rejected',
                          'wrong_session_rejected','expired_goal_rejected','missing_context_allowed']}))
    finally:
        client.destroy()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
