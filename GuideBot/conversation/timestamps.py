"""Experimental incremental FunASR alignment, isolated from realtime audio I/O.

Input is the final mono PCM16 at 16 kHz. Output indices are zero-based text
units; start/end are seconds from this response's first audio sample, not DAC
times. Provisional snapshots may be replaced or retracted by later versions.
"""

from collections import OrderedDict
import contextlib
from dataclasses import dataclass, field
import multiprocessing
import os
from pathlib import Path
import queue
import re
import threading
import time

RATE = 16000
MODEL_PATH = Path(os.environ.get("G1_TIMESTAMP_MODEL", Path.home() / ".local/share/guidebot/deps/funasr-fa-zh"))


def text_units(text):
    """Chinese characters and Latin words; offsets refer to the original text."""
    return [{"text": m.group(), "text_offset": m.start()} for m in
            re.finditer(r"[\u3400-\u9fff]|[A-Za-z]+(?:'[A-Za-z]+)?|[0-9]+", text)]


class MonotonicBackend:
    def __init__(self, model_path=MODEL_PATH, threads=2):
        import torch
        from funasr import AutoModel
        if not (Path(model_path) / "model.pt").is_file():
            raise FileNotFoundError(f"Timestamp model not installed: {model_path}")
        torch.set_num_threads(threads)
        self.torch = torch
        self.model = AutoModel(model=str(model_path), device="cpu", ncpu=threads,
                               disable_update=True, disable_pbar=True)

    def align(self, pcm, labels, final=False):
        import numpy as np
        from funasr.utils.load_utils import extract_fbank
        from funasr.utils.timestamp_tools import ts_prediction_lfr6_standard
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        with self.torch.inference_mode():
            features, lengths = extract_fbank([audio], frontend=self.model.kwargs["frontend"])
            encoded, encoded_lengths = self.model.model.encode(features, lengths)
            if final:
                count = len(labels)
                estimated = None
            else:
                _, _, alphas, _ = self.model.model.calc_predictor_timestamp(encoded, encoded_lengths, token_num=None)
                estimated = float(alphas.sum().item())
                count = min(len(labels), max(0, round(estimated) - 1))
            if not count:
                return [], estimated
            target = self.torch.tensor([count + 1], device=encoded.device)
            _, _, alphas, peaks = self.model.model.calc_predictor_timestamp(encoded, encoded_lengths, token_num=target)
            _, spans = ts_prediction_lfr6_standard(alphas[0, :encoded_lengths[0] * 3],
                                                   peaks[0, :encoded_lengths[0] * 3],
                                                   [u["text"] for u in labels[:count]])
        if len(spans) != count:
            raise RuntimeError(f"Timestamp count mismatch: {len(spans)} != {count}")
        duration = len(pcm) / (RATE * 2)
        rows = []
        for unit, (start, end) in zip(labels, spans):
            start, end = max(0, start / 1000), min(duration, end / 1000)
            if end <= start:
                raise RuntimeError("MonotonicAligner returned an empty interval")
            rows.append({**unit, "start": start, "end": end})
        return rows, estimated


@dataclass
class ResponseAlignment:
    response_id: str
    window: float = 6.
    step: float = 2.
    tail: float = 1.
    resync_every: float = 10.
    data: bytearray = field(default_factory=bytearray)
    text: str = ""
    done: bool = False
    last_samples: int = 0
    version: int = 0
    last_resync: float = 0.
    force_resync: bool = False
    latest: dict = field(default_factory=dict)

    def set_text(self, text):
        if self.text and text != self.text:
            self.latest.clear()
            self.last_samples = 0
            self.last_resync = 0.
            self.force_resync = False
        self.text = text

    def due(self):
        return bool(self.text and self.data and
                    (self.done or self.force_resync or
                     len(self.data) // 2 >= self.last_samples + round(self.step * RATE)))

    def update(self, backend):
        started = time.monotonic()
        available = len(self.data) / (RATE * 2)
        labels = text_units(self.text)
        if not labels:
            raise ValueError("Reply contains no supported text units")
        begin, cursor = 0., 0
        resync_reason = "order_conflict" if self.force_resync else "periodic"
        resync = not self.done and (self.force_resync or available - self.last_resync >= self.resync_every)
        if not self.done and not resync:
            anchors = [u for u in self.latest.values() if u["start"] <= available - self.window]
            if anchors:
                anchor = max(anchors, key=lambda u: u["index"])
                begin, cursor = max(0., anchor["start"] - .08), anchor["index"]
            if available - begin > self.window + 2:
                self.last_samples = len(self.data) // 2
                return {"kind": "alignment.warning", "response_id": self.response_id,
                        "reason": "cursor_lost", "audio_seconds": available,
                        "message": "Text cursor lost; waiting for complete-response repair"}
        rows, estimated = backend.align(bytes(self.data[round(begin * RATE) * 2:]), labels[cursor:], self.done)
        candidates = []
        for i, row in enumerate(rows):
            row = {**row, "index": cursor + i, "start": round(row["start"] + begin, 4),
                   "end": round(row["end"] + begin, 4)}
            if self.done or row["end"] <= available - self.tail:
                candidates.append(row)
        changes = []
        for row in candidates:
            old = self.latest.get(row["index"])
            if old:
                shift = max(abs(old["start"] - row["start"]), abs(old["end"] - row["end"]))
                if shift >= .001:
                    changes.append({"index": row["index"], "text": row["text"],
                                    "old_start": old["start"], "old_end": old["end"],
                                    "new_start": row["start"], "new_end": row["end"],
                                    "shift_ms": round(shift * 1000, 2)})
        previous_indices = set(self.latest)
        merged = {} if self.done or resync else dict(self.latest)
        merged.update((u["index"], u) for u in candidates)
        result = sorted(merged.values(), key=lambda u: u["index"])
        ordered = all(a["end"] <= b["start"] + .001 for a, b in zip(result, result[1:]))
        if not ordered:
            self.last_samples = len(self.data) // 2
            self.force_resync = True
            return {"kind": "alignment.warning", "response_id": self.response_id,
                    "reason": "order_conflict", "audio_seconds": available,
                    "message": "Conflicting window discarded; scheduling prefix repair"}
        self.latest = merged
        self.force_resync = False
        self.last_samples = len(self.data) // 2
        if resync:
            self.last_resync = available
        self.version += 1
        return {"kind": "alignment.final" if self.done else "alignment.update",
                "response_id": self.response_id, "version": self.version,
                "text": self.text,
                "provisional": not self.done, "audio_seconds": available,
                "scope": "final_repair" if self.done else "prefix_resync" if resync else "recent_window",
                "resync_reason": resync_reason if resync else None,
                "window_start": begin, "window_seconds": available - begin,
                "estimated_tokens": estimated, "compute_seconds": time.monotonic() - started,
                "total_units": len(labels), "timestamps": result, "changes": changes,
                "added_indices": [u["index"] for u in candidates if u["index"] not in previous_indices],
                "removed_indices": sorted(previous_indices - set(self.latest)),
                "ordered": ordered,
                "mixed_text": bool(re.search(r"[A-Za-z0-9]", self.text))}


def _worker(incoming, outgoing, model_path, log_path):
    with open(log_path, "a", buffering=1) as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            backend = MonotonicBackend(model_path)
            outgoing.put({"kind": "alignment.ready"})
            states = OrderedDict()
            closed = set()
            while True:
                messages = []
                try:
                    messages.append(incoming.get(timeout=.05))
                    for _ in range(255):
                        messages.append(incoming.get_nowait())
                except queue.Empty:
                    pass
                for action, rid, payload in messages:
                    if action == "stop":
                        return
                    if action == "cancel":
                        states.pop(rid, None)
                        closed.add(rid)
                        if len(closed) > 512:
                            raise RuntimeError("Timestamp response limit reached; restart session")
                        continue
                    if rid in closed:
                        continue
                    if rid not in states:
                        if len(states) >= 8:
                            raise RuntimeError("Too many pending timestamp responses")
                        states[rid] = ResponseAlignment(rid)
                    state = states[rid]
                    if action == "audio":
                        if len(state.data) + len(payload) > RATE * 2 * 120:
                            outgoing.put({"kind": "alignment.warning", "response_id": rid,
                                          "reason": "audio_limit", "message": "Reply exceeds 120s timestamp limit"})
                            del states[rid]
                            closed.add(rid)
                            continue
                        state.data.extend(payload)
                    elif action == "text":
                        state.set_text(payload)
                    elif action == "done":
                        state.done = True
                # Audio deltas accumulated during inference are merged into one
                # latest snapshot; there is no FIFO of old inference windows.
                state = next((s for s in states.values() if s.due()), None)
                if state is None:
                    continue
                try:
                    outgoing.put(state.update(backend))
                except Exception as error:
                    state.last_samples = len(state.data) // 2
                    outgoing.put({"kind": "alignment.warning", "response_id": state.response_id,
                                  "reason": "inference_failed", "message": str(error)})
                if state.done:
                    states.pop(state.response_id, None)
                    closed.add(state.response_id)
        except BaseException as error:
            outgoing.put({"kind": "alignment.error", "message": str(error)})


class StreamingTimestamps:
    def __init__(self, directory, on_event, model_path=MODEL_PATH):
        self.directory, self.on_event, self.model_path = Path(directory), on_event, str(model_path)
        self.process = self.reader = None
        self.closing = threading.Event()
        self.cancelled = set()
        self.enabled = False

    def start(self):
        context = multiprocessing.get_context("spawn")
        self.incoming, self.outgoing = context.Queue(maxsize=256), context.Queue(maxsize=128)
        self.process = context.Process(target=_worker, args=(self.incoming, self.outgoing, self.model_path,
                                       str(self.directory / "alignment-worker.log")), daemon=True)
        self.process.start()
        try:
            event = self.outgoing.get(timeout=60)
            if event["kind"] != "alignment.ready":
                raise RuntimeError(event.get("message", "Timestamp initialization failed"))
        except Exception:
            self.close()
            raise
        self.enabled = True
        self.on_event(**event)
        self.reader = threading.Thread(target=self._read, name="timestamp-results", daemon=True)
        self.reader.start()

    def _read(self):
        while not self.closing.is_set():
            try:
                event = self.outgoing.get(timeout=.2)
            except queue.Empty:
                if not self.process.is_alive() and not self.closing.is_set():
                    was_enabled = self.enabled
                    self.enabled = False
                    if was_enabled:
                        self.on_event(kind="alignment.error", message="Timestamp worker exited")
                    return
                continue
            if not self.enabled:
                continue
            if event.get("response_id") in self.cancelled:
                continue
            if event["kind"] == "alignment.error":
                self.enabled = False
            try:
                self.on_event(**event)
            except Exception:
                # A failed observer must not block audio reception or playback.
                self.enabled = False
                return

    def send(self, action, response_id, payload=None):
        if not self.enabled or (response_id in self.cancelled and action != "cancel"):
            return
        if action == "cancel":
            self.cancelled.add(response_id)
        try:
            self.incoming.put_nowait((action, response_id, payload))
        except queue.Full:
            self.enabled = False
            self.on_event(kind="alignment.error", message="Timestamp input overflow; audio continues")

    def close(self):
        if self.closing.is_set():
            return
        self.enabled = False
        self.closing.set()
        if self.process is not None:
            try:
                self.incoming.put_nowait(("stop", "", None))
            except queue.Full:
                pass
            self.process.join(timeout=3)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)
        if self.reader is not None and self.reader is not threading.current_thread():
            self.reader.join(timeout=2)
        if self.process is not None:
            for channel in (self.incoming, self.outgoing):
                channel.cancel_join_thread()
                channel.close()
