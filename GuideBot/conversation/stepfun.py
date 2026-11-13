"""Persistent StepAudio 3 Realtime session with concurrent G1 input and output."""

import audioop
import base64
import json
import queue
import threading
import time
from urllib.parse import urlencode
import uuid

import websocket

from audio import AudioDiagnostic, CLOUD_RATE, RATE, LevelGate, StreamingSpeaker, microphone_packets
from knowledge import read_soul
from localvqe import LocalVQEEcho
from timestamps import StreamingTimestamps

MODEL = "stepaudio-3-realtime-preview"
DEFAULT_DIAGNOSE_AUDIO = True
DEFAULT_VAD_ENERGY = 4999
DEFAULT_AEC = True
DEFAULT_AEC_DELAY_MS = 0
DEFAULT_MIC_GATE_DBFS = -35.


def make_event(kind, **fields):
    return {"event_id": f"evt_{uuid.uuid4().hex}", "type": kind, **fields}


class RealtimeSession:
    def __init__(self, secret, directory, voice=None, chunk_ms=1000, gain=1.5,
                 diagnose_audio=DEFAULT_DIAGNOSE_AUDIO, vad_energy=DEFAULT_VAD_ENERGY,
                 aec=DEFAULT_AEC, aec_delay_ms=DEFAULT_AEC_DELAY_MS,
                 mic_gate_dbfs=DEFAULT_MIC_GATE_DBFS, instructions=None, vector_store_id=None,
                 timestamps=False):
        if not 0 <= vad_energy <= 5000:
            raise ValueError("VAD energy threshold must be 0..5000")
        self.secret, self.directory = secret, directory
        self.instructions = read_soul() if instructions is None else instructions.strip()
        if not self.instructions:
            raise ValueError("Instructions must not be empty")
        self.vector_store_id = vector_store_id
        self.vad_energy = vad_energy
        self.gate = LevelGate(mic_gate_dbfs) if mic_gate_dbfs is not None else None
        self.echo = None
        self.aec_enabled, self.aec_delay_ms = aec, aec_delay_ms
        if not 0 <= aec_delay_ms <= 1000:
            raise ValueError("AEC delay must be 0..1000 ms")
        self.voice = voice
        self.diagnose_audio = diagnose_audio
        self.audio_diagnostic = None
        self.ready = threading.Event()
        self.stopping = threading.Event()
        self.lifecycle = threading.Lock()
        self.error_lock = threading.Lock()
        self.log_lock = threading.Lock()
        self.started_at = time.monotonic()
        self.current_turn = self.committed_turn = 0
        self.user_turns = {}
        self.confirmed_interruptions = set()
        self.response_turns = {}
        self.response_numbers = {}
        self.input_queue = queue.Queue(maxsize=100)
        self.speaker = StreamingSpeaker(self.stopping, self.fail, chunk_ms, gain,
                                        self._playback_event,
                                        self._speaker_reference if diagnose_audio or aec else None)
        self.active, self.discarded = set(), set()
        self.workers = []
        self.errors = []
        self.stats = {"microphone_packets": 0, "nonzero_packets": 0, "uploaded_bytes": 0,
                      "speech_starts": 0, "speech_stops": 0, "responses": [], "playback_events": []}
        self.session = None
        self.ws = self.thread = None
        self.log = None
        self.timestamp_log = None
        self.timestamp_stats = {"ready": False, "updates": 0, "finals": 0, "revisions": 0, "errors": []}
        self.playback_starts = {}
        self.timestamps = StreamingTimestamps(directory, self._alignment_event) if timestamps else None

    def _alignment_event(self, kind, **details):
        rid = details.get("response_id")
        rows = details.get("timestamps", [])
        changes = details.get("changes", [])
        if rid in self.playback_starts:
            playhead = max(0, time.monotonic() - self.playback_starts[rid])
            details["estimated_playhead_seconds"] = playhead
            details["new_units_after_estimated_start"] = sum(
                row["start"] < playhead for row in rows
                if row["index"] in details.get("added_indices", []))
        if kind in {"alignment.update", "alignment.final"}:
            self.timestamp_stats["finals" if kind == "alignment.final" else "updates"] += 1
            self.timestamp_stats["revisions"] += len(changes)
            state = ("最终修复" if kind == "alignment.final" else
                     "前缀重同步（暂定）" if details.get("scope") == "prefix_resync" else "暂定")
            shift = max((c["shift_ms"] for c in changes), default=0)
            message = (f"{state}字级时间戳 {len(rows)}/{details['total_units']}；"
                       f"计算 {details['compute_seconds']:.3f}s；修订 {len(changes)} 处，最大 {shift:g}ms")
            if not details.get("ordered", True):
                message += "；窗口合并存在顺序冲突，等待最终修复"
            if details.get("mixed_text"):
                message += "；含英文或数字，按文字单元实验性对齐"
        elif kind == "alignment.ready":
            self.timestamp_stats["ready"] = True
            message = "FunASR 后台对齐就绪：6s 窗口、2s 更新、1s 尾部保留、约10s前缀重同步；增量结果仅供实验"
        else:
            message = details.get("message", kind)
            self.timestamp_stats["errors"].append(message)
        with self.log_lock:
            if self.timestamp_log is not None and not self.timestamp_log.closed:
                self.timestamp_log.write(json.dumps({"elapsed": time.monotonic() - self.started_at,
                                                     "type": kind, **details}, ensure_ascii=False) + "\n")
                self.timestamp_log.flush()
        report_details = {key: value for key, value in details.items() if key != "message"}
        self.report(kind, message, **report_details)

    def _speaker_reference(self, pcm, started_at, **details):
        if self.echo is not None and details.get("code") == 0:
            self.echo.add_reference(pcm, started_at)
        if self.audio_diagnostic is not None:
            finished = details.pop("rpc_finished")
            self.audio_diagnostic.write("speaker", pcm, started_at,
                                        rpc_finished_elapsed=finished - self.started_at, **details)

    def _write_log(self, kind, **details):
        if self.log is not None and not self.log.closed:
            self.log.write(json.dumps({"time": time.time(), "elapsed": time.monotonic() - self.started_at,
                                       "type": kind, **details}, ensure_ascii=False) + "\n")
            self.log.flush()

    def report(self, stage, message, turn=None, response_id=None, **details):
        with self.log_lock:
            label = ""
            if response_id:
                label = f"R{self.response_numbers.get(response_id, '?')}"
                turn = self.response_turns.get(response_id, turn)
            if turn:
                label += ("/" if label else "") + f"U{turn}"
            elapsed = time.monotonic() - self.started_at
            print(f"[+{elapsed:07.3f}s][{label or 'session'}][{stage}] {message}", flush=True)
            self._write_log("client." + stage, message=message, turn=turn,
                            response_id=response_id, **details)

    def _playback_event(self, kind, **details):
        if kind == "playback.stopped" and self.echo is not None:
            self.echo.stop_reference(time.monotonic())
        rid = details.get("response_id")
        if kind == "playback.started":
            self.playback_starts[rid] = time.monotonic()
        if kind == "playback.discard_requested" and self.timestamps is not None:
            self.timestamps.send("cancel", rid)
        if kind == "playback.chunk_submitted":
            with self.log_lock:
                self._write_log(kind, **details)
            return
        self.stats["playback_events"].append({"elapsed": time.monotonic() - self.started_at,
                                              "type": kind, **details})
        messages = {
            "playback.ready": f"扬声器就绪，音量只读：{details.get('volume')}",
            "playback.started": "开始向扬声器提交回复音频",
            "playback.drained_estimated": f"已提交 {details.get('submitted_ms', 0) / 1000:.2f}s 音频，预计已播完（无设备结束回执）",
            "playback.discard_requested": f"请求丢弃剩余回复，原因：{details.get('reason')}",
            "playback.stopped": f"已调用 SDK 停止播放，原因：{details.get('reason')}",
        }
        self.report(kind, messages[kind], **details)

    def start(self):
        if self.thread is not None:
            raise RuntimeError("Create a new RealtimeSession for each conversation")
        if not self.secret:
            raise ValueError("STEP_SECRET is required")
        if not self.vector_store_id:
            raise ValueError("A successfully synchronized knowledge base is required")
        self.started_at = time.monotonic()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.aec_enabled:
            self.echo = LocalVQEEcho(self.aec_delay_ms)
        if self.diagnose_audio:
            self.audio_diagnostic = AudioDiagnostic(self.directory, self.started_at,
                                                    processed=self.aec_enabled,
                                                    gated=self.gate is not None)
        self.log = (self.directory / "events.jsonl").open("w", encoding="utf-8")
        if self.timestamps is not None:
            self.timestamp_log = (self.directory / "alignment.jsonl").open("w", encoding="utf-8")
            try:
                self.timestamps.start()
            except Exception as error:
                self._alignment_event("alignment.error", message=f"Timestamp worker disabled: {error}; audio continues")
        websocket.setdefaulttimeout(5)
        self.ws = websocket.WebSocketApp(
            "wss://api.stepfun.com/v1/realtime?" + urlencode({"model": MODEL}),
            header=[f"Authorization: Bearer {self.secret}"],
            on_open=lambda ws: self._close_socket() if self.stopping.is_set() else None,
            on_message=lambda ws, message: self.on_event(json.loads(message)),
            on_error=lambda ws, error: self._socket_error(error),
            on_close=self._on_close,
        )
        self.thread = threading.Thread(target=self._run_socket, name="stepfun-realtime", daemon=True)
        self.thread.start()

    def _send(self, kind, **fields):
        if not self.stopping.is_set():
            self.ws.send(json.dumps(make_event(kind, **fields), ensure_ascii=False))
            return True
        return False

    def _socket_error(self, error):
        if not self.stopping.is_set():
            self.fail(error)

    def _close_socket(self):
        if self.ws is None:
            return
        self.ws.keep_running = False
        connection = self.ws.sock
        # Wake the receiver before close() tries to read its close handshake.
        if connection is not None:
            try:
                connection.abort()
            except OSError:
                pass
        self.ws.close(timeout=0.5)

    def _run_socket(self):
        try:
            self.ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as error:
            self._socket_error(error)
        finally:
            self.stopping.set()

    def _on_close(self, ws, code, reason):
        if not self.stopping.is_set():
            self.fail(RuntimeError(f"Realtime connection closed (code={code})"))

    def fail(self, error):
        message = str(error).replace(self.secret, "[redacted]") if self.secret else str(error)
        with self.error_lock:
            if message not in self.errors:
                self.errors.append(message)
                self.report("error", message)
        self.stopping.set()
        self._close_socket()

    def _capture(self):
        state = None
        pending = bytearray()
        try:
            for pcm in microphone_packets(self.stopping, self.stats):
                received_at = time.monotonic()
                if self.audio_diagnostic is not None:
                    self.audio_diagnostic.write("microphone", pcm, received_at)
                if self.echo is not None:
                    pcm = self.echo.process(pcm, received_at)
                    if self.audio_diagnostic is not None:
                        self.audio_diagnostic.write("microphone-aec", pcm, received_at)
                if self.gate is not None:
                    pcm = self.gate.process(pcm, enabled=self.speaker.is_playing())
                    if self.audio_diagnostic is not None:
                        self.audio_diagnostic.write("microphone-gated", pcm, received_at)
                converted, state = audioop.ratecv(pcm, 2, 1, RATE, CLOUD_RATE, state)
                pending.extend(converted)
                while len(pending) >= 960 and not self.stopping.is_set():
                    self.input_queue.put_nowait(bytes(pending[:960]))
                    del pending[:960]
        except queue.Full:
            self.fail(RuntimeError("Microphone upload queue exceeds 2s; stopping instead of sending stale audio"))
        except Exception as error:
            if not self.stopping.is_set():
                self.fail(error)

    def _send_microphone(self):
        try:
            while not self.stopping.is_set():
                try:
                    pcm = self.input_queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                if self._send("input_audio_buffer.append", audio=base64.b64encode(pcm).decode("ascii")):
                    self.stats["uploaded_bytes"] += len(pcm)
        except Exception as error:
            self._socket_error(error)

    def on_event(self, event):
        if self.stopping.is_set():
            return
        try:
            kind = event["type"]
            # Server streams are asynchronous; record arrival order without
            # presenting cloud completion as physical playback completion.
            record = {key: event[key] for key in ("response_id", "item_id", "transcript",
                                                 "audio_start_ms", "audio_end_ms") if key in event}
            if "response" in event:
                record["response_id"] = event["response"].get("id")
                record["status"] = event["response"].get("status")
            raw_audio = None
            if kind == "response.audio.delta":
                raw_audio = base64.b64decode(event["delta"], validate=True)
                record["audio_bytes"] = len(raw_audio)
            with self.log_lock:
                self._write_log(kind, **record)
            if kind == "session.created":
                settings = {
                    "modalities": ["text", "audio"], "instructions": self.instructions,
                    "input_audio_format": "pcm16", "output_audio_format": "pcm16",
                    "turn_detection": {"type": "server_vad", "prefix_padding_ms": 500,
                                       "silence_duration_ms": 300,
                                       "energy_awakeness_threshold": self.vad_energy},
                }
                if self.vector_store_id:
                    settings["tools"] = [{
                        "type": "retrieval",
                        "function": {
                            "name": "guidebot_knowledge",
                            "description": "检索本地 knowledge 目录发布的项目知识、场所介绍、业务事实与常见问题。",
                            "options": {
                                "vector_store_id": self.vector_store_id,
                                "prompt_template": "参考资料：{{knowledge}}。用户问题：{{query}}。"
                                                   "仅根据相关资料回答；未找到时明确说明，不编造。"
                            }
                        }
                    }]
                if self.voice:
                    settings["voice"] = self.voice
                self._send("session.update", session=settings)
            elif kind == "session.updated" and not self.ready.is_set():
                self.session = event["session"]
                if self.session.get("model", MODEL) != MODEL:
                    raise RuntimeError("Server returned an unexpected model")
                actual_type = (self.session.get("turn_detection") or {}).get("type")
                if actual_type != "server_vad":
                    raise RuntimeError("Server did not enable server_vad")
                if self.vector_store_id:
                    tools = self.session.get("tools") or []
                    if not any(tool.get("type") == "retrieval" and
                               tool.get("function", {}).get("options", {}).get("vector_store_id")
                               == self.vector_store_id for tool in tools):
                        raise RuntimeError("Server did not confirm the retrieval knowledge base; "
                                           "microphone was not started")
                with self.lifecycle:
                    if self.stopping.is_set():
                        return
                    if not self.speaker.start() or self.stopping.is_set():
                        return
                    self.workers = [threading.Thread(target=target, name=name, daemon=True)
                                    for target, name in [(self._capture, "g1-microphone"),
                                                         (self._send_microphone, "stepfun-upload")]]
                    for worker in self.workers:
                        worker.start()
                    self.ready.set()
                actual_vad = self.session.get("turn_detection") or {}
                self.report("ready", f"{MODEL} 已就绪。可以说话，按 Enter 结束。"
                            f" VAD 门槛={actual_vad.get('energy_awakeness_threshold', '未回显')}；等待确认事件后打断。")
            elif kind == "input_audio_buffer.speech_started":
                self.stats["speech_starts"] += 1
                self.current_turn += 1
                self.user_turns[event.get("item_id")] = self.current_turn
                self.report("VAD-start", "检测到候选人声；继续播放，等待云端确认是否打断", turn=self.current_turn)
            elif kind == "input_audio_buffer.speech_interrupted":
                item_id = event.get("item_id")
                if item_id in self.confirmed_interruptions:
                    return
                self.confirmed_interruptions.add(item_id)
                self.report("VAD-interrupt", "云端确认打断，停止旧回复；麦克风继续上传",
                            turn=self.user_turns.get(item_id, self.current_turn))
                self.discarded.update(self.active)
                if self.timestamps is not None:
                    for rid in self.active:
                        self.timestamps.send("cancel", rid)
                self.speaker.interrupt()
            elif kind == "input_audio_buffer.speech_backchannel":
                self.report("VAD-backchannel", "云端判为 backchannel，保留旧回复；本次未产生正式输入结束事件",
                            turn=self.user_turns.get(event.get("item_id"), self.current_turn))
            elif kind == "input_audio_buffer.speech_stopped":
                self.stats["speech_stops"] += 1
                self.report("VAD-end", "云端检测到停顿，等待回复", turn=self.user_turns.get(event.get("item_id"), self.current_turn))
            elif kind == "input_audio_buffer.committed":
                self.committed_turn = self.user_turns.get(event.get("item_id"), self.current_turn)
            elif kind == "conversation.item.input_audio_transcription.completed":
                self.report("ASR-final", "User: " + event.get("transcript", ""), turn=self.user_turns.get(event.get("item_id")))
            elif kind == "response.created":
                rid = event["response"]["id"]
                self.active.add(rid)
                self.response_numbers[rid] = len(self.response_numbers) + 1
                self.response_turns[rid] = self.committed_turn or self.current_turn
            elif kind == "response.done":
                response = event["response"]
                rid, status = response["id"], response.get("status")
                self.stats["responses"].append({"id": rid, "status": status})
                if status in {"completed", "incomplete"}:
                    self.speaker.finish(rid)
                    if self.timestamps is not None:
                        self.timestamps.send("done" if status == "completed" else "cancel", rid)
                elif status in {"cancelled", "interrupted"}:
                    if self.timestamps is not None:
                        self.timestamps.send("cancel", rid)
                    if rid not in self.discarded:
                        self.speaker.cancel(rid, reason=f"cloud_{status}")
                else:
                    raise RuntimeError(f"Realtime response failed: {status}")
                self.active.discard(rid)
                self.discarded.discard(rid)
                self.report("cloud-done", f"云端生成结束：{status}；不代表扬声器已播完", response_id=rid)
            elif kind in {"response.audio.delta", "response.audio.done", "response.audio_transcript.done"}:
                rid = event.get("response_id")
                if not rid:
                    raise ValueError("Realtime response event is missing response_id")
                if rid not in self.active or rid in self.discarded:
                    return
                if kind == "response.audio.delta":
                    converted = self.speaker.feed(rid, raw_audio)
                    if self.timestamps is not None:
                        self.timestamps.send("audio", rid, converted)
                elif kind == "response.audio.done":
                    self.speaker.finish(rid)
                else:
                    if self.timestamps is not None:
                        self.timestamps.send("text", rid, event.get("transcript", ""))
                    self.report("reply-text", "回复文本已就绪：" + event.get("transcript", ""), response_id=rid)
            elif kind in {"error", "conversation.item.input_audio_transcription.failed"}:
                detail = event.get("error", {})
                raise RuntimeError(f"Stepfun: {detail.get('code', '')} {detail.get('message', 'Request failed')}")
        except Exception as error:
            self.fail(error)

    def stop(self):
        self.stopping.set()
        self._close_socket()
        with self.lifecycle:
            workers = list(self.workers)
        for worker in workers + ([self.thread] if self.thread is not None else []):
            if worker is not threading.current_thread():
                worker.join(timeout=5)
                if worker.is_alive():
                    self.errors.append(f"Worker did not stop: {worker.name}")
        try:
            self.speaker.close()
        except Exception as error:
            self.errors.append(str(error))
        if self.timestamps is not None:
            self.timestamps.close()
        if self.timestamp_log is not None:
            self.timestamp_log.close()
        if self.audio_diagnostic is not None:
            self.audio_diagnostic.close()
        echo_stats = None
        if self.echo is not None:
            self.echo.close()
            echo_stats = dict(self.echo.stats)
        if self.log is not None and (self.thread is None or not self.thread.is_alive()):
            self.log.close()
            self.log = None
        return {"model": MODEL, "cloud_rate": CLOUD_RATE, "g1_rate": RATE,
                "vector_store_id": self.vector_store_id,
                "aec": self.aec_enabled, "aec_delay_ms": self.aec_delay_ms,
                "aec_stats": echo_stats,
                "mic_gate_dbfs": self.gate.threshold_dbfs if self.gate else None,
                "mic_gate_scope": "playback_only" if self.gate else None,
                "mic_gate_stats": dict(self.gate.stats) if self.gate else None,
                "diagnose_audio": self.diagnose_audio,
                "timestamps_enabled": self.timestamps is not None,
                "timestamp_stats": self.timestamp_stats,
                "session": self.session, **self.stats,
                "speaker_submitted_bytes": self.speaker.submitted_bytes, "errors": list(self.errors)}
