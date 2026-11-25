"""Translate scheduled gestures to the existing motion library socket protocol."""
import json
import os
from pathlib import Path
import time

from drivers.unitree_motion.client import request as socket_request, SOCKET_NAME


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
            payload = self.sequence(event)
            if self.mode == 'simulation':
                return {'mode': 'simulation', 'sequence': payload}
            limits = json.loads((self.catalog.limits_path).read_text())
            if limits.get('verified') is not True or not limits.get('verified_by') or not limits.get('verified_at'):
                raise ValueError('Joint limits are not verified')
            status = self.request({'状态': True})['status']
            if status.get('ownership') != 'owned':
                raise ValueError('Motion service ownership is not owned')
            if status.get('state') != 'idle':
                raise ValueError('Motion service is busy')
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
