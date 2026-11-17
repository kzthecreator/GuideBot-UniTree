"""Load the editable action contract and validate all model output locally."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

from GuideBot.conversation.timestamps import text_units

DIRECTORY = Path(__file__).resolve().parent
COMMAND_FIELDS = {'action', 'start_unit', 'arrival_unit', 'response_id', 'job_id', 'request_id',
                  'monotonic', 'kind', 'simulated', 'start_audio_s', 'arrival_audio_s',
                  'start_monotonic', 'arrival_monotonic', 'compressed', 'alignment_version'}


def units_for(text):
    return [dict(unit_id=i, **row) for i, row in enumerate(text_units(text))]


def strict_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError('Nonfinite JSON number')
    return json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)


@dataclass(frozen=True)
class Plan:
    action: str
    start_unit: int
    arrival_unit: int
    parameters: dict

    def as_dict(self):
        return dict(action=self.action, start_unit=self.start_unit,
                    arrival_unit=self.arrival_unit, **self.parameters)

class Catalog:
    def __init__(self, path=DIRECTORY / 'actions.json'):
        self.document = strict_json(Path(path).read_text(encoding='utf-8'))
        if self.document.get('version') != 1 or not isinstance(self.document.get('actions'), list):
            raise ValueError('Unsupported action registry')
        self.actions = {}
        known = set()
        for item in self.document['actions']:
            name = item['id']
            if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', name) or name in known:
                raise ValueError('Invalid or duplicate action ID')
            known.add(name)
            if item['kind'] not in {'pose', 'motion'} or type(item.get('enabled', True)) is not bool:
                raise ValueError('Invalid action kind or enabled flag')
            properties = item['parameters']
            if not isinstance(properties, dict) or set(properties) & COMMAND_FIELDS:
                raise ValueError('Invalid action parameters')
            if not set(item['required']) <= set(properties):
                raise ValueError('Unknown required parameter')
            if item['kind'] == 'pose' and 'duration_s' in properties:
                raise ValueError('Pose cannot have duration')
            if item['kind'] == 'motion' and 'duration_s' not in item['required']:
                raise ValueError('Motion must require duration_s')
            if item['kind'] == 'motion' and (properties['duration_s']['type'] != 'number'
                                            or properties['duration_s'].get('minimum', 0) <= 0):
                raise ValueError('Motion duration must have a positive numeric lower bound')
            for spec in properties.values():
                if spec['type'] not in {'number', 'string', 'target'}:
                    raise ValueError('Unsupported parameter type')
                if spec['type'] == 'number':
                    lo, hi = spec.get('minimum'), spec.get('maximum')
                    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lo, hi)) or lo > hi:
                        raise ValueError('Numeric parameters need finite bounds')
            if item.get('enabled', True):
                self.actions[name] = item

    def prompt_document(self):
        return {**self.document, 'actions': list(self.actions.values())}

    def validate(self, row, eligible, targets):
        if not isinstance(row, dict) or not isinstance(row.get('action'), str) or row['action'] not in self.actions:
            raise ValueError('Unknown or disabled action')
        item = self.actions[row['action']]
        base = {'action', 'start_unit', 'arrival_unit'}
        if not (base | set(item['required'])) <= set(row) or set(row) - base - set(item['parameters']):
            raise ValueError('Missing or unknown action fields')
        start, arrival = row['start_unit'], row['arrival_unit']
        if any(type(i) is not int or i not in eligible for i in (start, arrival)) or start > arrival:
            raise ValueError('Invalid text anchors')
        target_ids = {t['id'] for t in targets}
        parameters = {k: v for k, v in row.items() if k not in base}
        for key, value in parameters.items():
            spec = item['parameters'][key]
            if spec['type'] == 'number':
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError('Invalid numeric parameter')
                if not spec['minimum'] <= value <= spec['maximum']:
                    raise ValueError('Numeric parameter outside registry bounds')
            elif not isinstance(value, str):
                raise ValueError('Expected string parameter')
            if 'enum' in spec and value not in spec['enum']:
                raise ValueError('Unknown parameter choice')
            if spec['type'] == 'target' and value not in target_ids:
                raise ValueError('Unknown scene target')
        return Plan(row['action'], start, arrival, parameters)


def make_input(response_id, text, targets=(), existing=(), eligible=None, complete=False):
    units = units_for(text)
    return dict(response_id=response_id, units=units,
                eligible_anchor_ids=list(range(len(units))) if eligible is None else list(eligible),
                targets=list(targets), existing_actions=list(existing), response_complete=complete)


def messages(catalog, payload, examples_path=DIRECTORY / 'few_shots.json'):
    system = (DIRECTORY / 'prompt.md').read_text(encoding='utf-8').replace(
        '{{REGISTRY}}', json.dumps(catalog.prompt_document(), ensure_ascii=False))
    result = [dict(role='system', content=system)]
    for example in strict_json(Path(examples_path).read_text(encoding='utf-8')):
        # Disabled or removed actions must not survive via historical examples.
        if any(a['action'] not in catalog.actions for a in example['actions']):
            continue
        value = make_input('example', example['text'], example['targets'], complete=True)
        for row in example['actions']:
            catalog.validate(row, value['eligible_anchor_ids'], value['targets'])
        result.extend([dict(role='user', content=json.dumps(value, ensure_ascii=False)),
                       dict(role='assistant', content=json.dumps({'actions': example['actions']}, ensure_ascii=False))])
    result.append(dict(role='user', content=json.dumps(payload, ensure_ascii=False)))
    return result
