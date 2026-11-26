"""Manual audio recording/playback tools. Enter authorizes device access."""
import argparse
import audioop
import os
from pathlib import Path
import socket
import struct
import sys
import time
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
RATE = 16000

from GuideBot.conversation.audio import state_directory, wait_for_enter, save_wav
from GuideBot.robot.audio.runtime import load_audio_sdk

def record(seconds, destination):
    if not 1 <= seconds <= 30:
        raise ValueError("Recording duration must be 1..30 seconds")
    wait_for_enter(f"Ready. Press Enter to record up to {seconds}s; Ctrl+C cancels. ")
    print("Recording from G1. Speak now.", flush=True)
    frames = []
    total_bytes = silence_bytes = packets = nonzero_packets = 0
    speech_detected = False
    deadline = time.monotonic() + seconds + 8
    # Same socket setup and silence rules as Saxion unitree_converse's tested receiver.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("", 5555))
        membership = struct.pack("4s4s", socket.inet_aton("239.168.123.161"),
                                 socket.inet_aton("192.168.123.164"))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        sock.settimeout(0.1)
        while total_bytes < seconds * RATE * 2 and time.monotonic() < deadline:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            if not data or len(data) % 2:
                raise RuntimeError("Received invalid PCM16 UDP packet")
            frames.append(data)
            total_bytes += len(data)
            packets += 1
            nonzero_packets += int(any(data))
            samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
            if np.sqrt(np.mean(samples ** 2)) >= 0.008:
                speech_detected = True
                silence_bytes = 0
            elif speech_detected:
                silence_bytes += len(data)
            if speech_detected and silence_bytes >= 2 * RATE * 2:
                print("Silence detected; stopping early.")
                break
    pcm = b"".join(frames)
    print(f"Network UDP: packets={packets}, nonzero_packets={nonzero_packets}")
    if not pcm:
        raise RuntimeError("No microphone packets received. Check the official assistant's wake-up mode.")
    save_wav(destination, pcm)
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    peak = int(np.max(np.abs(samples)))
    print(f"PCM: {len(samples) / RATE:.3f}s, RMS={np.sqrt(np.mean(samples ** 2)):.1f}, peak={peak}")
    print(f"Saved WAV: {destination}")
    if not peak:
        raise RuntimeError("PC1 sent only zeros. Restore the working official assistant wake-up state.")
    return pcm

def prepare_audio(source, destination, normalize=True):
    info = sf.info(str(source))
    if info.frames <= 0 or info.samplerate <= 0 or not 0 < info.duration <= 120:
        raise ValueError("Audio must contain 0 < duration <= 120 seconds")
    audio, rate = sf.read(str(source), dtype="float32", always_2d=True)
    if not np.isfinite(audio).all():
        raise ValueError("Audio contains nonfinite samples")
    mono = np.clip(audio.mean(axis=1), -1, 1)
    pcm = np.rint(mono * 32767).astype("<i2").tobytes()
    if rate != RATE:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, RATE, None)
    samples = np.frombuffer(pcm, dtype="<i2")
    if not len(samples) or not np.any(samples):
        raise ValueError("Converted audio contains no nonzero samples")
    peak = int(np.abs(samples.astype(np.int32)).max())
    gain = round(32767 * 10 ** (-1 / 20)) / peak if normalize else 1.
    pcm = np.rint(samples.astype(np.float64) * gain).astype("<i2").tobytes()
    save_wav(destination, pcm)
    print(f"Speaker PCM: {len(pcm) / (RATE * 2):.3f}s, peak normalization gain={gain:.3f}x")
    return pcm

def play(source, destination):
    pcm = prepare_audio(source, destination)
    wait_for_enter("Press Enter to play the reply through G1, or Ctrl+C to cancel. ")
    ChannelFactoryInitialize, AudioClient = load_audio_sdk()

    ChannelFactoryInitialize(0, "eth0")
    client = AudioClient()
    client.SetTimeout(5)
    client.Init()
    print("GetVolume:", client.GetVolume(), flush=True)
    app_name = "guidebot-conversation"
    stream_id = str(time.time_ns())
    started = time.monotonic()
    try:
        # Preserve the accepted official-example chunk size and pacing.
        for offset in range(0, len(pcm), 96000):
            chunk = pcm[offset:offset + 96000]
            code, _ = client.PlayStream(app_name, stream_id, chunk)
            print(f"PlayStream offset={offset}, bytes={len(chunk)}, code={code}", flush=True)
            if code != 0:
                raise RuntimeError(f"PlayStream failed (code={code})")
            if offset + len(chunk) < len(pcm):
                time.sleep(1)
        time.sleep(max(0, len(pcm) / (RATE * 2) - (time.monotonic() - started)) + 1)
    finally:
        client.PlayStop(app_name)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recording = commands.add_parser("record")
    recording.add_argument("seconds", type=int, choices=range(1, 31), nargs="?", default=5)
    recording.add_argument("--output", type=Path)
    playback = commands.add_parser("play")
    playback.add_argument("source", type=Path)
    args = parser.parse_args()
    stamp = time.time_ns()
    if args.command == "record":
        record(args.seconds, args.output or state_directory() / f"mic-{stamp}.wav")
    else:
        play(args.source, state_directory() / f"speaker-{stamp}.wav")

if __name__ == "__main__":
    main()
