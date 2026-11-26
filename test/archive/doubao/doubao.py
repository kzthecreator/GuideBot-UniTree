"""Doubao realtime duplex provider using the existing G1 audio pipeline."""

import json
import base64
import os
from pathlib import Path
import queue
import threading
import time
import uuid

import websocket
from dotenv import load_dotenv

from audio import AudioDiagnostic, microphone_packets
from localvqe import LocalVQEEcho
from agc import AGC2
from stepfun import RealtimeSession

ENDPOINT = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
MODEL = "1.2.6.1"
VOICE = "zh_female_xiaohe_jupiter_bigtts"


def load_doubao_api_key():
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    config = Path(os.environ.get("GUIDEBOT_CONFIG_FILE", base / "guidebot/conversation.env"))
    load_dotenv(config, override=False, interpolate=False)
    key = os.environ.get("DOUBAO_API_KEY")
    if not key:
        raise ValueError(f"Set DOUBAO_API_KEY in {config}")
    return key


class DoubaoSession(RealtimeSession):
    """Reuse the G1 capture, speaker, diagnostics, timestamps, and gesture path."""

    def __init__(self, secret, directory, voice=None, chunk_ms=1000, gain=1.5,
                 endpoint=None, model=None, agc=True, **kwargs):
        if agc:
            kwargs['mic_gate_dbfs'] = None
        super().__init__(secret, directory, voice, chunk_ms, gain,
                         vector_store_id=None, **kwargs)
        self.agc_enabled = agc
        self.agc = None
        self.endpoint = endpoint or os.environ.get("DOUBAO_ENDPOINT", ENDPOINT)
        self.model = model or os.environ.get("DOUBAO_MODEL", MODEL)
        self.voice = voice or VOICE
        self.session_id = str(uuid.uuid4())
        self.event_number = 0
        self.closed_event = threading.Event()
        self.interrupted_items = set()
        self.finished_responses = set()
        self.question_responses = {}
        self.response_aliases = {}
        self.asr_partials = {}
        self.session_closing = False
        self.send_lock = threading.Lock()

    def start(self):
        if self.thread is not None:
            raise RuntimeError("Create a new DoubaoSession for each conversation")
        if not self.secret:
            raise ValueError("DOUBAO_API_KEY is required")
        self.started_at = time.monotonic()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.aec_enabled:
            self.echo = LocalVQEEcho(self.aec_delay_ms)
        if self.agc_enabled:
            self.agc = AGC2()
        if self.diagnose_audio:
            self.audio_diagnostic = AudioDiagnostic(self.directory, self.started_at,
                                                    processed=self.aec_enabled,
                                                    gated=self.gate is not None,
                                                    uploaded=True)
            (self.directory / "LISTEN.md").write_text(
                "# 本次实验录音\n\n"
                "按 Enter 结束会话后再试听，WAV 文件头会在结束时完成写入。\n\n"
                "- microphone-16k.wav：G1 原始麦克风 PCM。\n"
                "- microphone-uploaded-16k.wav：处理后成功发送到 WebSocket 的实际 PCM。\n"
                "- microphone-aec-16k.wav：LocalVQE 输出（启用 AEC 时）。\n"
                "- microphone-gated-16k.wav：门控输出（启用 gate 时）。\n"
                "- speaker-16k.wav：提交给 G1 SDK 的回复 PCM。已提交但被中断的部分可能未实际播出。\n\n"
                "均为 16 kHz 单声道 PCM16。各轨按样本拼接，网络间隔不补静音；"
                "绝对时间关系见 audio-index.jsonl 和 events.jsonl，SDK 无真实播放结束回执。\n",
                encoding="utf-8")
        self.log = (self.directory / "events.jsonl").open("w", encoding="utf-8")
        if self.timestamps is not None:
            self.timestamp_log = (self.directory / "alignment.jsonl").open("w", encoding="utf-8")
            try:
                self.timestamps.start()
            except Exception as error:
                self._alignment_event("alignment.error", message=f"Timestamp worker disabled: {error}; audio continues")
        if self.gestures is not None:
            try:
                self.gestures.start()
            except Exception as error:
                self._gesture_event("gesture.error", message=f"Gesture startup failed: {error}; audio continues")
                self.gestures.close()
                self.gestures = None
        websocket.setdefaulttimeout(5)
        self.ws = websocket.WebSocketApp(
            self.endpoint,
            header=[f"X-Api-Key: {self.secret}"],
            on_open=self._on_open,
            on_message=lambda ws, message: self._dispatch_message(message),
            on_error=lambda ws, error: self._socket_error(error),
            on_close=self._on_close,
        )
        self.thread = threading.Thread(target=self._run_socket, name="doubao-realtime", daemon=True)
        self.thread.start()

    def _dispatch_message(self, message):
        try:
            self.on_event(json.loads(message))
        except Exception as error:
            self.fail(error)

    def _on_close(self, ws, code, reason):
        if self.session_closing or self.stopping.is_set():
            self.closed_event.set()
            return
        super()._on_close(ws, code, reason)

    def _socket_error(self, error):
        if not self.session_closing:
            super()._socket_error(error)

    def _on_open(self, ws):
        if self.stopping.is_set():
            self._close_socket()
            return
        try:
            session = {
                "id": self.session_id,
                "model": self.model,
                "instructions": self.instructions,
                "audio": {
                    "input": {"format": {"type": "pcm", "rate": 16000}},
                    "output": {"format": {"type": "pcm_s16le", "rate": 24000},
                               "voice": self.voice},
                },
            }
            extension = {"asr": {"extra": {}}, "tts": {"extra": {}},
                         "dialog": {"extra": {"enable_loudness_norm": True,
                                                "enable_music": False}}}
            self._send("session.create", session=session, extension=extension)
        except Exception as error:
            self.fail(error)

    def _send(self, kind, **fields):
        if self.stopping.is_set():
            return False
        if self.session_closing and kind != 'session.close':
            return False
        if self.ws is None:
            raise RuntimeError("Doubao WebSocket is not connected")
        with self.send_lock:
            self.event_number += 1
            event = {"type": kind, **fields}
            if kind != "input_audio_buffer.append":
                event["event_id"] = f"event_{self.event_number}"
            self.ws.send(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
        return True

    def _activate_media(self, event):
        self.session = event.get("session") or {}
        self.session_id = self.session.get("id") or self.session_id
        with self.lifecycle:
            if self.stopping.is_set() or self.ready.is_set():
                return
            if not self.speaker.start() or self.stopping.is_set():
                return
            self.workers = [threading.Thread(target=target, name=name, daemon=True)
                            for target, name in [(self._capture, "g1-microphone"),
                                                 (self._send_microphone, "doubao-upload")]]
            for worker in self.workers:
                worker.start()
            self.ready.set()
        self.report("ready", f"Doubao {self.model} 已就绪。按 Enter 结束；识别到用户语音时本地立即停播。")

    def _capture(self):
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
                if self.agc is not None:
                    pcm = self.agc.process(pcm)
                pending.extend(pcm)
                while len(pending) >= 640 and not self.stopping.is_set():
                    self.input_queue.put_nowait(bytes(pending[:640]))
                    del pending[:640]
        except queue.Full:
            self.fail(RuntimeError("Microphone upload queue exceeds 2s; stopping instead of sending stale audio"))
        except Exception as error:
            if not self.stopping.is_set():
                self.fail(error)

    def _ensure_response(self, response_id):
        if response_id and response_id not in self.active:
            super().on_event({"type": "response.created",
                              "response": {"id": response_id, "status": "in_progress"}})

    def _send_microphone(self):
        try:
            while not self.stopping.is_set() and not self.session_closing:
                try:
                    pcm = self.input_queue.get(timeout=.2)
                except queue.Empty:
                    continue
                if self._send("input_audio_buffer.append", audio=base64.b64encode(pcm).decode("ascii")):
                    self.stats["uploaded_bytes"] += len(pcm)
                    if self.audio_diagnostic is not None:
                        self.audio_diagnostic.write("microphone-uploaded", pcm, time.monotonic())
        except Exception as error:
            self._socket_error(error)

    def _canonical_response_id(self, event):
        response_id = event.get("response_id")
        question_id = event.get("question_id")
        canonical = self.response_aliases.get(response_id, response_id)
        if question_id:
            canonical = self.question_responses.get(question_id, canonical or question_id)
            self.question_responses[question_id] = canonical
        if response_id and canonical:
            self.response_aliases[response_id] = canonical
        if not canonical and len(self.active) == 1:
            canonical = next(iter(self.active))
        return canonical

    def _interrupt_for_transcription(self, event):
        item_id = event.get("item_id")
        if item_id and item_id in self.interrupted_items:
            return
        if item_id:
            self.interrupted_items.add(item_id)
        # response.done removes cloud-active IDs while their audio may still
        # be queued in the G1 speaker. Include that independent playback state.
        active = set(self.active) | self.speaker.pending_response_ids()
        if not active and not self.speaker.is_playing():
            return
        self.discarded.update(active)
        self.report("ASR-interrupt", "豆包开始转写用户语音；清除旧回复并停止 G1 播放",
                    turn=self.current_turn, item_id=item_id)
        for response_id in active:
            if self.gestures is not None:
                self.gestures.submit("cancel", response_id, reason="transcription_started")
            if self.timestamps is not None:
                self.timestamps.send("cancel", response_id)
        self.speaker.interrupt()

    def on_event(self, event):
        kind = event.get("type")
        if kind == "session.created":
            self._write_log("doubao.session.created", session=event.get("session"))
            self._activate_media(event)
            return
        if kind == "session.closed":
            self.closed_event.set()
            self._write_log("doubao.session.closed")
            return
        if kind == "conversation.item.input_audio_transcription.started":
            if event.get('item_id') not in self.user_turns:
                self.current_turn += 1
                self.user_turns[event.get('item_id')] = self.current_turn
            self._write_log("doubao.transcription.started", item_id=event.get("item_id"))
            self._interrupt_for_transcription(event)
            return
        if kind == "conversation.item.input_audio_transcription.delta":
            item_id = event.get("item_id")
            # Observed Seeduplex deltas are revisable full partial hypotheses,
            # e.g. '你', '你可以', '你可以帮我'; concatenation duplicates text.
            self.asr_partials[item_id] = event.get("delta", "")
            self._write_log("doubao.transcription.delta", item_id=event.get("item_id"),
                            delta=event.get("delta", ""))
            self.report('ASR-partial', 'User（暂定）: ' + event.get('delta', ''),
                        turn=self.user_turns.get(item_id, self.current_turn))
            return
        if kind == "conversation.item.input_audio_transcription.completed":
            item_id = event.get("item_id")
            partial = self.asr_partials.pop(item_id, "")
            transcript = event.get("transcript") or event.get("text") or partial
            self._write_log("doubao.transcription.completed", item_id=event.get("item_id"),
                            transcript=transcript)
            self.report("ASR-final", "User: " + transcript,
                        turn=self.user_turns.get(item_id, self.current_turn))
            return
        if kind == "conversation.item.input_audio_transcription.failed":
            self._write_log("doubao.transcription.failed", item_id=event.get("item_id"),
                            error=event.get("error"))
            return
        if kind in {"response.output_text.delta", "response.output_text.done",
                    "response.output_audio.started", "response.output_audio.delta",
                    "response.output_audio.done"}:
            response_id = self._canonical_response_id(event)
            if not response_id:
                self._write_log("doubao.response_event_without_id", provider_type=kind,
                                event_keys=sorted(event.keys()))
                return
            if response_id in self.finished_responses:
                self._write_log("doubao.late_response_event_discarded", provider_type=kind,
                                response_id=response_id)
                return
            self._ensure_response(response_id)
            if response_id in self.discarded:
                self._write_log("doubao.late_response_event_discarded", provider_type=kind,
                                response_id=response_id)
                return
            if kind == "response.output_audio.started":
                self._write_log("doubao.response.output_audio.started", response_id=response_id,
                                question_id=event.get("question_id"), tts_type=event.get("tts_type"))
            elif kind == "response.output_text.delta":
                super().on_event({"type": "response.audio_transcript.delta",
                                  "response_id": response_id, "delta": event.get("delta", "")})
            elif kind == "response.output_text.done":
                super().on_event({"type": "response.audio_transcript.done",
                                  "response_id": response_id,
                                  "transcript": event.get("text", "")})
            elif kind == "response.output_audio.delta":
                super().on_event({"type": "response.audio.delta", "response_id": response_id,
                                  "delta": event.get("delta", "")})
            else:
                super().on_event({"type": "response.audio.done", "response_id": response_id})
            return
        if kind == "response.canceled":
            self._write_log("doubao.response.canceled", event_id=event.get("event_id"))
            return
        if kind == "response.done":
            response = event.get("response") or {}
            response_id = self._canonical_response_id({
                "response_id": response.get("id") or event.get("response_id"),
                "question_id": event.get("question_id") or response.get("question_id"),
            })
            if not response_id:
                self._write_log("doubao.response_done_without_id", response_keys=sorted(response.keys()))
                return
            if response_id in self.finished_responses:
                self._write_log("doubao.duplicate_response_done", response=response)
                return
            self._ensure_response(response_id)
            self.finished_responses.add(response_id)
            self._write_log("doubao.response.done", response=response)
            # Doubao sends usage-only response.done payloads without StepFun's
            # status/id fields. Normalize this provider's terminal event here.
            status = response.get("status") or "completed"
            if response_id in self.discarded:
                status = "interrupted"
            event = {**event, "response": {**response, "id": response_id, "status": status}}
            super().on_event(event)
            return
        if kind in {"error", "session.updated", "input_audio_buffer.committed"}:
            if kind == "error":
                detail = event.get("error") or {}
                self.fail(RuntimeError(f"Doubao: {detail.get('code', '')} {detail.get('message', 'Request failed')}"))
            else:
                self._write_log("doubao." + kind, **{k: v for k, v in event.items() if k != "type"})
            return
        self._write_log("doubao.unhandled_event", provider_type=kind,
                        event={k: v for k, v in event.items() if k not in {"audio", "delta"}})

    def stop(self):
        if self.ws is not None and self.ready.is_set() and not self.stopping.is_set():
            try:
                self.session_closing = True
                self._send("session.close")
                self.closed_event.wait(1.5)
            except Exception:
                pass
        result = super().stop()
        if self.agc is not None:
            self.agc.close()
            result['agc2_stats'] = dict(self.agc.stats)
        result["provider"] = "doubao"
        result["model"] = self.model
        result["agc2_enabled"] = self.agc_enabled
        return result
