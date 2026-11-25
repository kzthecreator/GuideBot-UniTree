"""Nonblocking conversation adapter for planning and motion dispatch."""
from GuideBot.compat import CancellableThreadPoolExecutor as ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import os
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
                 debounce=.18, max_wait=.4, interaction_context=None, execution_mode=None, executor=None):
        self.directory = Path(directory)
        self.catalog = catalog or Catalog()
        self.planner = planner or Planner(self.catalog)
        self.targets = list(targets)
        self.interaction_context = self._validate_interaction_context(interaction_context)
        if len({t['id'] for t in self.targets}) != len(self.targets):
            raise ValueError('Duplicate scene target ID')
        self.on_event = on_event
        self.debounce, self.max_wait = debounce, max_wait
        self.queue = queue.Queue(maxsize=256)
        self.stopping = threading.Event()
        self.overflow = threading.Event()
        self.executor = executor
        execution_mode = execution_mode or os.getenv('GUIDEBOT_GESTURE_EXECUTION_MODE', 'simulation')
        timing_mode = os.getenv('GUIDEBOT_GESTURE_TIMING_MODE',
                                'immediate' if execution_mode == 'robot' else 'aligned')
        if timing_mode not in {'immediate', 'aligned'}:
            raise ValueError('Invalid gesture timing mode')
        self.scheduler = Scheduler(self.catalog, self._emit, immediate=timing_mode == 'immediate')
        self.replies = {}
        self.pool = self.thread = self.log = None
        self.request_id = 0
        self.requests = []

    @staticmethod
    def _validate_interaction_context(context):
        if context is None:
            return {'stage': 'unspecified', 'history': [], 'facts': []}
        allowed = {'stage', 'history', 'facts', 'navigation', 'scene', 'asr', 'dialogue', 'task',
                   'visitor_responded', 'interaction_changed', 'task_completed', 'task_cancelled',
                   'new_valid_input', 'clarification_completed', 'interaction_cancelled',
                   'display_target_changed', 'explanation_ended', 'action_switch_needed'}
        if not isinstance(context, dict) or set(context) - allowed:
            raise ValueError('Invalid interaction context')
        stage = context.get('stage', 'unspecified')
        history = context.get('history', [])
        facts = context.get('facts', [])
        if (not isinstance(stage, str) or not stage.strip()
                or not isinstance(history, list) or not isinstance(facts, list)
                or not all(isinstance(value, str) and value.strip() for value in history + facts)):
            raise ValueError('Invalid interaction context')
        result = {'stage': stage, 'history': list(history), 'facts': list(facts)}
        for key in ('navigation', 'scene', 'asr', 'dialogue', 'task'):
            if key in context:
                if not isinstance(context[key], dict):
                    raise ValueError('Invalid structured interaction state')
                result[key] = dict(context[key])
        result.update({key: context[key] for key in allowed - {
            'stage', 'history', 'facts', 'navigation', 'scene', 'asr', 'dialogue', 'task'
        } if key in context})
        return result

    def set_interaction_context(self, context):
        self.interaction_context = self._validate_interaction_context(context)
        lifecycle = (
            ('visitor_responded', 'visitor_responded'), ('interaction_changed', 'interaction_changed'),
            ('task_completed', 'task_completed'), ('task_cancelled', 'task_cancelled'),
            ('maximum_hold_time', 'maximum_hold_time'),
            ('new_valid_input', 'new_valid_input'), ('clarification_completed', 'clarification_completed'),
            ('interaction_cancelled', 'interaction_cancelled'), ('display_target_changed', 'display_target_changed'),
            ('explanation_ended', 'explanation_ended'), ('action_switch_needed', 'action_switch_needed'),
        )
        for key, condition in lifecycle:
            if self.interaction_context.get(key) is True:
                self.submit('release_pose', condition=condition)
        self._emit('gesture.context', interaction_context=self.interaction_context)

    def request_base_pose(self, reason='interaction_state_change'):
        """Queue an explicit scheduler lifecycle transition; does not auto-reset."""
        self.submit('base_pose', reason=reason)

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
        if kind in {'gesture.command', 'gesture.reset'} and self.executor is not None:
            try:
                execution = self.executor.handle(kind, details)
                if execution is not None:
                    value['execution'] = execution
                    if kind == 'gesture.command' and execution['mode'] == 'robot':
                        value['simulated'] = False
                        details['simulated'] = False
            except (ValueError, OSError, KeyError) as error:
                value['execution_error'] = str(error)
        if self.log is not None:
            self.log.write(json.dumps(value, ensure_ascii=False) + '\n')
            self.log.flush()
        if self.on_event:
            try:
                self.on_event(kind, **details)
            except Exception:
                pass
        return value

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
                elif kind == 'base_pose':
                    self.scheduler.request_base_pose(
                        value.get('reason', 'interaction_state_change'))
                elif kind == 'release_pose':
                    self.scheduler.release_active(value['condition'])
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
                        item = self.catalog.actions.get(value['plan'].action)
                        if item is None or not self.catalog.context_allows(item, self.interaction_context):
                            self._emit('gesture.rejected', response_id=rid,
                                       reason='trusted_interaction_context_changed',
                                       action=value['plan'].action)
                        else:
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
                                 range(first, len(reply.units)), state.complete,
                                 self.interaction_context)
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
            try:
                self.pool.shutdown(wait=True, cancel_futures=True)
            except TypeError:
                self.pool.shutdown(wait=True)
        if self.log:
            self.log.close()


def load_targets(path):
    if path is None:
        return []
    value = strict_json(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, list) or any(not isinstance(t.get('id'), str) or not t.get('id') for t in value):
        raise ValueError('Scene targets must be a list with nonempty string IDs')
    return value
