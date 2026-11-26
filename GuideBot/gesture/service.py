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
    submitted_version: int = -1
    submitted_at: float = 0.
    cancelled: threading.Event = field(default_factory=threading.Event)



def planning_anchors(reply, now, lead_s=2.):
    """Only known future anchors; keep unscheduled middle text eligible."""
    elapsed = max(0., now-reply.playback_origin) if reply.playback_origin is not None else 0.
    # One second entry plus planning lead after playback starts. Before playback,
    # the startup buffer supplies planning time, but cannot fix negative starts.
    earliest = elapsed + (lead_s+1. if reply.playback_origin is not None else 1.)
    covered = set()
    occupied = []
    for job in reply.jobs:
        if job.status in {'waiting', 'scheduled', 'committed', 'completed'}:
            covered.update(range(job.plan.start_unit, job.plan.arrival_unit+1))
            timing = getattr(job, 'timing', None)
            if isinstance(timing, dict):
                occupied.append((timing['start_s'], timing['deadline_s']+1.))
    return [i for i, anchor in sorted(reply.anchors.items())
            if i < len(reply.units) and anchor['start'] >= earliest and i not in covered
            and not any(start <= anchor['start'] < end for start, end in occupied)]

class GestureService:
    def __init__(self, directory, on_event=None, *, catalog=None, planner=None, targets=(),
                 debounce=.18, max_wait=.4, interaction_context=None, execution_mode=None, executor=None):
        self.directory = Path(directory)
        from .diagnostics import DialogueSummary
        self.diagnostics = DialogueSummary(self.directory)
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
                                'aligned')
        if timing_mode not in {'immediate', 'aligned'}:
            raise ValueError('Invalid gesture timing mode')
        self.scheduler = Scheduler(self.catalog, self._emit, immediate=timing_mode == 'immediate')
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
            try:
                self.diagnostics.observe(value)
            except OSError:
                pass
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
                    self._emit('gesture.text', response_id=rid, text=state.text, complete=state.complete)
                elif kind == 'alignment':
                    self._emit('gesture.alignment_snapshot', response_id=rid, anchor_count=len(value.get('anchors', [])), version=value.get('version'))
                    self.scheduler.alignment(rid, value)
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
            reply = self.scheduler.reply(rid)
            if reply is None:
                continue
            if state.text == state.submitted_text and state.complete == state.submitted_complete:
                if reply.version <= state.submitted_version or now-state.submitted_at < 1.:
                    continue
            age = now - state.changed_at if state.changed_at else 0
            boundary = re.search(r'[，。！？；：,.!?;:]\s*$', state.text)
            if not state.complete and not (age >= self.max_wait or (boundary and age >= self.debounce)):
                continue
            reply = self.scheduler.reply(rid)
            if reply is None:
                continue
            existing = self.scheduler.planning_history(rid)
            # Text sent is not text planned: revisit newly aligned, unspoken units.
            eligible = (list(range(len(reply.units))) if self.scheduler.immediate else planning_anchors(reply, now))
            if not eligible:
                continue
            signature = (state.text, state.complete, tuple(eligible),
                         tuple((a['action'], a['status'], str(a.get('keyframes'))) for a in existing))
            if signature == getattr(state, 'eligibility_signature', None):
                continue
            state.eligibility_signature = signature
            payload = make_input(rid, state.text, self.targets, existing,
                                 eligible, state.complete, self.interaction_context)
            payload['timing_contract'] = 'semantic_keyframes'
            from .timing import phases
            payload['execution_timing'] = [dict(id=name, transition_s=1.,
                minimum_core_s=phases(asset)[1], minimum_hold_s=phases(asset)[2],
                keyframe_count=asset['frames'])
                for name,asset in self.catalog.assets.items() if name in self.catalog.actions]
            payload['alignment_anchors'] = list(reply.anchors.values())
            payload['playback_elapsed_s'] = (max(0., now-reply.playback_origin)
                                             if reply.playback_origin is not None else 0.)
            payload['playback_started'] = reply.playback_origin is not None
            payload['suggested_planning_lead_s'] = 2.
            state.submitted_version = reply.version
            state.submitted_at = now
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
            directory = self.directory/'planner-requests'/('%06d' % request_id)
            directory.mkdir(parents=True, exist_ok=False)
            def save(name, value):
                (directory/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            save('input.json', dict(response_id=rid, request_id=request_id, text=text, payload=payload))
            returned=[]
            def trace(kind, value):
                if kind == 'messages':save('messages.json', value)
                elif kind == 'content':
                    with (directory/'raw-response.txt').open('a', encoding='utf-8') as output:output.write(value)
            planner=self.planner
            if isinstance(planner, Planner):
                planner=Planner(self.catalog, api_key=planner.api_key, model=planner.model,
                    base_url=planner.base_url, timeout=planner.timeout, examples_path=planner.examples_path,
                    session=planner.session, trace=trace)
            def action(plan):
                returned.append(plan.as_dict())
                save('validated-actions.json', returned)
                self.submit('action', rid, plan=plan, text=text, units=payload['units'], request_id=request_id)
            stats = planner.plan(payload, action, cancelled)
            save('result.json', stats)
            self.submit('result', rid, request_id=request_id, **stats)
        except Exception as error:
            # Only known, sanitized client errors can be logged verbatim.
            message = str(error) if type(error) is RuntimeError else type(error).__name__
            if 'directory' in locals() and directory.is_dir():
                try:
                    save('result.json', dict(error=message))
                except OSError:
                    pass
            self.submit('result', rid, request_id=request_id, error=message)

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
        if self.log:
            self.log.close()


def load_targets(path):
    if path is None:
        return []
    value = strict_json(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, list) or any(not isinstance(t.get('id'), str) or not t.get('id') for t in value):
        raise ValueError('Scene targets must be a list with nonempty string IDs')
    return value
