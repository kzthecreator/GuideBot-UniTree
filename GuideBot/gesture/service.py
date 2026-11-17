"""Nonblocking conversation adapter; all commands are simulation-only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
from pathlib import Path
import queue
import re
import threading
import time

from .catalog import Catalog, make_input, units_for, strict_json
from .planner import Planner
from .scheduler import Scheduler


@dataclass
class PlanningReply:
    text: str = ''
    complete: bool = False
    changed_at: float = 0
    submitted_text: str = None
    submitted_complete: bool = False
    in_flight: bool = False
    cancelled: threading.Event = field(default_factory=threading.Event)


class GestureService:
    def __init__(self, directory, on_event=None, *, catalog=None, planner=None, targets=(),
                 debounce=.18, max_wait=.4):
        self.directory = Path(directory)
        self.catalog = catalog or Catalog()
        self.planner = planner or Planner(self.catalog)
        self.targets = list(targets)
        if len({t['id'] for t in self.targets}) != len(self.targets):
            raise ValueError('Duplicate scene target ID')
        self.on_event = on_event
        self.debounce, self.max_wait = debounce, max_wait
        self.queue = queue.Queue(maxsize=256)
        self.stopping = threading.Event()
        self.overflow = threading.Event()
        self.scheduler = Scheduler(self.catalog, self._emit)
        self.replies = {}
        self.pool = self.thread = self.log = None
        self.request_id = 0
        self.requests = []

    def start(self):
        if self.thread is not None:
            raise RuntimeError('Create a new gesture service per session')
        if isinstance(self.planner, Planner) and not self.planner.api_key:
            raise RuntimeError('DEEPSEEK_API_KEY is not set; gesture planning disabled')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log = (self.directory / 'gesture.jsonl').open('w', encoding='utf-8')
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='gesture-planner')
        self.thread = threading.Thread(target=self._run, name='gesture-scheduler', daemon=True)
        self.thread.start()
        self.submit('ready', model=getattr(self.planner, 'model', 'test'), actions=list(self.catalog.actions))

    def submit(self, kind, response_id=None, **details):
        if self.stopping.is_set() or self.overflow.is_set():
            return
        try:
            self.queue.put_nowait((kind, response_id, details))
        except queue.Full:
            self.overflow.set()

    def _emit(self, kind, **details):
        value = dict(kind=kind, monotonic=time.monotonic(), **details)
        if self.log is not None:
            self.log.write(json.dumps(value, ensure_ascii=False) + '\n')
            self.log.flush()
        if self.on_event:
            try:
                self.on_event(kind, **details)
            except Exception:
                pass

    def _cancel(self, rid, reason):
        state = self.replies.pop(rid, None)
        if state:
            state.cancelled.set()
        self.scheduler.cancel(rid, reason)

    def _run(self):
        try:
            while not self.stopping.is_set():
                if self.overflow.is_set():
                    self._emit('gesture.error', message='Gesture input overflow; audio continues')
                    return
                try:
                    kind, rid, value = self.queue.get(timeout=.02)
                except queue.Empty:
                    kind, rid, value = None, None, {}
                if kind == 'ready':
                    self._emit('gesture.ready', simulated=True, **value)
                elif kind == 'cancel':
                    self._cancel(rid, value.get('reason', 'interrupted'))
                elif rid in self.scheduler.closed:
                    continue
                elif kind in {'text', 'text_delta', 'done'}:
                    if rid not in self.replies and len(self.replies) >= 8:
                        self._emit('gesture.rejected', response_id=rid, reason='pending_response_limit')
                        self.scheduler.cancel(rid, 'pending_response_limit')
                        continue
                    state = self.replies.setdefault(rid, PlanningReply())
                    if kind == 'done':
                        state.complete = True
                    else:
                        state.text = state.text + value['text'] if kind == 'text_delta' else value['text']
                        if len(state.text) > 12000:
                            self._cancel(rid, 'text_limit')
                            continue
                        self.scheduler.text(rid, state.text)
                        if not state.changed_at:
                            state.changed_at = time.monotonic()
                elif kind == 'alignment':
                    self.scheduler.alignment(rid, value)
                elif kind == 'playback':
                    self.scheduler.playback(rid, value['origin'])
                elif kind == 'action':
                    state = self.replies.get(rid)
                    if state and state.text.startswith(value['text']):
                        self.scheduler.add(rid, value['plan'], value['units'], value['request_id'])
                    else:
                        self._emit('gesture.rejected', response_id=rid, reason='stale_planner_snapshot')
                elif kind == 'result':
                    state = self.replies.get(rid)
                    if state:
                        state.in_flight = False
                    self._emit('gesture.planner_result', response_id=rid, **value)
                    if 'error' in value:
                        self.scheduler.discard_request(rid, value['request_id'])
                self._plan_due()
                self.scheduler.tick()
        except Exception as error:
            # Never let observer/model failures escape onto the speech thread.
            self._emit('gesture.error', message=f'Gesture service failed: {type(error).__name__}; audio continues')
        finally:
            for rid in list(self.scheduler.replies):
                self._cancel(rid, 'service_stopped')
            self.stopping.set()

    def _plan_due(self):
        now = time.monotonic()
        # Two slots allow a newly interrupted turn to proceed while a cancelled
        # HTTP request is winding down. No queue of obsolete text snapshots.
        self.requests = [future for future in self.requests if not future.done()]
        if len(self.requests) >= 2:
            return
        for rid, state in list(self.replies.items()):
            if state.in_flight or not units_for(state.text):
                continue
            if state.text == state.submitted_text and state.complete == state.submitted_complete:
                continue
            age = now - state.changed_at if state.changed_at else 0
            boundary = re.search(r'[，。！？；：,.!?;:]\s*$', state.text)
            if not state.complete and not (age >= self.max_wait or (boundary and age >= self.debounce)):
                continue
            reply = self.scheduler.reply(rid)
            if reply is None:
                continue
            existing = [j.plan.as_dict() for j in reply.jobs if j.status != 'cancelled']
            # Keep a short overlap for a lead-in whose object arrived later.
            first = max(0, len(units_for(state.submitted_text or '')) - 16)
            payload = make_input(rid, state.text, self.targets, existing,
                                 range(first, len(reply.units)), state.complete)
            state.in_flight = True
            state.submitted_text, state.submitted_complete = state.text, state.complete
            state.changed_at = 0
            self.request_id += 1
            request_id = self.request_id
            self._emit('gesture.planner_started', response_id=rid, request_id=request_id,
                       units=len(reply.units), complete=state.complete)
            self.requests.append(self.pool.submit(self._request, rid, state.text, payload,
                                                 request_id, state.cancelled))
            break

    def _request(self, rid, text, payload, request_id, cancelled):
        try:
            def action(plan):
                self.submit('action', rid, plan=plan, text=text, units=payload['units'], request_id=request_id)
            stats = self.planner.plan(payload, action, cancelled)
            self.submit('result', rid, request_id=request_id, **stats)
        except Exception as error:
            # Only known, sanitized client errors can be logged verbatim.
            message = str(error) if type(error) is RuntimeError else type(error).__name__
            self.submit('result', rid, request_id=request_id, error=message)

    def close(self):
        self.stopping.set()
        for state in list(self.replies.values()):
            state.cancelled.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
        if self.pool:
            self.pool.shutdown(wait=True, cancel_futures=True)
        if self.log:
            self.log.close()


def load_targets(path):
    if path is None:
        return []
    value = strict_json(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, list) or any(not isinstance(t.get('id'), str) or not t.get('id') for t in value):
        raise ValueError('Scene targets must be a list with nonempty string IDs')
    return value
