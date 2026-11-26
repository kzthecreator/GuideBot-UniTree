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
import tempfile
import time
import wave

import numpy as np
import soundfile as sf

RATE = 16000
CLOUD_RATE = 24000


from GuideBot.robot.audio.runtime import load_audio_sdk, microphone_packets
from runtime.telemetry.audio_sink import AudioDiagnostic
from GuideBot.conversation.playback import (StreamingSpeaker, SpeakerBacklogExceeded, _PCMSpool, _ResponseAudio)

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
