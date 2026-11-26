"""Shared bounded action JSON decoding and HTTP-client configuration.

Contains no anchor prompt or legacy planning request construction.
"""
import json
import os

import requests

from GuideBot.gesture.catalog import strict_json


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


class PlannerClient:
    def __init__(self, catalog, *, api_key=None, model=None, base_url=None, timeout=20, session=None):
        self.catalog = catalog
        self.api_key = api_key if api_key is not None else os.environ.get('DEEPSEEK_API_KEY', '')
        self.model = model or os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')
        self.base_url = (base_url or os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')).rstrip('/')
        self.timeout = timeout
        self.session = session or requests
