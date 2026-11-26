"""Streaming reply queue, SDK pacing, interruption and playback reference."""
import audioop
from collections import deque
from dataclasses import dataclass, field
import threading
import tempfile
import time
import numpy as np
from GuideBot.robot.audio.runtime import load_audio_sdk

RATE = 16000
CLOUD_RATE = 24000

class SpeakerBacklogExceeded(RuntimeError):
    """Discard one pathological response, without stopping realtime reception."""

class _PCMSpool:
    """Small memory queue spilling to an anonymous temporary file, not a recording."""
    def __init__(self):
        self.file = tempfile.SpooledTemporaryFile(max_size=RATE*2*2, mode='w+b')
        self.read_offset = self.write_offset = 0

    def __len__(self):
        return self.write_offset-self.read_offset

    def __bytes__(self):
        # Read-only snapshot for diagnostics; normal playback uses take().
        position = self.file.tell()
        try:
            self.file.seek(self.read_offset)
            return self.file.read(len(self))
        finally:
            self.file.seek(position)

    @property
    def disk_backed(self):
        return bool(getattr(self.file, '_rolled', False))

    @property
    def closed(self):
        return self.file.closed

    def extend(self, data):
        self.file.seek(self.write_offset)
        self.file.write(data)
        self.write_offset += len(data)

    def take(self, size):
        self.file.seek(self.read_offset)
        result = self.file.read(min(size,len(self)))
        self.read_offset += len(result)
        if self.read_offset == self.write_offset:
            self.file.seek(0)
            self.file.truncate()
            self.read_offset = self.write_offset = 0
        return result

    def close(self):
        self.file.close()

@dataclass
class _ResponseAudio:
    response_id: str
    stream_id: str = field(default_factory=lambda: str(time.time_ns()))
    data: object = field(default_factory=_PCMSpool)
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

    def pending_response_ids(self):
        """Cloud completion does not mean locally queued audio has drained."""
        with self.condition:
            return set(self.responses)

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
            # A cloud burst can legitimately get >30s ahead of the real speaker.
            # Bound temporary storage without blocking the websocket/VAD receiver.
            if max(self.buffered_bytes, entry.received_bytes) + len(converted) > RATE * 2 * 300:
                raise SpeakerBacklogExceeded('Reply audio exceeds the 300s temporary storage limit')
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

    def interrupt(self, reason="server_vad"):
        with self.condition:
            entries = list(self.pending)
            self.pending.clear()
            self.responses.clear()
            self.buffered_bytes = 0
            self.generation += 1
            self.stop_reason = reason
            self.condition.notify_all()
        for entry in entries:
            entry.data.close()
            self._emit("playback.discard_requested", entry, reason=reason)

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
            entry.data.close()
            self.condition.notify_all()
        self._emit("playback.discard_requested", entry, reason=reason)

    def close(self):
        self.stopping.set()
        with self.condition:
            for entry in self.pending:
                entry.data.close()
            self.pending.clear()
            self.responses.clear()
            self.buffered_bytes = 0
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
            volume_code = client.SetVolume(100)
            if volume_code != 0:
                raise RuntimeError(f'G1 SetVolume(100) failed: {volume_code}')
            volume = client.GetVolume()
            if self.on_event is None:
                print("G1 speaker volume (requested 100%):", volume, flush=True)
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
                            chunk = entry.data.take(self.chunk_bytes)
                            self.buffered_bytes -= len(chunk)
                            stream_id = entry.stream_id
                            action = "play"
                        elif entry.done:
                            if playback_until > now:
                                self.condition.wait(min(0.2, playback_until - now))
                                continue
                            self.pending.popleft()
                            entry.data.close()
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
                for entry in self.pending:
                    entry.data.close()
                self.pending.clear()
                self.responses.clear()
                self.buffered_bytes = 0
