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

from GuideBot.gesture.catalog import Catalog, make_input, units_for, strict_json
from GuideBot.gesture.streaming import PlannerClient
from GuideBot.gesture.semantic_planner import SemanticPlanner
from GuideBot.gesture.semantic import bind, next_chunk, validate_output
from GuideBot.gesture.scheduler import Scheduler


@dataclass
class PlanningReply:
    text: str = ''
    complete: bool = False
    changed_at: float = 0
    submitted_text: str = None
    submitted_complete: bool = False
    in_flight: bool = False
    sent_offset: int = 0
    request_id: int = 0
    cancelled: threading.Event = field(default_factory=threading.Event)


class GestureService:
    def __init__(self, directory, on_event=None, *, catalog=None, planner=None, targets=(),
                 debounce=.18, max_wait=.4, interaction_context=None, execution_mode=None, executor=None):
        self.directory = Path(directory)
        self.catalog = catalog or Catalog()
        self.planner = planner or SemanticPlanner(self.catalog)
        self.semantic = getattr(self.planner, 'semantic', False) is True
        self.pending_intents = {}
        self.semantic_attempts = {}
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
        self.scheduler = Scheduler(self.catalog, self._emit,
                                   immediate=not self.semantic and timing_mode == 'immediate')
        self.replies = {}
        self.pool = self.thread = self.log = None
        self.request_id = 0
        self.requests = []
        self.mode = 'listening'
        self.speaking_response = None

    def _listen(self, reason):
        self.mode = 'listening'
        self.speaking_response = None
        self._emit('gesture.mode', mode=self.mode, reason=reason)
        self.scheduler.request_base_pose(reason)

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
        if (isinstance(self.planner, PlannerClient) and not self.planner.api_key
                and getattr(self.planner, 'provider', None) != 'local_qwen'):
            raise RuntimeError('DEEPSEEK_API_KEY is not set; gesture planning disabled')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.log = (self.directory / 'gesture.jsonl').open('w', encoding='utf-8')
        self.pool = ThreadPoolExecutor(max_workers=1 if self.semantic else 2, thread_name_prefix='gesture-planner')
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
        if self.semantic and kind == 'gesture.command' and details.get('response_id') != '__scheduler__':
            self.semantic_attempts.setdefault(details.get('response_id'), set()).add(details['job_id'])
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
        self.pending_intents.pop(rid, None)
        self.semantic_attempts.pop(rid, None)
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
                    self._emit('gesture.mode', mode=self.mode, reason='session_started')
                elif kind == 'cancel':
                    self._cancel(rid, value.get('reason', 'interrupted'))
                    if rid == self.speaking_response:
                        self._listen(value.get('reason', 'interrupted'))
                elif kind == 'base_pose':
                    self.scheduler.request_base_pose(
                        value.get('reason', 'interaction_state_change'))
                elif kind == 'release_pose':
                    self.scheduler.release_active(value['condition'])
                elif kind == 'execution_result':
                    self.scheduler.execution_result(value['job_id'], value['success'], value.get('reason', ''))
                elif kind == 'semantic_action':
                    self._semantic_result(rid, value, incremental=True)
                elif kind == 'semantic_result':
                    self._semantic_result(rid, value)
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
                        text = state.text + value['text'] if kind == 'text_delta' else value['text']
                        if self.semantic and not text.startswith(state.text):
                            self._emit('gesture.rejected', response_id=rid, reason='text_replaced')
                            self._cancel(rid, 'text_replaced')
                            continue
                        state.text = text
                        if len(state.text) > 12000:
                            self._cancel(rid, 'text_limit')
                            continue
                        self.scheduler.text(rid, state.text)
                        if not state.changed_at:
                            state.changed_at = time.monotonic()
                elif kind == 'alignment':
                    self.scheduler.alignment(rid, value)
                    if self.semantic:
                        self._invalidate_semantic_windows(rid)
                elif kind == 'playback':
                    if self.speaking_response is not None and self.speaking_response != rid:
                        self._cancel(self.speaking_response, 'playback_replaced')
                    if self.mode != 'speaking' or self.speaking_response != rid:
                        self.mode, self.speaking_response = 'speaking', rid
                        self._emit('gesture.mode', mode=self.mode, response_id=rid,
                                   reason='playback.started')
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
                if self.semantic:
                    self._resolve_semantic()
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
        if self.semantic:
            return self._plan_semantic_due()
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
            existing = self.scheduler.planning_history(rid)
            # Keep a short overlap for a lead-in whose object arrived later.
            first = max(0, len(units_for(state.submitted_text or '')) - 16)
            payload = make_input(rid, state.text, self.targets, existing,
                                 range(first, len(reply.units)), state.complete,
                                 self.interaction_context)
            payload['timing_contract'] = 'fixed_deadline'
            payload['playback_elapsed_s'] = (max(0., now-reply.playback_origin)
                                             if reply.playback_origin is not None else 0.)
            payload['playback_started'] = reply.playback_origin is not None
            payload['suggested_planning_lead_s'] = 2.
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

    def _semantic_capacity(self, rid):
        reply = self.scheduler.replies.get(rid)
        queued = sum(j.status in {'waiting', 'scheduled'} for j in reply.jobs) if reply else 0
        return max(0, 3-len(self.semantic_attempts.get(rid, ()))-queued
                   -len(self.pending_intents.get(rid, ())))

    def _plan_semantic_due(self):
        self.requests = [f for f in self.requests if not f.done()]
        if self.requests:
            return
        for rid, state in list(self.replies.items()):
            if state.in_flight or not self._semantic_capacity(rid):
                continue
            chunk = next_chunk(state.text, state.sent_offset, state.complete)
            if chunk is None:
                continue
            state.sent_offset = chunk.offset+len(chunk.text)
            state.in_flight = True
            self.request_id += 1
            state.request_id = self.request_id
            self._emit('gesture.planner_started', response_id=rid, request_id=self.request_id,
                       protocol='semantic_v1', chunk_offset=chunk.offset,
                       input_characters=len(chunk.text))
            self.requests.append(self.pool.submit(self._semantic_request, rid, chunk,
                                                  self.request_id, state.cancelled))
            return

    def _semantic_request(self, rid, chunk, request_id, cancelled):
        try:
            if getattr(self.planner, 'incremental_actions', False) is True:
                def action(row):
                    self.submit('semantic_action', rid, chunk=chunk, request_id=request_id,
                                result={'actions': [row]})
                result = self.planner.analyze(chunk.text, cancelled, on_action=action)
            else:
                result = self.planner.analyze(chunk.text, cancelled)
        except Exception as error:
            result = dict(error=str(error) if type(error) is RuntimeError else type(error).__name__)
        self.submit('semantic_result', rid, chunk=chunk, request_id=request_id, result=result)

    def _semantic_result(self, rid, value, incremental=False):
        state = self.replies.get(rid)
        result, chunk = value['result'], value['chunk']
        if (state is None or state.request_id != value['request_id']
                or state.cancelled.is_set() or rid in self.scheduler.closed):
            self._emit('gesture.semantic_discarded', response_id=rid, reason='stale_request')
            return
        if not incremental:
            state.in_flight = False
            self._emit('gesture.planner_result', response_id=rid, request_id=value['request_id'],
                       **{k:v for k,v in result.items() if k != 'actions'})
        if result.get('error') or result.get('cancelled'):
            self.pending_intents[rid] = [p for p in self.pending_intents.get(rid, ())
                                         if p['request_id'] != value['request_id']]
            self.scheduler.discard_request(rid, value['request_id'])
            return
        if result.get('streamed') and result.get('actions'):
            return
        if not state.text.startswith(chunk.snapshot):
            self._emit('gesture.rejected', response_id=rid, reason='stale_text')
            return
        try:
            rows = validate_output(self.catalog, {'actions': result['actions']})
        except (ValueError, KeyError, TypeError):
            self._emit('gesture.rejected', response_id=rid, reason='semantic_json_invalid')
            return
        if not rows:
            self._emit('gesture.semantic_none', response_id=rid, request_id=value['request_id'])
        for row in rows:
            if not self._semantic_capacity(rid):
                self._emit('gesture.rejected', response_id=rid, reason='quota_reached')
                break
            try:
                begin, finish, source = bind(self.catalog, row, chunk)
            except ValueError as error:
                self._emit('gesture.rejected', response_id=rid, reason=str(error), action=row['action'])
                continue
            reply = self.scheduler.replies[rid]
            if (any(j.plan.action == row['action'] and j.plan.arrival_unit == finish
                    for j in reply.jobs if j.status != 'cancelled') or
                    any(p['action'] == row['action'] and p['finish'] == finish
                        for p in self.pending_intents.get(rid, ()))):
                self._emit('gesture.rejected', response_id=rid, reason='duplicate_intent')
                continue
            self.pending_intents.setdefault(rid, []).append(dict(action=row['action'],
                begin=begin, finish=finish, source=source, request_id=value['request_id'], waiting=False))
            self._emit('gesture.semantic_bound', response_id=rid, action=row['action'],
                       begin_unit=begin, finish_unit=finish, request_id=value['request_id'])

    def _resolve_semantic(self):
        for rid, pending in list(self.pending_intents.items()):
            reply = self.scheduler.replies.get(rid)
            if reply is None or rid in self.scheduler.closed:
                self.pending_intents.pop(rid, None)
                continue
            keep = []
            for item in pending:
                if tuple(reply.units[:item['finish']+1]) != item['source']:
                    self._emit('gesture.rejected', response_id=rid, reason='stale_text')
                    continue
                if (reply.playback_origin is not None and item.get('end_cap') is not None
                        and time.monotonic()-reply.playback_origin >= item['end_cap']):
                    self._emit('gesture.skipped', response_id=rid, action=item['action'],
                               reason='deadline_passed')
                    continue
                if reply.playback_origin is None or any(i not in reply.anchors for i in (item['begin'],item['finish'])):
                    if not item['waiting']:
                        self._emit('gesture.alignment_waiting', response_id=rid,
                                   action=item['action'], reason='alignment_not_ready')
                        item['waiting'] = True
                    keep.append(item)
                    continue
                start, end = [reply.anchors[i]['start'] for i in (item['begin'], item['finish'])]
                anchor_pair = (start, end)
                end = min(end, item.get('end_cap', end))
                now = time.monotonic()-reply.playback_origin
                remaining = end-max(start, now)
                minimum = self.catalog.execution_timing(item['action'])['minimum_remaining_s']
                reason = ('deadline_passed' if now >= end else
                          'insufficient_budget' if remaining < minimum else None)
                if reason:
                    self._emit('gesture.skipped', response_id=rid, action=item['action'],
                               reason=reason, remaining_s=remaining, minimum_remaining_s=minimum)
                    continue
                row = dict(action=item['action'], start_unit=item['begin'], arrival_unit=item['finish'],
                           start_s=start, end_s=end)
                try:
                    plan = self.catalog.validate(row, range(len(reply.units)), self.targets,
                                                 self.interaction_context)
                except ValueError:
                    self._emit('gesture.rejected', response_id=rid, reason='invalid_timed_window')
                    continue
                job = self.scheduler.add(rid, plan, item['source'], item['request_id'])
                if job is not None:
                    job.anchor_pair = anchor_pair
                self._emit('gesture.window_bound', response_id=rid, action=item['action'],
                           alignment_version=reply.version, start_s=start, end_s=end,
                           remaining_s=remaining)
            self.pending_intents[rid] = keep

    def _invalidate_semantic_windows(self, rid):
        reply = self.scheduler.replies.get(rid)
        if reply is None:
            return
        for job in reply.jobs:
            if job.status not in {'waiting', 'scheduled'}:
                continue
            indices = (job.plan.start_unit, job.plan.arrival_unit)
            actual = tuple(reply.anchors[i]['start'] if i in reply.anchors else None for i in indices)
            if actual != (job.anchor_pair or (job.plan.start_s, job.plan.end_s)):
                job.status, job.reason = 'cancelled', 'alignment_changed'
                self._emit('gesture.cancelled', response_id=rid, job_id=job.id, reason='alignment_changed')
                self.pending_intents.setdefault(rid, []).append(dict(action=job.plan.action,
                    begin=job.plan.start_unit, finish=job.plan.arrival_unit,
                    source=job.source_units, request_id=job.request_id, waiting=False,
                    end_cap=job.plan.end_s))
                self._emit('gesture.replanning', response_id=rid, job_id=job.id,
                           reason='alignment_changed', end_cap_s=job.plan.end_s)

    def close(self, *, wait=True):
        """Stop scheduling immediately; ROS control may avoid waiting for provider I/O."""
        self.stopping.set()
        for state in list(self.replies.values()):
            state.cancelled.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=3)
        if self.pool:
            try:
                self.pool.shutdown(wait=wait, cancel_futures=True)
            except TypeError:
                self.pool.shutdown(wait=wait)
        close_planner = getattr(self.planner, 'close', None)
        if callable(close_planner):
            close_planner()
        if self.log:
            self.log.close()


def load_targets(path):
    if path is None:
        return []
    value = strict_json(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, list) or any(not isinstance(t.get('id'), str) or not t.get('id') for t in value):
        raise ValueError('Scene targets must be a list with nonempty string IDs')
    return value
