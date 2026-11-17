"""DeepSeek JSON/SSE client; secrets and provider error bodies never enter logs."""
import json
import os
import threading
import time

import requests

from .catalog import messages, strict_json


class ActionStream:
    """Decode complete action objects without guessing string/brace boundaries."""
    def __init__(self):
        self.text = ''
        self.cursor = None
        self.rows = []
        self.decoder = json.JSONDecoder()

    def feed(self, fragment):
        self.text += fragment
        if len(self.text) > 32768:
            raise ValueError('Planner output limit exceeded')
        if self.cursor is None:
            pos = len(self.text) - len(self.text.lstrip())
            if pos >= len(self.text):
                return []
            if self.text[pos] != '{':
                raise ValueError('Expected JSON object')
            pos += 1
            pos += len(self.text[pos:]) - len(self.text[pos:].lstrip())
            try:
                key, pos = self.decoder.raw_decode(self.text, pos)
            except json.JSONDecodeError:
                return []
            if key != 'actions':
                raise ValueError('Expected actions as first JSON field')
            for token in (':', '['):
                pos += len(self.text[pos:]) - len(self.text[pos:].lstrip())
                if pos >= len(self.text):
                    return []
                if self.text[pos] != token:
                    raise ValueError('Invalid actions envelope')
                pos += 1
            self.cursor = pos
        result = []
        while True:
            pos = self.cursor
            pos += len(self.text[pos:]) - len(self.text[pos:].lstrip())
            if self.rows:
                if pos >= len(self.text) or self.text[pos] == ']':
                    break
                if self.text[pos] != ',':
                    raise ValueError('Expected action separator')
                pos += 1
                pos += len(self.text[pos:]) - len(self.text[pos:].lstrip())
            if pos >= len(self.text) or self.text[pos] == ']':
                break
            try:
                row, end = self.decoder.raw_decode(self.text, pos)
            except json.JSONDecodeError:
                break
            if not isinstance(row, dict) or len(self.rows) >= 3:
                raise ValueError('Invalid action list or too many actions')
            # Re-decode with duplicate-key and nonfinite-number checks.
            row = strict_json(self.text[pos:end])
            result.append(row)
            self.rows.append(row)
            self.cursor = end
        return result

    def finish(self):
        root = strict_json(self.text)
        if not isinstance(root, dict) or set(root) != {'actions'} or root['actions'] != self.rows:
            raise ValueError('Invalid final action JSON')


class Planner:
    def __init__(self, catalog, *, api_key=None, model=None, base_url=None, timeout=20,
                 examples_path=None, session=None):
        self.catalog = catalog
        self.api_key = api_key if api_key is not None else os.environ.get('DEEPSEEK_API_KEY', '')
        self.model = model or os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')
        self.base_url = (base_url or os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')).rstrip('/')
        self.timeout = timeout
        self.examples_path = examples_path
        self.session = session or requests

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
                                plan = self.catalog.validate(row, payload['eligible_anchor_ids'], payload['targets'])
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
