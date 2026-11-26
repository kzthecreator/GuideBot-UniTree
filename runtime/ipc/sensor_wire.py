"""Bounded local framing for CDR sensor messages across independent DDS runtimes."""
import json
import struct

MAX_HEADER = 4096
MAX_PAYLOAD = 8*1024*1024
TRACKS = {'cloud', 'imu', 'odom'}


def send(connection, header, payload):
    if header.get('track') not in TRACKS or not 0 < len(payload) <= MAX_PAYLOAD:
        raise ValueError('Invalid sensor payload')
    metadata = dict(header, size=len(payload))
    raw = json.dumps(metadata, allow_nan=False).encode()
    if len(raw) > MAX_HEADER:
        raise ValueError('Sensor header too large')
    connection.sendall(struct.pack('!I', len(raw))+raw+payload)


def read_exact(connection, size):
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size-len(data))
        if not chunk:
            raise EOFError('Sensor source disconnected')
        data.extend(chunk)
    return bytes(data)


def receive(connection):
    length = struct.unpack('!I', read_exact(connection, 4))[0]
    if not 0 < length <= MAX_HEADER:
        raise ValueError('Invalid sensor header length')
    header = json.loads(read_exact(connection, length))
    size = header.get('size')
    if header.get('track') not in TRACKS or type(size) is not int or not 0 < size <= MAX_PAYLOAD:
        raise ValueError('Invalid sensor frame')
    if type(header.get('received_ns')) is not int:
        raise ValueError('Missing sensor receive time')
    return header, read_exact(connection, size)
