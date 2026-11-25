"""Local socket client for the G1 motion controller."""
import json
import socket


SOCKET_NAME = "\0g1_arm_motion_library"


def request(socket_name, payload):
    encoded = (json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3.0)
        client.connect(socket_name)
        client.sendall(encoded)
        client.shutdown(socket.SHUT_WR)
        response = client.makefile(encoding="utf-8").readline()
    if not response:
        raise OSError("控制服务端未返回状态")
    result = json.loads(response)
    if not result.get("ok"):
        raise ValueError(result.get("error", "指令被拒绝"))
    return result
