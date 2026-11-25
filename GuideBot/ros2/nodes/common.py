"""Local Foxy graph: typed speech events, local gesture planning and motion Action.

Never imports microphone or robot SDK. Host motion access is private bounded IPC.
"""
import json
import math
import os
from pathlib import Path
import threading
import time
from GuideBot.compat import CancellableThreadPoolExecutor as ThreadPoolExecutor

import rclpy
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from guidebot_interfaces.msg import (ConversationInput, GestureEvent, InteractionContext,
                                    MotionState, Transcript)
from guidebot_interfaces.srv import SessionControl
from guidebot_interfaces.action import ExecuteGesture

from GuideBot.runtime.ipc import Server, call
from GuideBot.gesture.catalog import Catalog, Plan
from GuideBot.gesture.planner import Planner
from GuideBot.gesture.service import GestureService
from ..protocol import Fence, context_from_wire
from ..codec import message, to_dict

ROOT = Path(os.environ['GUIDEBOT_ROS_IPC'])
QOS = QoSProfile(depth=128, reliability=ReliabilityPolicy.RELIABLE)
STATE_QOS = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL)


def wait(future, timeout=8):
    done = threading.Event()
    future.add_done_callback(lambda _: done.set())
    if not done.wait(timeout):
        raise TimeoutError('ROS operation timed out')
    return future.result()


