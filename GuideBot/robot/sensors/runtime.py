"""Receive existing robot DDS sensors. No publishers or motion/control API calls."""
import json
from pathlib import Path
import socket
import time


def source_types():
    from dataclasses import dataclass
    import cyclonedds.idl as idl
    import cyclonedds.idl.annotations as annotate
    import cyclonedds.idl.types as types
    from unitree_sdk2py.idl.std_msgs.msg.dds_ import Header_
    from unitree_sdk2py.idl.geometry_msgs.msg.dds_ import Quaternion_, Vector3_
    from unitree_sdk2py.idl.sensor_msgs.msg.dds_ import PointCloud2_
    from unitree_sdk2py.idl.nav_msgs.msg.dds_ import Odometry_

    @dataclass
    @annotate.final
    @annotate.autoid('sequential')
    class Imu_(idl.IdlStruct, typename='sensor_msgs.msg.dds_.Imu_'):
        header: Header_
        orientation: Quaternion_
        orientation_covariance: types.array[types.float64, 9]
        angular_velocity: Vector3_
        angular_velocity_covariance: types.array[types.float64, 9]
        linear_acceleration: Vector3_
        linear_acceleration_covariance: types.array[types.float64, 9]

    return dict(cloud=('rt/utlidar/cloud_livox_mid360', PointCloud2_),
                imu=('rt/utlidar/imu_livox_mid360', Imu_), odom=('rt/dog_odom', Odometry_))


def run(endpoint, interface, directory, duration=None):
    from GuideBot.robot.audio.runtime import load_audio_sdk
    # Imports and process-local log config only: no AudioClient construction.
    load_audio_sdk()
    from unitree_sdk2py.core import channel
    from cyclonedds.domain import Domain, DomainParticipant
    from cyclonedds.topic import Topic
    from cyclonedds.sub import DataReader
    from cyclonedds.qos import Qos, Policy
    from runtime.ipc.sensor_wire import send
    config = channel.ChannelConfigHasInterface.replace('$__IF_NAME__$', interface)
    domain = Domain(0, config=config)
    participant = DomainParticipant(0)
    sources = source_types()
    readers = {name: DataReader(participant, Topic(participant, topic, cls),
        qos=Qos(Policy.Reliability.BestEffort, Policy.History.KeepLast(8)))
        for name, (topic, cls) in sources.items()}
    started = time.monotonic()
    last_status = 0.
    statistics = dict(read_only=True, interface=interface, domain=0, sources={}, errors=[])
    target = Path(directory)/'source-status.json'
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(endpoint)
            while duration is None or time.monotonic()-started < duration:
                for track, reader in readers.items():
                    for msg in reader.take(8):
                        if getattr(msg, 'sample_info', None) and not msg.sample_info.valid_data:
                            continue
                        received = time.time_ns()
                        stamp = msg.header.stamp.sec*1000000000+msg.header.stamp.nanosec
                        row = statistics['sources'].setdefault(track, dict(count=0, topic=sources[track][0]))
                        row.update(count=row['count']+1, frame=msg.header.frame_id,
                                   source_stamp_ns=stamp, last_received_ns=received,
                                   source_clock_offset_s=(received-stamp)/1e9)
                        if track == 'cloud':
                            row.update(points=msg.width*msg.height, bytes=len(msg.data))
                        if track == 'odom':
                            row.update(child_frame=msg.child_frame_id)
                        send(connection, dict(track=track, received_ns=received),
                             msg.serialize(use_version_2=False))
                if time.monotonic()-started > 5 and not statistics['sources']:
                    raise RuntimeError('No sensor samples on robot DDS domain 0')
                statistics['elapsed_s'] = time.monotonic()-started
                if time.monotonic()-last_status > .5:
                    target.write_text(json.dumps(statistics, ensure_ascii=False, indent=2))
                    last_status = time.monotonic()
                time.sleep(.002)
    except KeyboardInterrupt:
        pass
    except Exception as error:
        statistics['errors'].append(type(error).__name__+': '+str(error))
        raise
    finally:
        statistics['elapsed_s'] = time.monotonic()-started
        target.write_text(json.dumps(statistics, ensure_ascii=False, indent=2))
