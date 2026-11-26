"""Resolve mutable text anchors and dispatch immutable simulated commands."""
from dataclasses import dataclass, field
import math
import time

from .catalog import Plan, units_for


@dataclass
class Job:
    id: str
    plan: object
    source_units: tuple
    request_id: int
    status: str = 'waiting'
    timing: tuple = None
    reason: str = ''


@dataclass
class Reply:
    text: str = ''
    units: list = field(default_factory=list)
    anchors: dict = field(default_factory=dict)
    raw_anchors: dict = field(default_factory=dict)
    version: int = -1
    playback_origin: float = None
    jobs: list = field(default_factory=list)
    last_started_s: float = -1.


class Scheduler:
    def __init__(self, catalog, emit, clock=time.monotonic, dispatch_lead=.03,
                 pose_max_hold_s=30., immediate=False):
        if type(pose_max_hold_s) not in (int, float) or not math.isfinite(pose_max_hold_s) or pose_max_hold_s <= 0:
            raise ValueError('pose_max_hold_s must be a positive finite Scheduler setting')
        self.catalog, self.emit, self.clock = catalog, emit, clock
        self.dispatch_lead = dispatch_lead
        self.pose_max_hold_s = float(pose_max_hold_s)
        self.immediate = immediate
        self.replies = {}
        self.closed = set()
        self.active = None
        self.base_pose_serial = 0

    def release_active(self, condition):
        """Release an active pose when a trusted lifecycle condition occurs."""
        active = self.active
        if not active or self.catalog.definitions.get(active['job'].plan.action, {}).get('kind') != 'pose':
            return False
        item = self.catalog.definitions.get(active['job'].plan.action, {})
        if condition not in item.get('release_conditions', []):
            return False
        rid = active['rid']
        job = active['job']
        job.status = 'completed'
        self.active = None
        self.event('gesture.released', rid, job_id=job.id, action=job.plan.action,
                   condition=condition)
        return True

    def reply(self, rid):
        if rid in self.closed:
            return None
        return self.replies.setdefault(rid, Reply())

    def event(self, kind, rid, **details):
        return self.emit(kind, response_id=rid, **details)

    def text(self, rid, text):
        reply = self.reply(rid)
        if reply is None:
            return
        replacement = not text.startswith(reply.text)
        reply.text, reply.units = text, units_for(text)
        if replacement:
            reply.raw_anchors = {}
        reply.anchors = {i: row for i, row in reply.raw_anchors.items()
                         if i < len(reply.units) and all(row[k] == reply.units[i][k] for k in ('text', 'text_offset'))}
        for job in reply.jobs:
            if job.status in {'waiting', 'scheduled'} and (replacement or not self.matches(job, reply)):
                job.status = 'cancelled'
                self.event('gesture.cancelled', rid, job_id=job.id, reason='text_changed')

    @staticmethod
    def matches(job, reply):
        end = job.plan.arrival_unit + 1
        return tuple(reply.units[:end]) == job.source_units

    def add(self, rid, plan, source_units, request_id=0):
        reply = self.reply(rid)
        if reply is None:
            return
        # Timing or duration variation must not duplicate the same expression.
        if any(j.plan.action == plan.action and j.plan.arrival_unit == plan.arrival_unit
               for j in reply.jobs if j.status != 'cancelled'):
            self.event('gesture.duplicate', rid, action=plan.action, arrival_unit=plan.arrival_unit)
            return
        job = Job(f'{rid}:{len(reply.jobs)}', plan, tuple(source_units[:plan.arrival_unit+1]), request_id)
        if not self.matches(job, reply):
            self.event('gesture.rejected', rid, reason='stale_text', action=plan.action)
            return
        reply.jobs.append(job)
        self.event('gesture.planned', rid, job_id=job.id, request_id=request_id, **plan.as_dict())

    def alignment(self, rid, details):
        reply = self.reply(rid)
        if reply is None or details['version'] <= reply.version:
            return
        # alignment.starts is a full current snapshot, including retractions.
        rows = details['anchors']
        starts = [row['start'] for row in rows]
        indices = [row['index'] for row in rows]
        if (any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in starts)
                or any(type(i) is not int or i < 0 for i in indices)
                or indices != sorted(set(indices)) or starts != sorted(starts)):
            self.event('gesture.alignment_rejected', rid, reason='invalid_start')
            return
        reply.version = details['version']
        reply.raw_anchors = {row['index']: row for row in rows}
        reply.anchors = {row['index']: row for row in rows if row['index'] < len(reply.units)
                         and row['index'] >= 0
                         and all(row[k] == reply.units[row['index']][k] for k in ('text', 'text_offset'))}

    def playback(self, rid, origin):
        reply = self.reply(rid)
        if reply is not None and reply.playback_origin is None:
            reply.playback_origin = origin

    def request_base_pose(self, reason='interaction_state_change'):
        """Request the listening pose after cancelling any speaking action."""
        item = self.catalog.definitions.get('B_Neutral_Rest')
        asset = self.catalog.assets.get('B_Neutral_Rest')
        if not item or not asset:
            raise ValueError('Scheduler base pose is unavailable')
        now = self.clock()
        if self.active and now < self.active['busy_until']:
            return self.event('gesture.skipped', '__scheduler__', action='B_Neutral_Rest',
                              reason='upper_body_busy')
        if asset['metadata']['status'] != 'approved':
            raise ValueError('Scheduler base pose is not approved')
        if self.active:
            self.event('gesture.superseded', self.active['rid'],
                       job_id=self.active['job'].id)
        self.base_pose_serial += 1
        job = Job(f'base_pose:{self.base_pose_serial}', Plan('B_Neutral_Rest', 0, 0, {}),
                  (), 0, status='committed')
        # Leave transport margin above the native minimum 500ms transition.
        arrival = now + 2.0
        self.active = dict(rid='__scheduler__', job=job, end=None, busy_until=arrival)
        result = self.event('gesture.command', '__scheduler__', job_id=job.id,
                            action='B_Neutral_Rest', scheduler_managed=True, simulated=True,
                            start_monotonic=now, arrival_monotonic=arrival,
                            compressed=False, reason=reason)
        if isinstance(result, dict) and result.get('execution_error'):
            job.status = 'skipped'
            self.active = None
            self.event('gesture.skipped', '__scheduler__', job_id=job.id,
                       reason='execution_rejected', detail=result['execution_error'])
        return result

    def discard_request(self, rid, request_id):
        reply = self.replies.get(rid)
        if reply:
            for job in reply.jobs:
                if job.request_id == request_id and job.status in {'waiting', 'scheduled'}:
                    job.status = 'cancelled'
                    self.event('gesture.cancelled', rid, job_id=job.id, reason='planner_failed')

    def tick(self):
        now = self.clock()
        if self.active and self.active.get('release_deadline') is not None and now >= self.active['release_deadline']:
            rid, job = self.active['rid'], self.active['job']
            job.status = 'completed'
            self.active = None
            self.event('gesture.released', rid, job_id=job.id,
                       action=job.plan.action, condition='maximum_hold_time')
        if self.active and self.active['end'] is not None and now >= self.active['end']:
            self.event('gesture.completed', self.active['rid'], job_id=self.active['job'].id)
            self.active['job'].status = 'completed'
            self.active = None
        self._tick_semantic(now)
        self._tick_deadlines()
        if self.immediate:
            self._tick_immediate(now)
            return
        ready = []
        for rid, reply in self.replies.items():
            for job in reply.jobs:
                if job.plan.end_s is not None or 'keyframes' in job.plan.parameters:
                    continue
                if job.status not in {'waiting', 'scheduled'}:
                    continue
                plan = job.plan
                if reply.playback_origin is None or any(i not in reply.anchors for i in (plan.start_unit, plan.arrival_unit)):
                    job.status = 'waiting'
                    job.timing = None
                    continue
                start, arrival = (reply.anchors[i]['start'] for i in (plan.start_unit, plan.arrival_unit))
                if start > arrival:
                    self.event('gesture.alignment_rejected', rid, reason='reversed_pair')
                    continue
                timing = (start, arrival)
                if job.timing != timing:
                    self.event('gesture.scheduled' if job.timing is None else 'gesture.revised', rid,
                               job_id=job.id, start_audio_s=start, arrival_audio_s=arrival,
                               alignment_version=reply.version)
                    job.timing = timing
                job.status = 'scheduled'
                if now >= reply.playback_origin + start - self.dispatch_lead:
                    ready.append((reply.playback_origin + start, rid, reply, job))
        for _, rid, reply, job in sorted(ready, key=lambda x: (x[0], x[3].id)):
            start, arrival = job.timing
            arrival_wall = reply.playback_origin + arrival
            start_wall = reply.playback_origin + start
            if now >= arrival_wall:
                job.status = 'skipped'
                self.event('gesture.skipped', rid, job_id=job.id, reason='arrival_passed',
                           lateness_s=now-arrival_wall)
                continue
            if self.active and now < self.active['busy_until']:
                job.status = 'skipped'
                self.event('gesture.skipped', rid, job_id=job.id, reason='upper_body_busy')
                continue
            if self.active:
                self.active['job'].status = 'completed'
                self.event('gesture.superseded', self.active['rid'], job_id=self.active['job'].id)
            job.status = 'committed'
            duration = job.plan.parameters.get('duration_s')
            item = self.catalog.definitions[job.plan.action]
            is_pose = item['kind'] == 'pose'
            self.active = dict(rid=rid, job=job, end=arrival_wall+duration if duration is not None else None,
                               release_deadline=(arrival_wall+self.pose_max_hold_s
                                                 if is_pose and item.get('release_conditions') else None),
                               busy_until=arrival_wall+(duration or 0))
            result = self.event('gesture.command', rid, job_id=job.id, simulated=True,
                                **job.plan.as_dict(), start_audio_s=start, arrival_audio_s=arrival,
                                start_monotonic=max(now, start_wall), arrival_monotonic=arrival_wall,
                                compressed=now > start_wall, alignment_version=reply.version)
            if isinstance(result, dict) and result.get('execution_error'):
                job.status = 'skipped'
                self.active = None
                self.event('gesture.skipped', rid, job_id=job.id,
                           reason='execution_rejected', detail=result['execution_error'])

    def _tick_immediate(self, now):
        if self.active and now < self.active['busy_until']:
            return
        for rid, reply in self.replies.items():
            if reply.playback_origin is None:
                continue
            for job in reply.jobs:
                if job.plan.end_s is not None or 'keyframes' in job.plan.parameters:
                    continue
                if job.status != 'waiting':
                    continue
                if self.active:
                    self.active['job'].status = 'completed'
                    self.event('gesture.superseded', self.active['rid'], job_id=self.active['job'].id)
                arrival = now + 2.0
                duration = job.plan.parameters.get('duration_s')
                item = self.catalog.definitions[job.plan.action]
                job.status = 'committed'
                self.active = dict(rid=rid, job=job,
                                   end=arrival+duration if duration is not None else None,
                                   release_deadline=(arrival+self.pose_max_hold_s
                                                     if item['kind'] == 'pose' and item.get('release_conditions') else None),
                                   busy_until=arrival+(duration or 0))
                result = self.event('gesture.command', rid, job_id=job.id,
                                    **job.plan.as_dict(), simulated=True,
                                    start_monotonic=now, arrival_monotonic=arrival,
                                    timing_mode='immediate')
                if isinstance(result, dict) and result.get('execution_error'):
                    job.status = 'skipped'
                    self.active = None
                    self.event('gesture.skipped', rid, job_id=job.id,
                               reason='execution_rejected', detail=result['execution_error'])
                return

    def _tick_semantic(self, now):
        from .timing import compile_intent
        for rid, reply in self.replies.items():
            if reply.playback_origin is None:
                continue
            committed_end = max((j.timing['deadline_s'] for j in reply.jobs
                if j.status in {'committed', 'completed'} and isinstance(j.timing, dict)), default=0.)
            candidates = []
            for job in reply.jobs:
                if 'keyframes' not in job.plan.parameters or job.status not in {'waiting', 'scheduled'}:
                    continue
                frames = job.plan.parameters['keyframes']
                if any(row['unit'] not in reply.anchors for row in frames):
                    continue
                try:
                    timing = compile_intent(self.catalog.assets[job.plan.action], frames,
                                            reply.anchors, job.plan.parameters['hold_s'])
                except ValueError as error:
                    job.status = 'skipped'
                    job.reason = str(error)
                    self.event('gesture.skipped', rid, job_id=job.id, reason=job.reason)
                    continue
                candidates.append((timing['start_s'], job, timing))
            for start, job, timing in sorted(candidates, key=lambda row: row[0]):
                # Resolve conflicts before submission; never cancel a running action.
                if start < committed_end:
                    job.status = 'skipped'
                    job.reason = 'semantic_window_conflict'
                    self.event('gesture.skipped', rid, job_id=job.id, reason=job.reason)
                    continue
                if job.timing != timing:
                    job.timing = timing
                    self.event('gesture.scheduled', rid, job_id=job.id, **timing)
                job.status = 'scheduled'
                committed_end = timing['deadline_s']
                wall = reply.playback_origin + start
                # Submit ahead of the target; the host executor waits until wall.
                # This is transport lead, not extra motion/keyword time.
                if now < wall-.25:
                    continue
                if now-wall > .05 or (self.active and now < self.active['busy_until']):
                    job.status = 'skipped'
                    job.reason = 'semantic_plan_late_or_busy'
                    self.event('gesture.skipped', rid, job_id=job.id,
                               reason=job.reason, lateness_s=now-wall)
                    continue
                job.status = 'committed'
                end = reply.playback_origin+timing['deadline_s']
                self.active = dict(rid=rid, job=job, end=None, busy_until=end, deadline=True)
                result = self.event('gesture.command', rid, job_id=job.id, action=job.plan.action,
                    start_monotonic=wall, arrival_monotonic=reply.playback_origin+timing['arrival_s'],
                    end_monotonic=end, timing_mode='semantic_keyframes', simulated=True,
                    transition_s=1., core_s=timing['core_s'], hold_s=timing['hold_s'])
                if isinstance(result, dict) and result.get('execution_error'):
                    job.status = 'skipped'
                    self.active = None
                    self.event('gesture.skipped', rid, job_id=job.id,
                               reason='execution_rejected', detail=result['execution_error'])

    def _tick_deadlines(self):
        ready = []
        for rid, reply in self.replies.items():
            if reply.playback_origin is None:
                continue
            for job in reply.jobs:
                if job.plan.end_s is None or job.status != 'waiting':
                    continue
                start = reply.playback_origin + job.plan.start_s
                end = reply.playback_origin + job.plan.end_s
                if self.clock() >= start:
                    ready.append((start, rid, job, end))
        ordered = sorted(ready, key=lambda row: (row[0], row[2].id))
        live = [row for row in ordered if self.clock() < row[3]]
        newest = live[-1][2] if live else None
        for start, rid, job, end in ordered:
            if self.clock() >= end:
                job.status = 'skipped'
                self.event('gesture.skipped', rid, job_id=job.id, reason='end_deadline_passed')
                continue
            if job is not newest:
                job.status = 'skipped'
                self.event('gesture.skipped', rid, job_id=job.id, reason='newer_action_due')
                continue
            if job.plan.start_s < self.replies[rid].last_started_s:
                job.status = 'skipped'
                self.event('gesture.skipped', rid, job_id=job.id, reason='older_window_superseded')
                continue
            # Cancel, wait for the execution result and native idle in the
            # executor, then re-check the ORIGINAL deadline. Never rebase it.
            if self.active:
                previous = self.active
                result = self.event('gesture.reset', previous['rid'],
                                    job_id=previous['job'].id, reason='new_action_preempts')
                if isinstance(result, dict) and result.get('execution_error'):
                    job.status = 'skipped'
                    self.event('gesture.skipped', rid, job_id=job.id, reason='preemption_failed')
                    continue
                previous['job'].status = 'cancelled'
                self.active = None
            if self.clock() >= end:
                job.status = 'skipped'
                self.event('gesture.skipped', rid, job_id=job.id, reason='end_deadline_passed')
                continue
            job.status = 'committed'
            self.replies[rid].last_started_s = job.plan.start_s
            self.active = dict(rid=rid, job=job, end=None, busy_until=end, deadline=True)
            result = self.event('gesture.command', rid, job_id=job.id, **job.plan.as_dict(),
                                start_monotonic=start, arrival_monotonic=end,
                                end_monotonic=end, timing_mode='fixed_deadline', simulated=True)
            if isinstance(result, dict) and result.get('execution_error'):
                job.status = 'skipped'
                self.active = None
                self.event('gesture.skipped', rid, job_id=job.id, reason='execution_rejected',
                           detail=result['execution_error'])

    def planning_history(self, rid):
        reply = self.replies.get(rid)
        return [dict(j.plan.as_dict(), status=j.status, reason=j.reason, resolved_timing=j.timing)
                for j in reply.jobs if j.status != 'cancelled'] if reply else []

    def execution_result(self, job_id, success, reason=''):
        if self.active and self.active['job'].id == job_id and self.active.get('deadline'):
            active, self.active = self.active, None
            active['job'].status = 'completed' if success else 'skipped'
            active['job'].reason = reason
            self.event('gesture.completed' if success else 'gesture.skipped', active['rid'],
                       job_id=job_id, reason=reason or 'execution_result')

    def cancel(self, rid, reason='interrupted'):
        self.closed.add(rid)
        reply = self.replies.pop(rid, None)
        if reply:
            for job in reply.jobs:
                if job.status in {'waiting', 'scheduled', 'committed'}:
                    job.status = 'cancelled'
                    self.event('gesture.cancelled', rid, job_id=job.id, reason=reason)
        if self.active and self.active['rid'] == rid:
            self.active = None
            self.event('gesture.reset', rid, simulated=True, reason=reason)
