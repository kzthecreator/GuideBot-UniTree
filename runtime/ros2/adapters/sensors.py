"""Publish local ROS sensor copies, keeping SDK CycloneDDS out of ROS processes."""
import json
from collections import deque
from pathlib import Path
import socket
import threading
import time


def run(endpoint, directory):
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.serialization import deserialize_message
    from sensor_msgs.msg import PointCloud2, Imu
    from nav_msgs.msg import Odometry
    from runtime.ipc.sensor_wire import receive
    rclpy.init()
    node = rclpy.create_node('guidebot_sensor_bridge')
    types = dict(cloud=PointCloud2, imu=Imu, odom=Odometry)
    publishers = {name: node.create_publisher(cls, '/guidebot/sensors/'+name, qos_profile_sensor_data)
                  for name, cls in types.items()}
    pending = {name: deque() for name in types}
    limits = dict(cloud=4, imu=2048, odom=8192)
    lock, stopping = threading.Lock(), threading.Event()
    stats = dict(published={}, overwritten={}, errors=[], clock_offset_ns=None,
                 timestamp_policy='one shared offset from first received source sample; raw CDR timestamps preserved')
    root = Path(directory)
    # Native source also stores a bounded chronological CDR stream when requested.
    save = (root/'record.enabled').exists()
    index = (root/'samples.jsonl').open('w') if save else None
    raw = (root/'samples.cdr').open('wb') if save else None
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(endpoint)
    Path(endpoint).chmod(0o600)
    server.listen(1)
    server.settimeout(.2)
    (root/'ros.ready').touch()

    def ingest():
        try:
            while not stopping.is_set():
                try:
                    connection, _ = server.accept()
                    break
                except socket.timeout:
                    continue
            else:
                return
            with connection:
                connection.settimeout(2)
                while not stopping.is_set():
                    header, payload = receive(connection)
                    if save:
                        offset = raw.tell();raw.write(payload)
                        index.write(json.dumps(dict(header, offset=offset))+'\n')
                    with lock:
                        track = header['track']
                        if len(pending[track]) >= limits[track]:
                            pending[track].popleft()
                            stats['overwritten'][track] = stats['overwritten'].get(track, 0)+1
                        pending[track].append((header, payload))
        except EOFError:
            stats['source_disconnected'] = True
        except socket.timeout:
            if not stopping.is_set():stats['errors'].append('Sensor source stopped sending for 2 seconds')
        except Exception as error:
            if not stopping.is_set():
                stats['errors'].append(type(error).__name__+': '+str(error))
        finally:
            if raw:raw.flush()
            if index:index.flush()

    thread = threading.Thread(target=ingest, daemon=True);thread.start()
    def publish():
        with lock:
            samples = [(track, item) for track, items in pending.items() for item in items]
            for items in pending.values():items.clear()
        for track, (header, payload) in samples:
            try:
                msg = deserialize_message(payload, types[track])
                stamp = msg.header.stamp.sec*1000000000+msg.header.stamp.nanosec
                if stats['clock_offset_ns'] is None:
                    stats['clock_offset_ns'] = header['received_ns']-stamp
                mapped = stamp+stats['clock_offset_ns']
                if abs(header['received_ns']-mapped) > 2000000000:
                    raise ValueError('Source clock jumped or sensors use inconsistent clocks; restart capture')
                msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(mapped, 1000000000)
                publishers[track].publish(msg)
                if track == 'cloud':
                    from GuideBot.perception.preview import write_preview
                    write_preview(root, msg)
                stats['published'][track] = stats['published'].get(track, 0)+1
            except Exception as error:
                if len(stats['errors']) < 20:stats['errors'].append(type(error).__name__+': '+str(error))
        (root/'bridge-status.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2))
    node.create_timer(.01, publish)
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:
        stopping.set();server.close();thread.join(timeout=3)
        if raw:raw.close()
        if index:index.close()
        (root/'bridge-status.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2))
        node.destroy_node();rclpy.shutdown()
