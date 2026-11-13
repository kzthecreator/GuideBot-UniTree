"""G1 multicast microphone and Unitree SDK speaker, with manual triggering."""

import argparse
import audioop
import ctypes
from ctypes.util import find_library
import json
import math
from collections import deque
from dataclasses import dataclass, field
import os
from pathlib import Path
import signal
import socket
import struct
import sys
import threading
import time
import wave

import numpy as np
import soundfile as sf

RATE = 16000
CLOUD_RATE = 24000


def load_audio_sdk():
    """Use shared SDK locations even when the terminal has not sourced its profile."""
    sdk_path = Path(os.environ.get("UNITREE_SDK_PATH", "/opt/unitree_robotics/unitree_sdk2_python"))
    if sdk_path.is_dir() and str(sdk_path) not in sys.path:
        sys.path.insert(0, str(sdk_path))
    os.environ.setdefault("CYCLONEDDS_HOME", "/opt/unitree_robotics/cyclonedds")
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
    return ChannelFactoryInitialize, AudioClient


def state_directory():
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return Path(os.environ.get("GUIDEBOT_STATE_DIR", base / "guidebot/conversation"))


def wait_for_enter(message):
    try:
        input(message)
    except EOFError:
        raise RuntimeError("Cancelled: interactive input required; no audio was started.") from None


def save_wav(destination, pcm, rate=RATE):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(pcm)


class AudioDiagnostic:
    """Store sample offsets and arrival/RPC times; these are not DAC timestamps."""

    def __init__(self, directory, started_at, processed=False, gated=False):
        self.lock = threading.Lock()
        self.started_at = started_at
        self.closed = False
        self.offsets = {"microphone": 0, "speaker": 0}
        if processed:
            self.offsets["microphone-aec"] = 0
        if gated:
            self.offsets["microphone-gated"] = 0
        self.tracks = {}
        for name in self.offsets:
            track = wave.open(str(directory / f"{name}-16k.wav"), "wb")
            track.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            self.tracks[name] = track
        self.index = (directory / "audio-index.jsonl").open("w", encoding="utf-8")

    def write(self, name, pcm, started_at, **details):
        with self.lock:
            if self.closed:
                return
            self.tracks[name].writeframesraw(pcm)
            record = {"track": name, "elapsed": started_at - self.started_at,
                      "sample_offset": self.offsets[name], "samples": len(pcm) // 2,
                      **details}
            self.index.write(json.dumps(record) + "\n")
            self.offsets[name] += len(pcm) // 2

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                for track in self.tracks.values():
                    track.close()
                self.index.close()


class LevelGate:
    """20 ms RMS gate with 6 dB hysteresis and a 200 ms release hold."""

    frame_bytes = RATE * 2 // 50

    def __init__(self, threshold_dbfs):
        if not math.isfinite(threshold_dbfs) or not -96 <= threshold_dbfs <= 0:
            raise ValueError("Microphone gate threshold must be -96..0 dBFS")
        self.threshold_dbfs = threshold_dbfs
        self.open_level = 32768 * 10 ** (threshold_dbfs / 20)
        self.close_level = self.open_level * 10 ** (-6 / 20)
        self.remaining = 0
        self.open = False
        self.pending = bytearray()
        self.stats = {"frames": 0, "muted_frames": 0, "bypassed_frames": 0}

    def process(self, pcm, enabled=True):
        self.pending.extend(pcm)
        output = bytearray()
        while len(self.pending) >= self.frame_bytes:
            frame = bytes(self.pending[:self.frame_bytes])
            del self.pending[:self.frame_bytes]
            self.stats["frames"] += 1
            if not enabled:
                self.open = False
                self.remaining = 0
                output.extend(frame)
                self.stats["bypassed_frames"] += 1
                continue
            rms = audioop.rms(frame, 2)
            if not self.open and rms >= self.open_level:
                self.open = True
                self.remaining = 10
            elif self.open:
                if rms >= self.close_level:
                    self.remaining = 10
                else:
                    self.remaining -= 1
                    if self.remaining <= 0:
                        self.open = False
            if self.open:
                output.extend(frame)
            else:
                output.extend(bytes(len(frame)))
                self.stats["muted_frames"] += 1
        return bytes(output)


class EchoCanceller:
    """SpeexDSP AEC with a timed reference for the remote G1 speaker."""

    frame_samples = 160

    def __init__(self, delay_ms=0):
        if not 0 <= delay_ms <= 1000:
            raise ValueError("AEC reference delay must be 0..1000 ms")
        library = find_library("speexdsp")
        if not library:
            raise RuntimeError("AEC requires the system libspeexdsp1 library")
        self.lib = ctypes.CDLL(library)
        pointer = ctypes.POINTER(ctypes.c_int16)
        self.lib.speex_echo_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self.lib.speex_echo_state_init.restype = ctypes.c_void_p
        self.lib.speex_echo_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        self.lib.speex_echo_ctl.restype = ctypes.c_int
        self.lib.speex_echo_cancellation.argtypes = [ctypes.c_void_p, pointer, pointer, pointer]
        self.lib.speex_echo_cancellation.restype = None
        self.lib.speex_echo_state_destroy.argtypes = [ctypes.c_void_p]
        self.lib.speex_echo_state_destroy.restype = None
        self.state = self.lib.speex_echo_state_init(self.frame_samples, RATE // 2)
        if not self.state:
            raise RuntimeError("SpeexDSP AEC initialization failed")
        sample_rate = ctypes.c_int(RATE)
        if self.lib.speex_echo_ctl(self.state, 24, ctypes.byref(sample_rate)) != 0:
            self.lib.speex_echo_state_destroy(self.state)
            self.state = None
            raise RuntimeError("SpeexDSP rejected the 16 kHz sample rate")
        self.pointer = pointer
        self.delay = delay_ms / 1000
        self.lock = threading.Lock()
        self.reference = deque()
        self.reference_until = 0.0
        self.capture_until = None
        self.pending = bytearray()
        self.stats = {"frames": 0, "reference_frames": 0, "input_energy": 0.0,
                      "output_energy": 0.0}

    def add_reference(self, pcm, submitted_at):
        with self.lock:
            start = max(submitted_at + self.delay, self.reference_until)
            samples = np.frombuffer(pcm, dtype="<i2").copy()
            self.reference.append((start, samples))
            self.reference_until = start + len(samples) / RATE
            # Bound storage even if microphone capture has stopped.
            while self.reference and self.reference[0][0] < submitted_at - 4:
                self.reference.popleft()

    def stop_reference(self, stopped_at):
        with self.lock:
            kept = deque()
            for start, samples in self.reference:
                count = min(len(samples), max(0, round((stopped_at - start) * RATE)))
                if count:
                    kept.append((start, samples[:count]))
            self.reference = kept
            self.reference_until = stopped_at

    def process(self, pcm, received_at, postprocess=None):
        with self.lock:
            if not self.state:
                raise RuntimeError("AEC is closed")
            # UDP contains blocks, not ADC timestamps. Smooth packet jitter while
            # retaining sample continuity; abandon stale alignment after a gap.
            observed_start = received_at - len(pcm) / (2 * RATE)
            if self.capture_until is None or abs(observed_start - self.capture_until) > .25:
                self.capture_until = observed_start
                self.pending.clear()
            else:
                self.capture_until += (observed_start - self.capture_until) * .02
            start = self.capture_until - len(self.pending) / (2 * RATE)
            self.capture_until += len(pcm) / (2 * RATE)
            self.pending.extend(pcm)
            size = len(self.pending) // (self.frame_samples * 2) * (self.frame_samples * 2)
            recorded = np.frombuffer(bytes(self.pending[:size]), dtype="<i2")
            del self.pending[:size]
            far_end = np.zeros(len(recorded), dtype="<i2")
            for ref_start, samples in self.reference:
                offset = round((ref_start - start) * RATE)
                left, right = max(0, offset), min(len(recorded), offset + len(samples))
                if left < right:
                    far_end[left:right] = samples[left-offset:right-offset]
            output = np.empty_like(recorded)
            for offset in range(0, len(recorded), self.frame_samples):
                near = recorded[offset:offset + self.frame_samples]
                far = far_end[offset:offset + self.frame_samples]
                target = output[offset:offset + self.frame_samples]
                self.lib.speex_echo_cancellation(self.state, near.ctypes.data_as(self.pointer),
                                                far.ctypes.data_as(self.pointer),
                                                target.ctypes.data_as(self.pointer))
                if postprocess is not None:
                    postprocess(target)
                self.stats["frames"] += 1
                if np.any(far):
                    self.stats["reference_frames"] += 1
                    self.stats["input_energy"] += float(np.sum(near.astype(float) ** 2))
                    self.stats["output_energy"] += float(np.sum(target.astype(float) ** 2))
            while self.reference and (self.reference[0][0] + len(self.reference[0][1]) / RATE
                                      < start - 1):
                self.reference.popleft()
            return output.tobytes()

    def close(self):
        with self.lock:
            if self.state:
                self.lib.speex_echo_state_destroy(self.state)
                self.state = None


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


@dataclass
class _ResponseAudio:
    response_id: str
    stream_id: str = field(default_factory=lambda: str(time.time_ns()))
    data: bytearray = field(default_factory=bytearray)
    resample_state: object = None
    done: bool = False
    received_bytes: int = 0
    submitted_bytes: int = 0


class StreamingSpeaker:
    """Serialize SDK calls and discard interrupted responses, including PC1's FIFO."""

    def __init__(self, stopping, on_error, chunk_ms=1000, gain=1.5, on_event=None,
                 on_reference=None):
        if not 200 <= chunk_ms <= 3000 or not 0 < gain <= 4:
            raise ValueError("Speaker chunk must be 200..3000 ms and gain in (0, 4]")
        self.stopping, self.on_error = stopping, on_error
        self.on_event = on_event
        self.on_reference = on_reference
        self.chunk_bytes = RATE * 2 * chunk_ms // 1000
        self.gain = gain
        self.condition = threading.Condition()
        self.pending = deque()
        self.responses = {}
        self.generation = self.buffered_bytes = 0
        self.stop_reason = "server_vad"
        self.thread = None
        self.ready = threading.Event()
        self.submitted_bytes = 0
        self._playback_until = 0.0
        self._submitting = False
        self._playback_generation = self.generation
        self.app_name = f"guidebot-live-{time.time_ns()}"

    def is_playing(self):
        with self.condition:
            if self._playback_generation != self.generation:
                return False
            # Include the in-flight RPC and a small allowance for PC1 buffering.
            return self._submitting or (self._playback_until > 0 and
                                       time.monotonic() < self._playback_until + .2)

    def _emit(self, kind, entry=None, **details):
        if self.on_event is not None:
            if entry is not None:
                details.update(response_id=entry.response_id,
                               received_ms=entry.received_bytes / 32,
                               submitted_ms=entry.submitted_bytes / 32)
            self.on_event(kind, **details)

    def start(self):
        self.thread = threading.Thread(target=self._run, name="g1-speaker", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        while not self.ready.wait(0.05):
            if self.stopping.is_set():
                return False
            if time.monotonic() > deadline:
                raise RuntimeError("G1 speaker did not initialize within 5s")
        return not self.stopping.is_set()

    def feed(self, response_id, pcm):
        if not pcm or len(pcm) % 2:
            raise ValueError("Invalid reply PCM16 chunk")
        with self.condition:
            entry = self.responses.get(response_id)
            if entry is None:
                entry = _ResponseAudio(response_id)
                self.pending.append(entry)
                self.responses[response_id] = entry
            converted, entry.resample_state = audioop.ratecv(
                pcm, 2, 1, CLOUD_RATE, RATE, entry.resample_state)
            # Fixed gain avoids amplifying quiet/noisy blocks independently.
            samples = np.frombuffer(converted, dtype="<i2").astype(np.float64)
            converted = np.clip(np.rint(samples * self.gain), -29204, 29204).astype("<i2").tobytes()
            if self.buffered_bytes + len(converted) > RATE * 2 * 30:
                raise RuntimeError("Speaker buffer exceeds 30s; stopping to avoid stale playback")
            entry.data.extend(converted)
            entry.received_bytes += len(converted)
            self.buffered_bytes += len(converted)
            self.condition.notify_all()
            return converted

    def finish(self, response_id):
        with self.condition:
            if response_id in self.responses:
                self.responses[response_id].done = True
            self.condition.notify_all()

    def interrupt(self):
        with self.condition:
            entries = list(self.pending)
            self.pending.clear()
            self.responses.clear()
            self.buffered_bytes = 0
            self.generation += 1
            self.stop_reason = "server_vad"
            self.condition.notify_all()
        for entry in entries:
            self._emit("playback.discard_requested", entry, reason="server_vad")

    def cancel(self, response_id, reason):
        with self.condition:
            entry = self.responses.pop(response_id, None)
            if entry is None:
                return
            if self.pending[0] is entry:
                self.generation += 1
                self.stop_reason = reason
            self.pending.remove(entry)
            self.buffered_bytes -= len(entry.data)
            self.condition.notify_all()
        self._emit("playback.discard_requested", entry, reason=reason)

    def close(self):
        self.stopping.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=6)
            if self.thread.is_alive():
                raise RuntimeError("Speaker worker did not stop within 6s")

    def _run(self):
        client = None
        submitted = False
        playing_entry = None
        try:
            ChannelFactoryInitialize, AudioClient = load_audio_sdk()

            if self.stopping.is_set():
                return
            ChannelFactoryInitialize(0, "eth0")
            client = AudioClient()
            client.SetTimeout(2)
            client.Init()
            volume = client.GetVolume()
            if self.on_event is None:
                print("G1 speaker volume (read only):", volume, flush=True)
            else:
                self._emit("playback.ready", volume=volume)
            self.ready.set()
            generation = self.generation
            playback_until = 0.0
            while not self.stopping.is_set():
                with self.condition:
                    if generation != self.generation:
                        generation = self.generation
                        action = "stop"
                        reason = self.stop_reason
                    elif not self.pending:
                        self.condition.wait(0.2)
                        continue
                    else:
                        entry = self.pending[0]
                        now = time.monotonic()
                        # Keep at most roughly one chunk queued on PC1.
                        if playback_until > now + 0.2:
                            self.condition.wait(min(0.2, playback_until - now - 0.2))
                            continue
                        if len(entry.data) >= self.chunk_bytes or (entry.done and entry.data):
                            chunk = bytes(entry.data[:self.chunk_bytes])
                            del entry.data[:len(chunk)]
                            self.buffered_bytes -= len(chunk)
                            stream_id = entry.stream_id
                            action = "play"
                        elif entry.done:
                            if playback_until > now:
                                self.condition.wait(min(0.2, playback_until - now))
                                continue
                            self.pending.popleft()
                            del self.responses[entry.response_id]
                            action = "drained"
                        else:
                            self.condition.wait(0.2)
                            continue
                if action == "stop":
                    if submitted:
                        client.PlayStop(self.app_name)
                        submitted = False
                        self._emit("playback.stopped", playing_entry, reason=reason)
                    playback_until = 0.0
                    with self.condition:
                        self._playback_until = 0.0
                elif action == "drained":
                    # PC1 has no playback-complete callback. Do not cut its FIFO
                    # based on a local clock: device startup/buffering can run late.
                    self._emit("playback.drained_estimated", entry)
                    playback_until = 0.0
                else:
                    if self.stopping.is_set():
                        break
                    with self.condition:
                        if generation != self.generation:
                            continue
                        self._playback_generation = generation
                        self._submitting = True
                    rpc_started = time.monotonic()
                    code, _ = client.PlayStream(self.app_name, stream_id, chunk)
                    rpc_finished = time.monotonic()
                    submitted = True
                    if self.on_reference is not None:
                        self.on_reference(chunk, rpc_started, response_id=entry.response_id,
                                          rpc_finished=rpc_finished, code=code)
                    if code != 0:
                        raise RuntimeError(f"G1 PlayStream failed (code={code})")
                    first_chunk = entry.submitted_bytes == 0
                    entry.submitted_bytes += len(chunk)
                    self.submitted_bytes += len(chunk)
                    playing_entry = entry
                    playback_until = max(playback_until, time.monotonic()) + len(chunk) / (RATE * 2)
                    with self.condition:
                        self._playback_until = playback_until
                        self._submitting = False
                    if first_chunk:
                        self._emit("playback.started", entry)
                    self._emit("playback.chunk_submitted", entry, chunk_bytes=len(chunk))
        except Exception as error:
            self.on_error(error)
        finally:
            if client is not None and submitted:
                try:
                    client.PlayStop(self.app_name)
                    self._emit("playback.stopped", playing_entry, reason="session_end")
                except Exception as error:
                    self.on_error(error)
            with self.condition:
                self._playback_until = 0.0
                self._submitting = False


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
    import sys
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError) as error:
        sys.exit(str(error))
