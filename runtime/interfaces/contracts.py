"""Transport-independent session fencing and typed-context conversion."""
import math
import threading
import time

LIFECYCLE = {'visitor_responded', 'interaction_changed', 'task_completed', 'task_cancelled',
             'new_valid_input', 'clarification_completed', 'interaction_cancelled',
             'display_target_changed', 'explanation_ended', 'action_switch_needed'}
INPUTS = {'text', 'text_delta', 'done', 'cancel', 'playback', 'alignment', 'base_pose', 'release_pose'}


class Fence:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.session = None
        self.generation = 0
        self.sequence = 0
        self.closed = set()
        self.jobs = set()
        self.retired = set()

    def start(self, session, generation):
        with self.lock:
            if not session or generation < 1 or self.session is not None or (session, generation) in self.retired:
                raise ValueError('Session already active or invalid')
            self.session, self.generation = session, generation
            self.sequence = 0
            self.closed.clear()
            self.jobs.clear()

    def check(self, session, generation):
        if self.session is None or (session, generation) != (self.session, self.generation):
            raise ValueError('Session generation rejected')

    def input(self, session, generation, sequence, kind, response):
        with self.lock:
            self.check(session, generation)
            if kind not in INPUTS or sequence <= self.sequence:
                raise ValueError('Unknown or stale input')
            self.sequence = sequence
            if kind == 'cancel':
                self.closed.add(response)
            elif response in self.closed:
                raise ValueError('Reply already cancelled')

    def job(self, session, generation, job_id, response, arrival):
        with self.lock:
            self.check(session, generation)
            if not math.isfinite(arrival) or arrival <= self.clock():
                raise ValueError('Action deadline passed')
            if not job_id or job_id in self.jobs or response in self.closed:
                raise ValueError('Duplicate or cancelled job')
            self.jobs.add(job_id)

    def close(self):
        with self.lock:
            if self.session is not None:
                self.retired.add((self.session, self.generation))
            self.session = None


def context_to_wire(value, session, generation, version, expiry, source='operator'):
    result = dict(session_id=session, generation=generation, version=version,
                  source=source, expires_monotonic=expiry, stage=value.get('stage', 'unspecified'),
                  history=value.get('history', []), facts=value.get('facts', []),
                  lifecycle_events=[key for key in LIFECYCLE if value.get(key) is True])
    mapping = {'scene': {'confirmed': 'scene_confirmed', 'direction': 'scene_direction',
                         'target_id': 'scene_target_id'},
               'navigation': {'status': 'navigation_status', 'destination': 'destination',
                              'route_confirmed': 'route_confirmed', 'movement_allowed': 'movement_allowed'},
               'task': {'status': 'task_status'}, 'asr': {'needs_repeat': 'needs_repeat'},
               'dialogue': {'state': 'dialogue_state'}}
    for group, fields in mapping.items():
        result[group + '_valid'] = group in value
        for key, output in fields.items():
            if key in value.get(group, {}):
                result[output] = value[group][key]
    return result


def context_from_wire(value):
    result = dict(stage=value['stage'] or 'unspecified', history=value['history'], facts=value['facts'])
    mapping = {'scene': {'confirmed': 'scene_confirmed', 'direction': 'scene_direction',
                         'target_id': 'scene_target_id'},
               'navigation': {'status': 'navigation_status', 'destination': 'destination',
                              'route_confirmed': 'route_confirmed', 'movement_allowed': 'movement_allowed'},
               'task': {'status': 'task_status'}, 'asr': {'needs_repeat': 'needs_repeat'},
               'dialogue': {'state': 'dialogue_state'}}
    for group, fields in mapping.items():
        if value.get(group + '_valid'):
            result[group] = {key: value[output] for key, output in fields.items()}
    for key in value['lifecycle_events']:
        if key not in LIFECYCLE:
            raise ValueError('Unknown lifecycle')
        result[key] = True
    return result
