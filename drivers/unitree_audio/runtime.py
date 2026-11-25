"""G1 SDK loading and multicast PCM capture; no business imports."""
import os
import sys
from pathlib import Path
import socket
import struct
import time

def load_audio_sdk():
    """Use shared SDK locations even when the terminal has not sourced its profile."""
    sdk_path = Path(os.environ.get("UNITREE_SDK_PATH", "/opt/unitree_robotics/unitree_sdk2_python"))
    if sdk_path.is_dir() and str(sdk_path) not in sys.path:
        sys.path.insert(0, str(sdk_path))
    os.environ.setdefault("CYCLONEDDS_HOME", "/opt/unitree_robotics/cyclonedds")
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
    return ChannelFactoryInitialize, AudioClient

def microphone_packets(stopping, stats):
    """Continuously capture the accepted multicast stream; caller owns triggering."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("", 5555))
        membership = struct.pack("4s4s", socket.inet_aton("239.168.123.161"),
                                 socket.inet_aton("192.168.123.164"))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        sock.settimeout(0.2)
        last_packet = time.monotonic()
        while not stopping.is_set():
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                if time.monotonic() - last_packet > 5:
                    raise RuntimeError("No G1 microphone packets for 5s; check the official wake-up mode")
                continue
            if not data or len(data) % 2:
                raise RuntimeError("Invalid microphone PCM16 packet")
            last_packet = time.monotonic()
            stats["microphone_packets"] += 1
            stats["nonzero_packets"] += int(any(data))
            yield data
