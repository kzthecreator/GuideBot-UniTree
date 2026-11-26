"""Translate scheduled gestures to the existing motion library socket protocol."""
import json
import math
import os
from pathlib import Path
import time

from drivers.unitree_motion.client import request as socket_request, SOCKET_NAME


class MotionTimingRejected(ValueError):
    """Only these fixed codes/numbers may cross IPC; no exception text."""
    def __init__(self, code, remaining_s, minimum_required_s):
        super().__init__('Insufficient remaining time before end deadline: '+code)
        self.diagnostic = dict(reason=code, remaining_s=remaining_s,
                               minimum_required_s=minimum_required_s)


class MotionExecutor:
    def __init__(self, catalog, *, mode=None, request=None, clock=time.monotonic):
        self.catalog = catalog
        self.mode = mode or os.getenv('GUIDEBOT_GESTURE_EXECUTION_MODE', 'simulation')
        if self.mode not in {'simulation', 'robot'}:
            raise ValueError('Invalid gesture execution mode')
        self.clock = clock
        if request is None:
            self.request = lambda payload: socket_request(SOCKET_NAME, payload)
        else:
            self.request = request
        self.active = None

    def sequence(self, event):
        action = event['action']
        item = self.catalog.definitions.get(action)
        scheduler_managed = event.get('scheduler_managed') is True
        if item is None or (not item.get('llm_selectable', True) and not scheduler_managed):
            raise ValueError('Unknown or disabled physical action')
        asset = self.catalog.assets[action]
        meta = asset['metadata']
        if meta['status'] != 'approved':
            raise ValueError('Motion is not approved')
        now = self.clock()
        start = event['start_monotonic']
        arrival = event['arrival_monotonic']
        end = event.get('end_monotonic', 0.)
        if event.get('timing_mode') == 'semantic_keyframes':
            from GuideBot.gesture.timing import phases
            entry, minimum, minimum_hold = phases(asset)
            core, hold = event['core_s'], event['hold_s']
            if (any(type(v) not in (int,float) or not math.isfinite(v) for v in (core,hold))
                    or core < minimum or hold < minimum_hold or core > 600 or hold > 300):
                raise ValueError('Invalid semantic phase timing')
            required = entry+core+hold
            if end-max(now,start) < required+.05:
                raise MotionTimingRejected('semantic_deadline_too_close', end-max(now,start), required+.05)
            step = dict(type=item['asset_type'], name=item['motion_name'],
                        transition_ms=1000, hold_ms=round(hold*1000))
            if core:
                step['duration_ms'] = round(core*1000)
            return {'序列': dict(sequence_name='guidebot_'+action, preserve_transition=True, steps=[step]),
                    'end_monotonic': end, 'job_id': event['job_id']}
        if end:
            if not math.isfinite(end) or not math.isfinite(start):
                raise ValueError('Action end deadline passed or invalid')
            timing = self.catalog.execution_timing(action)
            # Retain only the native resolver's existing 50ms deadline check
            # when the optional coordination reserve is disabled.
            budget_ms = max(50, round(timing['reserved_overhead_s']*1000))
            if 'minimum_total_ms' in timing:
                remaining = end-max(now, start)
                if math.floor(remaining*1000)-budget_ms < timing['minimum_total_ms']:
                    raise MotionTimingRejected('insufficient_remaining_time', remaining,
                                               timing['minimum_total_ms']/1000+budget_ms/1000)
                step = dict(type=item['asset_type'], name=item['motion_name'],
                            total_ms=min(600000, max(timing['minimum_total_ms'],
                                                    math.floor(remaining*1000)-budget_ms)))
                return {'序列': dict(sequence_name='guidebot_'+action, steps=[step]),
                        'end_monotonic': end, 'job_id': event['job_id']}
            remaining = end-max(now, start)
            if remaining <= 0:
                raise MotionTimingRejected('end_deadline_passed', remaining, timing['minimum_remaining_s'])
            # Never accelerate the recorded core. The optional coordination
            # reserve comes from the catalog; native deadline margin stays.
            core_ms = round(timing['recorded_core_s']*1000)
            minimum_entry = timing['minimum_transition_s']*1000
            available_ms = math.floor((end-max(now, start))*1000) - core_ms - budget_ms
            transition_ms = min(2000, available_ms)
            if transition_ms < minimum_entry:
                raise MotionTimingRejected('insufficient_remaining_time', remaining,
                                           timing['recorded_core_s'] + timing['minimum_transition_s'] + budget_ms/1000)
            step = dict(type=item['asset_type'], name=item['motion_name'],
                        transition_ms=transition_ms)
            if core_ms:
                step['duration_ms'] = core_ms
            return {'序列': dict(sequence_name='guidebot_'+action, steps=[step]),
                    'end_monotonic': end, 'job_id': event['job_id']}
        from drivers.unitree_motion.planning import confirmed_timing
        confirmed = confirmed_timing(meta)
        if confirmed:
            if now >= arrival or (arrival-max(now,start)) < confirmed['transition_s']:
                raise ValueError('Insufficient transition time for confirmed preview')
            return {'序列': dict(sequence_name='guidebot_'+action, steps=[dict(
                type=item['asset_type'], name=item['motion_name'],
                total_ms=min(600000, max(confirmed['minimum_total_ms'],
                    math.ceil((arrival-max(now,start))*1000 *
                              sum(meta['timing_profile']['phase_weights'].values()) /
                              meta['timing_profile']['phase_weights']['transition']))))])}
        if now >= arrival:
            raise ValueError('Action arrival deadline passed')
        available_ms = round((arrival - max(now, start)) * 1000)
        if available_ms > 30000:
            raise ValueError('Transition exceeds Sequence limit')
        profile = meta.get('timing_profile')
        if profile:
            weights = profile['phase_weights']
            minimum_entry = profile['minimum_total_ms'] * weights['transition'] / sum(weights.values())
        else:
            minimum_entry = 500
        if available_ms < minimum_entry:
            raise ValueError('Insufficient transition time for saved motion profile')
        step = {'type': item['asset_type'], 'name': item['motion_name'],
                'transition_ms': available_ms}
        if asset['frames'] > 1:
            duration_ms = round(event['duration_s'] * 1000)
            if duration_ms < meta['nominal_duration_ms']:
                raise ValueError('Core duration shorter than recorded motion')
            step['duration_ms'] = duration_ms
        return {'序列': {'sequence_name': 'guidebot_' + action, 'steps': [step]}}

    def handle(self, kind, event):
        if kind == 'gesture.command':
            if self.mode == 'robot' and self.clock() < event['start_monotonic']:
                time.sleep(event['start_monotonic'] - self.clock())
            if self.mode == 'simulation':
                return {'mode': 'simulation', 'sequence': self.sequence(event)}
            limits = json.loads((self.catalog.limits_path).read_text())
            if limits.get('verified') is not True or not limits.get('verified_by') or not limits.get('verified_at'):
                raise ValueError('Joint limits are not verified')
            status = self.request({'状态': True})['status']
            if status.get('ownership') != 'owned':
                raise ValueError('Motion service ownership is not owned')
            if status.get('state') != 'idle':
                raise ValueError('Motion service is busy')
            # Status IPC can consume the remaining window. Recompute last.
            payload = self.sequence(event)
            result = self.request(payload)
            self.active = event.get('job_id')
            return {'mode': 'robot', 'response': result}
        if kind == 'gesture.reset' and self.active is not None:
            if self.mode == 'robot':
                result = self.request({'停止': True})
            else:
                result = {'mode': 'simulation'}
            self.active = None
            return result
        return None
