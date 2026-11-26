"""Planner provider selection, independent of audio and robot initialization."""
import os
from urllib.parse import urlparse


def provider_name():
    name = os.environ.get('GUIDEBOT_PLANNER_PROVIDER', 'deepseek')
    if name not in {'local_qwen', 'deepseek'}:
        raise ValueError('Unknown GUIDEBOT_PLANNER_PROVIDER')
    return name


def validate_configuration():
    if provider_name() == 'deepseek':
        if not os.environ.get('DEEPSEEK_API_KEY', '').strip():
            raise ValueError('DEEPSEEK_API_KEY is required for DeepSeek')
    else:
        local_base_url()


def local_base_url():
    value = os.environ.get('GUIDEBOT_PLANNER_BASE_URL', 'http://127.0.0.1:8088/v1').rstrip('/')
    parsed = urlparse(value)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != '/v1'):
        raise ValueError('Local planner requires http://127.0.0.1:PORT/v1')
    return value


def output_schema(catalog):
    quote = dict(type='object', additionalProperties=False,
                 required=['text', 'occurrence'], properties={
                     'text': dict(type='string', minLength=1),
                     'occurrence': dict(type='integer', minimum=1)})
    actions = [a['id'] for a in catalog.actions.values()
               if not (set(a['parameters']) - {'duration_s'})]
    return dict(type='object', additionalProperties=False, required=['actions'], properties={
        'actions': dict(type='array', maxItems=3, items=dict(type='object',
            additionalProperties=False, required=['action', 'begin', 'finish_by'], properties={
                'action': dict(type='string', enum=actions), 'begin': quote, 'finish_by': quote}))})
