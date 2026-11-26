"""Archived anchor-based JSON/SSE planner; only development tools use it."""
import json
import threading
import time

import requests

from GuideBot.gesture.streaming import PlannerClient, ActionStream
from test.archive.anchor_planner.prompts import messages


class Planner(PlannerClient):
    def __init__(self, catalog, *, examples_path=None, **kwargs):
        super().__init__(catalog, **kwargs)
        self.examples_path = examples_path

    def plan(self, payload, on_action, cancelled=None):
        if not self.api_key:
            raise RuntimeError('DEEPSEEK_API_KEY is not set')
        cancelled = cancelled or threading.Event()
        if cancelled.is_set():
            return {'cancelled': True}
        prompt = messages(self.catalog, payload, **(
            {'examples_path': self.examples_path} if self.examples_path else {}))
        started = time.monotonic()
        stats = dict(model=self.model, first_content_seconds=None, first_action_seconds=None,
                     valid_actions=0, invalid_actions=0, invalid_reasons=[])
        stream = ActionStream()
        finished = False
        try:
            with self.session.post(self.base_url + '/chat/completions',
                                   headers={'Authorization': 'Bearer ' + self.api_key},
                                   json=dict(model=self.model, messages=prompt, stream=True,
                                             response_format={'type': 'json_object'},
                                             temperature=0, max_tokens=1200),
                                   timeout=(5, self.timeout), stream=True) as response:
                if response.status_code != 200:
                    raise RuntimeError(f'DeepSeek HTTP {response.status_code}')
                response.encoding = 'utf-8'
                for line in response.iter_lines(chunk_size=1, decode_unicode=True):
                    if cancelled.is_set():
                        return {**stats, 'cancelled': True}
                    if time.monotonic() - started > self.timeout * 2:
                        raise RuntimeError('DeepSeek total request deadline exceeded')
                    if not line or not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        break
                    packet = json.loads(data)
                    if 'error' in packet:
                        raise RuntimeError('DeepSeek stream error')
                    for choice in packet.get('choices', []):
                        reason = choice.get('finish_reason')
                        if reason is not None:
                            if reason != 'stop':
                                raise RuntimeError('DeepSeek output did not finish normally')
                            finished = True
                        content = choice.get('delta', {}).get('content') or ''
                        if content and stats['first_content_seconds'] is None:
                            stats['first_content_seconds'] = time.monotonic() - started
                        for row in stream.feed(content):
                            try:
                                plan = self.catalog.validate(row, payload['eligible_anchor_ids'], payload['targets'],
                                                             payload.get('interaction_context'))
                                if payload.get('timing_contract') == 'fixed_deadline' and plan.end_s is None:
                                    raise ValueError('Fixed playback start_s/end_s required')
                            except ValueError as error:
                                stats['invalid_actions'] += 1
                                stats['invalid_reasons'].append(str(error))
                                continue
                            if cancelled.is_set():
                                return {**stats, 'cancelled': True}
                            if stats['first_action_seconds'] is None:
                                stats['first_action_seconds'] = time.monotonic() - started
                            stats['valid_actions'] += 1
                            on_action(plan)
            if not finished:
                raise RuntimeError('DeepSeek stream ended before normal completion')
            stream.finish()
        except requests.RequestException:
            raise RuntimeError('DeepSeek network failure') from None
        stats['total_seconds'] = time.monotonic() - started
        return stats
