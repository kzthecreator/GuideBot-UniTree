"""Bounded ROS cross-process and optional host IPC test; no hardware imports."""
import argparse
import json
import multiprocessing as mp
import socket
import time
import uuid


def subscriber(token, results):
    import rclpy
    from std_msgs.msg import String
    rclpy.init()
    node = rclpy.create_node('guidebot_smoke_sub')
    received = []
    node.create_subscription(String, '/guidebot/smoke',
                             lambda msg: received.append(msg.data), 10)
    deadline = time.monotonic() + 20
    try:
        while token not in received and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        results.put(token in received)
    finally:
        node.destroy_node()
        rclpy.shutdown()


def main():
    import rclpy
    from std_msgs.msg import String
    parser = argparse.ArgumentParser()
    parser.add_argument('--host-socket')
    args = parser.parse_args()
    context = mp.get_context('spawn')
    results = context.Queue()
    token = str(uuid.uuid4())
    process = context.Process(target=subscriber, args=(token, results))
    process.start()
    rclpy.init()
    node = rclpy.create_node('guidebot_smoke_pub')
    publisher = node.create_publisher(String, '/guidebot/smoke', 10)
    deadline = time.monotonic() + 25
    try:
        while process.is_alive() and time.monotonic() < deadline:
            if publisher.get_subscription_count():
                publisher.publish(String(data=token))
            rclpy.spin_once(node, timeout_sec=0.1)
        process.join(timeout=1)
        if process.is_alive() or process.exitcode != 0 or not results.get(timeout=2):
            raise RuntimeError('ROS cross-process communication failed')
        if args.host_socket:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(5)
                client.connect(args.host_socket)
                client.sendall((token + '\n').encode())
                with client.makefile('rb') as reader:
                    answer = reader.readline(128).decode().strip()
                if answer != token:
                    raise RuntimeError('Host IPC echo mismatch')
        print(json.dumps({'ok': True, 'test': 'two_nodes_two_processes',
                          'host_ipc': bool(args.host_socket), 'hardware': False}), flush=True)
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=3)
        node.destroy_node()
        rclpy.shutdown()
        results.close()


if __name__ == '__main__':
    main()
