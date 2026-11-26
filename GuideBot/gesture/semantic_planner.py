"""Planner semantic analyzer: fixed instruct at creation, plain text per call."""
import os
import threading
import time

import requests

from GuideBot.gesture.catalog import strict_json
from GuideBot.gesture.streaming import PlannerClient, ActionStream
from GuideBot.gesture.semantic import instructions, local_instructions, validate_output
from GuideBot.gesture.provider import provider_name, local_base_url, output_schema


class SemanticPlanner(PlannerClient):
    semantic = True

    def __init__(self, catalog, **kwargs):
        # Explicit API-key construction retains the cloud client test/tool contract.
        self.provider = kwargs.pop('provider', None) or ('deepseek' if 'api_key' in kwargs else provider_name())
        if self.provider not in {'local_qwen', 'deepseek'}:
            raise ValueError('Unknown planner provider')
        self._owns_session = kwargs.get('session') is None
        if self._owns_session:
            kwargs['session'] = requests.Session()
        if self.provider == 'local_qwen':
            kwargs['session'].trust_env = False  # localhost must bypass HTTP proxies
            kwargs.update(api_key='', base_url=local_base_url(),
                          model=os.environ.get('GUIDEBOT_PLANNER_MODEL', 'qwen3-1.7b'))
        super().__init__(catalog, **kwargs)
        self.instruct = (local_instructions(catalog) if self.provider == 'local_qwen'
                         else instructions(catalog))

    def close(self):
        if self._owns_session:
            self._owns_session = False
            self.session.close()

    incremental_actions = True

    def analyze(self, text, cancelled=None, on_action=None):
        if self.provider == 'deepseek' and not self.api_key:
            raise RuntimeError('DEEPSEEK_API_KEY is not set')
        if not isinstance(text, str) or not text or len(text) > 12000:
            raise ValueError('Invalid semantic text')
        cancelled = cancelled or threading.Event()
        if cancelled.is_set():
            return dict(cancelled=True, actions=[])
        started = time.monotonic()
        payload = dict(model=self.model, messages=[
            dict(role='system', content=self.instruct), dict(role='user', content=text)],
            stream=self.provider == 'deepseek', response_format={'type': 'json_object'}, temperature=0, max_tokens=384)
        if self.provider == 'local_qwen':
            payload.update(cache_prompt=True, chat_template_kwargs={'enable_thinking': False},
                           response_format={'type': 'json_schema', 'json_schema': {
                               'name': 'gesture_actions', 'strict': True, 'schema': output_schema(self.catalog)}})
        headers = {'Authorization': 'Bearer '+self.api_key} if self.api_key else {}
        # Each complete, validated action can reach the service before the root ends.
        try:
            with self.session.post(self.base_url+'/chat/completions',
                    headers=headers, json=payload, timeout=(5, self.timeout), stream=True) as response:
                if response.status_code != 200:
                    raise RuntimeError(f'Planner HTTP {response.status_code}')
                if payload['stream']:
                    return self._stream(response, text, cancelled, started, on_action)
                # Stream transport bytes with a bounded body and a total deadline,
                # while requesting a non-SSE JSON response from the provider.
                response.encoding = 'utf-8'
                body = bytearray()
                for fragment in response.iter_content(chunk_size=4096):
                    if cancelled.is_set():
                        return dict(cancelled=True, actions=[], total_seconds=time.monotonic()-started)
                    if time.monotonic()-started > self.timeout*2:
                        raise RuntimeError('Planner total request deadline exceeded')
                    body.extend(fragment)
                    if len(body) > 131072:
                        raise RuntimeError('Planner semantic response limit exceeded')
                try:
                    packet = strict_json(body.decode('utf-8'))
                except (ValueError, UnicodeError):
                    raise RuntimeError('Invalid Planner semantic envelope') from None
        except requests.RequestException:
            raise RuntimeError('Planner network failure') from None
        elapsed = time.monotonic()-started
        if cancelled.is_set():
            return dict(cancelled=True, actions=[], total_seconds=elapsed)
        if elapsed > self.timeout*2:
            raise RuntimeError('Planner total request deadline exceeded')
        choices = packet.get('choices', []) if isinstance(packet, dict) else []
        if (not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict)
                or choices[0].get('finish_reason') != 'stop'):
            raise RuntimeError('Planner semantic output did not finish normally')
        message = choices[0].get('message')
        content = message.get('content') if isinstance(message, dict) else None
        if not isinstance(content, str) or len(content) > 32768:
            raise RuntimeError('Invalid Planner semantic output')
        try:
            rows = validate_output(self.catalog, strict_json(content))
        except (ValueError, TypeError):
            raise RuntimeError('Invalid Planner semantic JSON') from None
        return dict(actions=rows, total_seconds=elapsed, model=self.model,
                    input_characters=len(text), protocol='semantic_v1')

    def _stream(self, response, text, cancelled, started, on_action):
        parser = ActionStream()
        pending = b''
        data = []
        size = 0
        stopped = done = False
        first_action = None
        try:
            for fragment in response.iter_content(chunk_size=1):
                if cancelled.is_set():
                    return dict(cancelled=True, actions=[], total_seconds=time.monotonic()-started)
                if time.monotonic()-started > self.timeout*2:
                    raise RuntimeError('Planner total request deadline exceeded')
                size += len(fragment)
                if size > 131072:
                    raise RuntimeError('Planner semantic response limit exceeded')
                pending += fragment
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    line = line.rstrip(b'\r')
                    if line.startswith(b'data:'):
                        data.append(line[5:].lstrip(b' '))
                    if line or not data:
                        continue
                    event = b'\n'.join(data).decode('utf-8')
                    data = []
                    if done:
                        raise ValueError('Data after DONE')
                    if event == '[DONE]':
                        done = True
                        continue
                    packet = strict_json(event)
                    if not isinstance(packet, dict) or 'error' in packet:
                        raise ValueError('Invalid stream envelope')
                    choices = packet.get('choices')
                    if choices == [] and isinstance(packet.get('usage'), dict):
                        continue
                    if not isinstance(choices, list) or len(choices) != 1:
                        raise ValueError('Invalid stream choices')
                    choice = choices[0]
                    if not isinstance(choice, dict) or choice.get('index', 0) != 0 or stopped:
                        raise ValueError('Invalid stream choice')
                    delta = choice.get('delta')
                    if not isinstance(delta, dict):
                        raise ValueError('Invalid stream delta')
                    content = delta.get('content')
                    if content is not None:
                        if not isinstance(content, str):
                            raise ValueError('Invalid stream content')
                        for row in parser.feed(content):
                            row = validate_output(self.catalog, {'actions': [row]})[0]
                            if cancelled.is_set():
                                return dict(cancelled=True, actions=[])
                            if first_action is None:
                                first_action = time.monotonic()-started
                            if on_action:
                                on_action(row)
                    finish = choice.get('finish_reason')
                    if finish is not None:
                        if finish != 'stop':
                            raise ValueError('Abnormal stream finish')
                        stopped = True
            if not stopped or not done or pending.strip() or data:
                raise ValueError('Incomplete stream')
            parser.finish()
            rows = validate_output(self.catalog, {'actions': parser.rows})
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise RuntimeError('Invalid Planner semantic stream') from None
        return dict(actions=rows, streamed=bool(on_action), total_seconds=time.monotonic()-started,
                    first_action_seconds=first_action, model=self.model,
                    input_characters=len(text), protocol='semantic_v1')
