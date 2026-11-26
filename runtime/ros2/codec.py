"""Typed ROS converters; import only in the configured ROS process."""
from copy import deepcopy
from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.set_message import set_message_fields


def to_dict(message):
    return dict(message_to_ordereddict(message))


def message(cls, values):
    result = cls()
    set_message_fields(result, deepcopy(values))
    return result
