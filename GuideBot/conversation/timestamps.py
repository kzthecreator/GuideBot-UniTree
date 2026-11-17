"""Experimental incremental FunASR alignment, isolated from realtime audio I/O.

Input is the final mono PCM16 at 16 kHz. Output indices are zero-based text
units; start/end are seconds from this response's first audio sample, not DAC
times. Provisional snapshots may be replaced or retracted by later versions.
"""

from collections import OrderedDict
import contextlib
import math
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
    def __init__(self, model_path=MODEL_PATH, threads=2, reuse_predictor=False, quantized=False,
                 count_offset=-1):
        import torch
        from funasr import AutoModel
        if not (Path(model_path) / "model.pt").is_file():
            raise FileNotFoundError(f"Timestamp model not installed: {model_path}")
        torch.set_num_threads(threads)
        self.torch = torch
        self.model = AutoModel(model=str(model_path), device="cpu", ncpu=threads,
                               disable_update=True, disable_pbar=True)
        self.reuse_predictor = reuse_predictor
        self.count_offset = count_offset
        if reuse_predictor and type(self.model.model.predictor).__name__ != 'CifPredictorV3':
            raise ValueError('Predictor reuse is only validated for CifPredictorV3')
        if quantized:
            self.model.model = torch.ao.quantization.quantize_dynamic(
                self.model.model, {torch.nn.Linear, torch.nn.LSTM}, dtype=torch.qint8, inplace=False)

    def align(self, pcm, labels, final=False):
        started, cpu_started = time.monotonic(), time.process_time()
        self.last_profile = {}
        import numpy as np
        from funasr.utils.load_utils import extract_fbank
        from funasr.utils.timestamp_tools import ts_prediction_lfr6_standard
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        self.last_profile['pcm_seconds'] = time.monotonic() - started
        with self.torch.inference_mode():
            stage = time.monotonic()
            features, lengths = extract_fbank([audio], frontend=self.model.kwargs["frontend"])
            self.last_profile['frontend_seconds'] = time.monotonic() - stage
            self.last_profile['feature_frames'] = int(lengths.reshape(-1)[0].item())
            stage = time.monotonic()
            encoded, encoded_lengths = self.model.model.encode(features, lengths)
            self.last_profile['encoder_seconds'] = time.monotonic() - stage
            stage = time.monotonic()
            if final:
                count = len(labels)
                estimated = None
            else:
                _, _, alphas, _ = self.model.model.calc_predictor_timestamp(encoded, encoded_lengths, token_num=None)
                estimated = float(alphas.sum().item())
                count = min(len(labels), max(0, round(estimated) + self.count_offset))
            self.last_profile['count_seconds'] = time.monotonic() - stage
            self.last_profile['input_units'] = len(labels)
            self.last_profile['output_units'] = count
            if not count:
                self.last_profile.update(wall_seconds=time.monotonic()-started,
                                         process_cpu_seconds=time.process_time()-cpu_started)
                return [], estimated
            target = self.torch.tensor([count + 1], device=encoded.device)
            stage = time.monotonic()
            if self.reuse_predictor and not final:
                from funasr.models.bicif_paraformer.cif_predictor import cif_wo_hidden
                # The second upstream call only changes alpha normalization.
                # Reuse this window's unnormalized alphas, never another window.
                alphas = alphas.clone()
                alphas *= (target / alphas.sum(-1))[:, None].repeat(1, alphas.size(1))
                peaks = cif_wo_hidden(alphas, self.model.model.predictor.threshold-1e-4)
            else:
                _, _, alphas, peaks = self.model.model.calc_predictor_timestamp(encoded, encoded_lengths, token_num=target)
            self.last_profile['boundary_predictor_seconds'] = time.monotonic() - stage
            stage = time.monotonic()
            _, spans = ts_prediction_lfr6_standard(alphas[0, :encoded_lengths[0] * 3],
                                                   peaks[0, :encoded_lengths[0] * 3],
                                                   [u["text"] for u in labels[:count]])
            self.last_profile['timestamp_decode_seconds'] = time.monotonic() - stage
        stage = time.monotonic()
        if len(spans) != count:
            raise RuntimeError(f"Timestamp count mismatch: {len(spans)} != {count}")
        duration = len(pcm) / (RATE * 2)
        rows = []
        for unit, (start, end) in zip(labels, spans):
            start, end = max(0, start / 1000), min(duration, end / 1000)
            if end <= start:
                raise RuntimeError("MonotonicAligner returned an empty interval")
            rows.append({**unit, "start": start, "end": end})
        self.last_profile['row_seconds'] = time.monotonic() - stage
        self.last_profile.update(wall_seconds=time.monotonic()-started,
                                 process_cpu_seconds=time.process_time()-cpu_started)
        return rows, estimated


@dataclass
class ResponseAlignment:
    response_id: str
    window: float = 6.
    step: float = 2.
    tail: float = 1.
    resync_every: float = 10.
    final_repair: bool = True
    cursor_from_starts: bool = False
    data: bytearray = field(default_factory=bytearray)
    text: str = ""
    done: bool = False
    last_samples: int = 0
    version: int = 0
    last_resync: float = 0.
    force_resync: bool = False
    latest: dict = field(default_factory=dict)
    latest_starts: dict = field(default_factory=dict)
    start_version: int = 0
    text_pending: bool = False
    removed_starts: set = field(default_factory=set)
    text_revision: int = 0
    newest_audio_sent_at: float = None
    last_profile: dict = field(default_factory=dict, init=False)

    def set_text(self, text):
        if text == self.text:
            return
        self.text_revision += 1
        old_units, new_units = text_units(self.text), text_units(text)
        common = 0
        for old, new in zip(old_units, new_units):
            if old != new:
                break
            common += 1
        if self.text and not text.startswith(self.text):
            common = 0
        self.latest = {i: row for i, row in self.latest.items() if i < common}
        self.removed_starts.update(i for i in self.latest_starts if i >= common)
        self.latest_starts = {i: row for i, row in self.latest_starts.items() if i < common}
        if self.text and common == 0:
            self.last_samples = 0
            self.last_resync = 0.
            self.force_resync = False
        self.text = text
        self.text_pending = True

    def due(self):
        return bool(self.text and self.data and
                    (self.done or self.force_resync or
                     (self.text_pending and self.last_samples > 0) or
                     len(self.data) // 2 >= self.last_samples + round(self.step * RATE)))

    def update_starts(self, rows, available, replace, compute_started):
        previous = dict(self.latest_starts)
        merged = {} if replace else dict(previous)
        merged.update((row['index'], {key: row[key] for key in ('index', 'text', 'text_offset', 'start')})
                      for row in rows if self.done or row['start'] <= available - self.tail)
        anchors = sorted(merged.values(), key=lambda row: row['index'])
        if any(a['start'] > b['start'] for a, b in zip(anchors, anchors[1:])):
            return None
        if merged == previous and not self.removed_starts and not self.done:
            return None
        self.latest_starts = merged
        self.start_version += 1
        removed = sorted((set(previous) - set(merged)) | self.removed_starts)
        self.removed_starts.clear()
        return {'kind': 'alignment.starts', 'response_id': self.response_id,
                'version': self.start_version, 'provisional': not self.done,
                'audio_seconds': available, 'anchors': anchors,
                'added_indices': sorted(set(merged) - set(previous)), 'removed_indices': removed,
                'changes': [{'index': i, 'old_start': previous[i]['start'], 'new_start': row['start'],
                             'shift_ms': round(abs(row['start'] - previous[i]['start']) * 1000, 2)}
                            for i, row in merged.items() if i in previous and row != previous[i]],
                'compute_seconds': time.monotonic() - compute_started,
                'total_units': len(text_units(self.text))}

    def update(self, backend):
        started = time.monotonic()
        self.last_profile = dict(inference_ran=False, text_revision=self.text_revision,
                                 audio_seconds=len(self.data)/(RATE*2),
                                 new_audio_seconds=(len(self.data)//2-self.last_samples)/RATE)
        if self.newest_audio_sent_at is not None:
            self.last_profile['newest_audio_queue_wait_seconds'] = max(0., started-self.newest_audio_sent_at)
        try:
            result = self._update(backend)
        finally:
            self.last_profile['update_seconds'] = time.monotonic()-started
        result['profile'] = dict(self.last_profile)
        return result

    def _update(self, backend):
        if self.done and not self.final_repair:
            # Close with one ordinary window, retaining its provisional nature.
            self.done = False
            try:
                result = self._update(backend)
            finally:
                self.done = True
            result.update(kind='alignment.final', scope='final_window', provisional=True,
                          full_repair=False, total_units=len(text_units(self.text)))
            result.setdefault('timestamps', sorted(self.latest.values(), key=lambda row: row['index']))
            result.setdefault('changes', [])
            result.setdefault('ordered', True)
            return result
        started = time.monotonic()
        self.text_pending = False
        available = len(self.data) / (RATE * 2)
        labels = text_units(self.text)
        if not labels:
            raise ValueError("Reply contains no supported text units")
        begin, cursor = 0., 0
        resync_reason = "order_conflict" if self.force_resync else "periodic"
        resync = (not self.done and self.resync_every > 0 and
                  (self.force_resync or available - self.last_resync >= self.resync_every))
        if not self.done and not resync:
            history = self.latest_starts if self.cursor_from_starts else self.latest
            anchors = [u for u in history.values() if u["start"] <= available - self.window]
            if anchors:
                anchor = max(anchors, key=lambda u: u["index"])
                begin, cursor = max(0., anchor["start"] - .08), anchor["index"]
            if available - begin > self.window + 2:
                self.last_samples = len(self.data) // 2
                return {"kind": "alignment.warning", "response_id": self.response_id,
                        "reason": "cursor_lost", "audio_seconds": available,
                        "message": "Text cursor lost; waiting for complete-response repair"}
        self.last_profile.update(window_start=begin, window_seconds=available-begin,
                                 cursor=cursor, input_units=len(labels)-cursor,
                                 prepare_seconds=time.monotonic()-started, inference_ran=True)
        inference_started = time.monotonic()
        try:
            rows, estimated = backend.align(bytes(self.data[round(begin * RATE) * 2:]), labels[cursor:], self.done)
        finally:
            self.last_profile['backend_seconds'] = time.monotonic()-inference_started
            backend_profile = getattr(backend, 'last_profile', None)
            if isinstance(backend_profile, dict):
                self.last_profile['backend'] = dict(backend_profile)
        merge_started = time.monotonic()
        candidates, absolute_rows = [], []
        for i, row in enumerate(rows):
            row = {**row, "index": cursor + i, "start": round(row["start"] + begin, 4),
                   "end": round(row["end"] + begin, 4)}
            absolute_rows.append(row)
            if self.done or row["end"] <= available - self.tail:
                candidates.append(row)
        start_update = self.update_starts(absolute_rows, available, self.done or resync, started)
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
            self.last_profile['merge_seconds'] = time.monotonic()-merge_started
            self.last_samples = len(self.data) // 2
            self.force_resync = self.resync_every > 0
            return {"kind": "alignment.warning", "response_id": self.response_id,
                    "reason": "order_conflict", "audio_seconds": available,
                    "start_update": start_update,
                    "message": ("Conflicting window discarded; scheduling prefix repair" if self.force_resync
                                else "Conflicting window discarded; prefix repair disabled")}
        self.latest = merged
        self.force_resync = False
        self.last_samples = len(self.data) // 2
        if resync:
            self.last_resync = available
        self.version += 1
        self.last_profile['merge_seconds'] = time.monotonic()-merge_started
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
                "start_update": start_update,
                "mixed_text": bool(re.search(r"[A-Za-z0-9]", self.text))}


def _worker(incoming, outgoing, model_path, log_path, alignment_options=None, backend_options=None):
    with open(log_path, "a", buffering=1) as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        try:
            backend = MonotonicBackend(model_path, **(backend_options or {}))
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
                audio_messages = {}
                for action, rid, payload, sent_at in messages:
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
                        states[rid] = ResponseAlignment(rid, **(alignment_options or {}))
                    state = states[rid]
                    if action == "audio":
                        audio_messages[rid] = audio_messages.get(rid, 0)+1
                        if len(state.data) + len(payload) > RATE * 2 * 120:
                            outgoing.put({"kind": "alignment.warning", "response_id": rid,
                                          "reason": "audio_limit", "message": "Reply exceeds 120s timestamp limit"})
                            del states[rid]
                            closed.add(rid)
                            continue
                        state.data.extend(payload)
                        state.newest_audio_sent_at = sent_at
                    elif action == "text":
                        state.set_text(payload)
                    elif action == "text_delta":
                        state.set_text(state.text + payload)
                    elif action == "done":
                        state.done = True
                # Audio deltas accumulated during inference are merged into one
                # latest snapshot; there is no FIFO of old inference windows.
                state = next((s for s in states.values() if s.due()), None)
                if state is None:
                    continue
                try:
                    result = state.update(backend)
                    result['profile']['batch_messages'] = len(messages)
                    result['profile']['batch_audio_messages'] = audio_messages.get(state.response_id, 0)
                    result['profile']['coalesced_step_thresholds'] = max(
                        0, math.floor(result['profile']['new_audio_seconds']/state.step)-1)
                    starts = result.pop("start_update", None)
                    if starts is not None:
                        outgoing.put(starts)
                    outgoing.put(result)
                except Exception as error:
                    state.last_samples = len(state.data) // 2
                    outgoing.put({"kind": "alignment.warning", "response_id": state.response_id,
                                  "reason": "inference_failed", "message": str(error),
                                  "profile": dict(state.last_profile)})
                if state.done:
                    states.pop(state.response_id, None)
                    closed.add(state.response_id)
        except BaseException as error:
            outgoing.put({"kind": "alignment.error", "message": str(error)})


class StreamingTimestamps:
    def __init__(self, directory, on_event, model_path=MODEL_PATH, *, alignment_options=None, backend_options=None):
        self.directory, self.on_event, self.model_path = Path(directory), on_event, str(model_path)
        self.alignment_options = dict(alignment_options or {})
        self.backend_options = dict(backend_options or {})
        for name, value in self.backend_options.items():
            if name in {'reuse_predictor', 'quantized'} and type(value) is bool:
                continue
            if name == 'threads' and type(value) is int and 1 <= value <= 8:
                continue
            if name == 'count_offset' and type(value) is int and -2 <= value <= 1:
                continue
            raise ValueError(f'Invalid backend option: {name}')
        for name, value in self.alignment_options.items():
            if name in {'final_repair', 'cursor_from_starts'}:
                if type(value) is not bool:
                    raise ValueError(f'{name} must be boolean')
                continue
            if name not in {"window", "step", "tail", "resync_every"}:
                raise ValueError(f"Unknown alignment option: {name}")
            if not math.isfinite(value) or value < 0 or (name in {"window", "step"} and value == 0):
                raise ValueError(f"Invalid alignment option: {name}={value}")
        self.process = self.reader = None
        self.closing = threading.Event()
        self.cancelled = set()
        self.enabled = False
        self.sent_audio_samples = {}

    def start(self, timeout=60):
        context = multiprocessing.get_context("spawn")
        self.incoming, self.outgoing = context.Queue(maxsize=256), context.Queue(maxsize=128)
        self.process = context.Process(target=_worker, args=(self.incoming, self.outgoing, self.model_path,
                                       str(self.directory / "alignment-worker.log"), self.alignment_options,
                                       self.backend_options), daemon=True)
        self.process.start()
        try:
            event = self.outgoing.get(timeout=timeout)
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
            if 'profile' in event:
                event['profile']['received_monotonic'] = time.monotonic()
                event['profile']['audio_ahead_of_snapshot_seconds'] = max(
                    0., self.sent_audio_samples.get(event.get('response_id'), 0)/RATE -
                    event['profile']['audio_seconds'])
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
            self.incoming.put_nowait((action, response_id, payload, time.monotonic()))
            if action == 'audio':
                self.sent_audio_samples[response_id] = self.sent_audio_samples.get(response_id, 0)+len(payload)//2
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
                self.incoming.put_nowait(("stop", "", None, time.monotonic()))
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
