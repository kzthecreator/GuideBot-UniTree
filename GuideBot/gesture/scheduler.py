"""Resolve mutable text anchors and dispatch immutable simulated commands."""
from dataclasses import dataclass, field
import math
import time

from .catalog import units_for


@dataclass
class Job:
    id: str
    plan: object
    source_units: tuple
    request_id: int
    status: str = 'waiting'
    timing: tuple = None


@dataclass
class Reply:
    text: str = ''
    units: list = field(default_factory=list)
    anchors: dict = field(default_factory=dict)
    raw_anchors: dict = field(default_factory=dict)
    version: int = -1
    playback_origin: float = None
    jobs: list = field(default_factory=list)


class Scheduler:
    def __init__(self, catalog, emit, clock=time.monotonic, dispatch_lead=.03):
        self.catalog, self.emit, self.clock = catalog, emit, clock
        self.dispatch_lead = dispatch_lead
        self.replies = {}
        self.closed = set()
        self.active = None

    def reply(self, rid):
        if rid in self.closed:
            return None
        return self.replies.setdefault(rid, Reply())

    def event(self, kind, rid, **details):
        self.emit(kind, response_id=rid, **details)

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

    def discard_request(self, rid, request_id):
        reply = self.replies.get(rid)
        if reply:
            for job in reply.jobs:
                if job.request_id == request_id and job.status in {'waiting', 'scheduled'}:
                    job.status = 'cancelled'
                    self.event('gesture.cancelled', rid, job_id=job.id, reason='planner_failed')

    def tick(self):
        now = self.clock()
        if self.active and self.active['end'] is not None and now >= self.active['end']:
            self.event('gesture.completed', self.active['rid'], job_id=self.active['job'].id)
            self.active['job'].status = 'completed'
            self.active = None
        ready = []
        for rid, reply in self.replies.items():
            for job in reply.jobs:
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
            self.active = dict(rid=rid, job=job, end=arrival_wall+duration if duration is not None else None,
                               busy_until=arrival_wall+(duration or 0))
            self.event('gesture.command', rid, job_id=job.id, simulated=True,
                       **job.plan.as_dict(), start_audio_s=start, arrival_audio_s=arrival,
                       start_monotonic=max(now, start_wall), arrival_monotonic=arrival_wall,
                       compressed=now > start_wall, alignment_version=reply.version)

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
