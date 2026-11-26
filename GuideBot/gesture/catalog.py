"""Load the editable action contract and validate all model output locally."""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
from drivers.unitree_motion import assets as motion_library

from drivers.timestamps.runtime import text_units

DIRECTORY = Path(__file__).resolve().parent
from drivers.unitree_motion.paths import ASSETS as MOTION_ROOT, LIMITS
REGISTRY = MOTION_ROOT / 'actions.json'
EXAMPLES = MOTION_ROOT / 'conversation-few-shots.json'
# Temporarily disabled for prompt experiments; keep the native deadline check.
EXECUTION_COORDINATION_RESERVE_S = 0.0
COMMAND_FIELDS = {'action', 'start_unit', 'arrival_unit', 'response_id', 'job_id', 'request_id',
                  'monotonic', 'kind', 'simulated', 'start_audio_s', 'arrival_audio_s',
                  'start_monotonic', 'arrival_monotonic', 'compressed', 'alignment_version',
                  'start_s', 'end_s', 'end_monotonic'}


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
    start_s: float = None
    end_s: float = None

    def as_dict(self):
        result = dict(action=self.action, start_unit=self.start_unit,
                      arrival_unit=self.arrival_unit, **self.parameters)
        if self.start_s is not None:
            result.update(start_s=self.start_s, end_s=self.end_s)
        return result

class Catalog:
    def __init__(self, path=REGISTRY, motion_root=MOTION_ROOT, limits_path=LIMITS):
        self.document = strict_json(Path(path).read_text(encoding='utf-8'))
        if self.document.get('version') != 1 or not isinstance(self.document.get('actions'), list):
            raise ValueError('Unsupported action registry')
        self.actions = {}
        self.definitions = {}
        self.assets = {}
        self.motion_root = Path(motion_root)
        self.limits_path = Path(limits_path)
        self.library = motion_library
        entries = motion_library.catalog_entries(self.motion_root / 'config/motion_catalog.json')
        # Prosody and semantic motions share the same planner and arm scheduler.
        from drivers.unitree_motion.planning import description_action
        prosody_path = self.motion_root / 'prosody_catalog.json'
        rows = list(self.document['actions'])
        if prosody_path.is_file():
            prosody = strict_json(prosody_path.read_text(encoding='utf-8'))
            if prosody.get('version') != 1 or not isinstance(prosody.get('actions'), list):
                raise ValueError('Unsupported prosody registry')
            for row in prosody['actions']:
                entry = entries.get(row['id'])
                if entry is None:
                    raise ValueError('Unknown prosody physical motion')
                meta_path = self.motion_root / 'metadata' / (row['id'] + '.json')
                meta = strict_json(meta_path.read_text(encoding='utf-8')) if meta_path.is_file() else {}
                if type(row.get('enabled', False)) is not bool:
                    raise ValueError('Invalid prosody availability flag')
                item = description_action(entry, meta, description=row.get('description',''),
                                          label=row.get('label',''), enabled=row.get('enabled',False))
                item.update(gesture_group='prosody', gesture_subcategory=row.get('gesture_subcategory',row.get('family','')))
                rows.append(item)
        known = set()
        physical_names = set()
        for item in rows:
            name = item['id']
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_]+', name) or name in known:
                raise ValueError('Invalid or duplicate action ID')
            known.add(name)
            if item['kind'] not in {'pose', 'motion'} or type(item.get('enabled', True)) is not bool:
                raise ValueError('Invalid action kind or enabled flag')
            motion_name = item.get('motion_name')
            if motion_name not in entries or item.get('asset_type') != entries[motion_name]['type']:
                raise ValueError('Unknown physical motion or asset type')
            if motion_name in physical_names or name != motion_name:
                raise ValueError('Each physical motion needs one stable matching action ID')
            physical_names.add(motion_name)
            simple = item.get('selection_mode') == 'description'
            selectable = item.get('llm_selectable', True)
            if type(selectable) is not bool or type(item.get('verified', False)) is not bool:
                raise ValueError('Invalid action availability flags')
            for field in ('trigger_source', 'hold_policy', 'post_action_policy'):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise ValueError('Missing action lifecycle policy')
            action_context = item.get('context_requirements')
            if not isinstance(action_context, list) or not all(
                    isinstance(value, str) and value.strip() for value in action_context):
                raise ValueError('Invalid action context requirements')
            release_conditions = item.get('release_conditions', [])
            if not isinstance(release_conditions, list) or not all(
                    isinstance(value, str) and value.strip() for value in release_conditions):
                raise ValueError('Invalid release conditions')
            if item['kind'] == 'pose' and selectable and not release_conditions:
                raise ValueError('Selectable poses need explicit release conditions')
            for field in ('semantic_intents', 'example_phrases'):
                values = item.get(field)
                if not isinstance(values, list) or (selectable and not simple and not values) or not all(
                        isinstance(value, str) and value.strip() for value in values):
                    raise ValueError('Invalid action semantics')
            functions = item.get('interaction_functions')
            if not isinstance(functions, list) or (selectable and not simple and not functions):
                raise ValueError('Invalid interaction functions')
            function_ids = set()
            for function in functions:
                if not isinstance(function, dict) or not re.fullmatch(
                        r'[a-z][a-z0-9_]*', function.get('function', '')):
                    raise ValueError('Invalid interaction function')
                if function['function'] in function_ids:
                    raise ValueError('Duplicate interaction function')
                function_ids.add(function['function'])
                for field in ('description', 'avoid_when'):
                    if not isinstance(function.get(field), str) or not function[field].strip():
                        raise ValueError('Missing interaction function guidance')
                for field in ('example_phrases', 'context_requirements'):
                    values = function.get(field)
                    if not isinstance(values, list) or not values or not all(
                            isinstance(value, str) and value.strip() for value in values):
                        raise ValueError('Invalid interaction function examples or context')
            for field in (('description',) if simple else ('description', 'when_to_use', 'avoid_when')):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise ValueError('Missing action description')
            properties = item['parameters']
            if not isinstance(properties, dict) or set(properties) & COMMAND_FIELDS:
                raise ValueError('Invalid action parameters')
            if not set(item['required']) <= set(properties):
                raise ValueError('Unknown required parameter')
            self.definitions[name] = item
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
            result, errors, _ = motion_library.inspect(
                motion_name, entries, self.motion_root / 'motions',
                self.motion_root / 'poses', self.motion_root / 'metadata')
            if not errors and result and result[1] and result[1].get('schema_version') == 3:
                points, meta = result
                if item['kind'] != ('motion' if len(points) > 1 else 'pose'):
                    raise ValueError('Planner kind does not match recorded frame count')
                self.assets[name] = dict(entry=entries[motion_name], metadata=meta,
                                         frames=len(points), points=points)
            if (item.get('enabled', True) and item['verified'] and selectable and name in self.assets
                    and self.assets[name]['metadata']['status'] == 'approved'):
                self.actions[name] = item

    def prompt_document(self):
        return {**self.document, 'actions': list(self.actions.values())}

    def execution_timing(self, action):
        asset = self.assets[action]
        meta = asset['metadata']
        from drivers.unitree_motion.planning import confirmed_timing
        confirmed = confirmed_timing(meta)
        if confirmed:
            return dict(recorded_core_s=confirmed['core_s'],
                        minimum_transition_s=confirmed['transition_s'],
                        reserved_overhead_s=EXECUTION_COORDINATION_RESERVE_S,
                        minimum_remaining_s=confirmed['minimum_total_ms']/1000+EXECUTION_COORDINATION_RESERVE_S,
                        minimum_total_ms=confirmed['minimum_total_ms'])
        core = meta['nominal_duration_ms']/1000. if asset['frames'] > 1 else 0.
        transition = .5
        profile = meta.get('timing_profile')
        if profile:
            weights = profile['phase_weights']
            transition = max(transition, profile['minimum_total_ms']/1000. *
                             weights['transition']/sum(weights.values()))
        return dict(recorded_core_s=core, minimum_transition_s=transition,
                    reserved_overhead_s=EXECUTION_COORDINATION_RESERVE_S, minimum_remaining_s=core+transition+EXECUTION_COORDINATION_RESERVE_S)

    @staticmethod
    def context_allows(item, context):
        """Context is advisory; all registered actions may be selected without it."""
        return True

    def validate(self, row, eligible, targets, interaction_context=None, *, enforce_context=True):
        if not isinstance(row, dict) or not isinstance(row.get('action'), str) or row['action'] not in self.actions:
            raise ValueError('Unknown or disabled action')
        item = self.actions[row['action']]
        if 'keyframes' in row:
            if set(row) - {'action', 'keyframes', 'hold_s'}:
                raise ValueError('Unknown semantic intent fields')
            frames = row['keyframes']
            asset = self.assets[row['action']]
            if not isinstance(frames, list) or not 1 <= len(frames) <= asset['frames']:
                raise ValueError('Invalid semantic keyframes')
            for frame in frames:
                if (not isinstance(frame, dict) or set(frame) != {'frame', 'unit'}
                        or type(frame['frame']) is not int or not 0 <= frame['frame'] < asset['frames']
                        or type(frame['unit']) is not int or frame['unit'] not in eligible):
                    raise ValueError('Invalid semantic keyframe anchor')
            if any(b['frame'] <= a['frame'] or b['unit'] <= a['unit'] for a,b in zip(frames,frames[1:])):
                raise ValueError('Semantic keyframes must increase')
            hold = row.get('hold_s', 0.)
            if type(hold) not in (int,float) or not math.isfinite(hold) or not 0 <= hold <= 30:
                raise ValueError('Invalid semantic hold')
            return Plan(row['action'], frames[0]['unit'], frames[-1]['unit'],
                        dict(keyframes=frames, hold_s=hold))
        if enforce_context and not self.context_allows(item, interaction_context):
            raise ValueError('Trusted interaction context does not satisfy action trigger source')
        base = {'action', 'start_unit', 'arrival_unit'}
        deadline = 'start_s' in row or 'end_s' in row
        required = set(item['required'])
        if deadline:
            base |= {'start_s', 'end_s'}
            required -= {'duration_s'}
            start_s, end_s = row.get('start_s'), row.get('end_s')
            if (any(type(t) not in (int, float) or not math.isfinite(t) for t in (start_s, end_s))
                    or not 0 <= start_s < end_s <= 300):
                raise ValueError('Invalid fixed playback window')
        if not (base | required) <= set(row) or set(row) - base - set(item['parameters']):
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
        return Plan(row['action'], start, arrival, parameters,
                    row.get('start_s'), row.get('end_s'))


def make_input(response_id, text, targets=(), existing=(), eligible=None, complete=False,
               interaction_context=None):
    units = units_for(text)
    return dict(response_id=response_id, units=units,
                eligible_anchor_ids=list(range(len(units))) if eligible is None else list(eligible),
                targets=list(targets), existing_actions=list(existing), response_complete=complete,
                interaction_context=interaction_context or {'stage': 'unspecified', 'history': []})


def original_prompt_template():
    """Keep the historical file intact, translate physical IDs when using it."""
    template = (DIRECTORY/'prompt_original.md').read_text(encoding='utf-8')
    mapping = strict_json((MOTION_ROOT/'action-id-migration.json').read_text(encoding='utf-8'))['mapping']
    pattern = r'(?<![A-Za-z0-9_-])('+'|'.join(map(re.escape,mapping))+r')(?![A-Za-z0-9_-])'
    return re.sub(pattern, lambda match: mapping[match[0]], template)


def original_messages(catalog, payload, examples_path=EXAMPLES):
    document = catalog.prompt_document()
    if payload.get('timing_contract') == 'fixed_deadline':
        document = dict(document, actions=[dict(item,
            parameters={k:v for k,v in item['parameters'].items() if k != 'duration_s'},
            required=[k for k in item['required'] if k != 'duration_s'],
            **catalog.execution_timing(item['id']))
            for item in document['actions']])
    system = original_prompt_template().replace(
        '{{REGISTRY}}', json.dumps(document, ensure_ascii=False))
    result = [dict(role='system', content=system)]
    for example in strict_json(Path(examples_path).read_text(encoding='utf-8')):
        if payload.get('timing_contract') == 'fixed_deadline':
            # Historical examples use arrival+duration, not fixed end windows.
            continue
        # Disabled or removed actions must not survive via historical examples.
        if any(a['action'] not in catalog.actions for a in example['actions']):
            continue
        value = make_input('example', example['text'], example['targets'], complete=True,
                           interaction_context=example.get('interaction_context'))
        for row in example['actions']:
            catalog.validate(row, value['eligible_anchor_ids'], value['targets'], value['interaction_context'])
        result.extend([dict(role='user', content=json.dumps(value, ensure_ascii=False)),
                       dict(role='assistant', content=json.dumps({'actions': example['actions']}, ensure_ascii=False))])
    result.append(dict(role='user', content=json.dumps(payload, ensure_ascii=False)))
    return result


def minimal_document(catalog):
    """Expose only identity, physical description and the actual duration floor."""
    path = DIRECTORY / 'prompt_descriptions.json'
    overrides = strict_json(path.read_text(encoding='utf-8')) if path.is_file() else dict(version=1, actions={})
    if overrides.get('version') != 1 or not isinstance(overrides.get('actions'), dict):
        raise ValueError('Invalid physical prompt descriptions')
    actions = []
    for name, item in catalog.actions.items():
        description = item['description']
        override = overrides['actions'].get(name)
        meta = catalog.assets[name]['metadata']
        if override and override.get('sha256') == meta['sha256']:
            description = override['description']
        if not isinstance(description, str) or not description.strip():
            raise ValueError('Missing physical action description: ' + name)
        timing = catalog.execution_timing(name)
        minimum = timing.get('minimum_total_ms', max(0., timing['minimum_remaining_s'] - timing['reserved_overhead_s'])*1000)/1000
        # Round upward to milliseconds, without exposing floating point noise.
        minimum = math.ceil(minimum*1000 - 1e-7)/1000
        actions.append(dict(id=name, description=description, minimum_duration_s=minimum))
    return dict(actions=actions)


def messages(catalog, payload, examples_path=EXAMPLES, *, prompt_variant=None):
    variant = prompt_variant or os.environ.get('GUIDEBOT_GESTURE_PROMPT', 'minimal')
    if variant not in {'minimal', 'original'}:
        raise ValueError('GUIDEBOT_GESTURE_PROMPT must be minimal or original')
    if payload.get('timing_contract') == 'semantic_keyframes':
        from .timing import phases
        document = minimal_document(catalog)
        for row in document['actions']:
            row['minimum_duration_s'] = round(sum(phases(catalog.assets[row['id']])), 3)
        prompt_file = 'prompt_preplan.md' if payload.get('planning_mode') == 'whole_text_preplan' else 'prompt_stream.md'
        system = (DIRECTORY/prompt_file).read_text(encoding='utf-8').replace(
            '{{REGISTRY}}', json.dumps(document, ensure_ascii=False, indent=2))
        return [dict(role='system', content=system),
                dict(role='user', content=json.dumps(payload, ensure_ascii=False))]
    if variant == 'original' or payload.get('timing_contract') != 'fixed_deadline':
        # Legacy anchor-only callers keep their original parameter contract.
        return original_messages(catalog, payload, examples_path)
    document = minimal_document(catalog)
    system = (DIRECTORY/'prompt.md').read_text(encoding='utf-8').replace(
        '{{REGISTRY}}', json.dumps(document, ensure_ascii=False, indent=2))
    # No historical semantic few-shots in the experimental description-only prompt.
    return [dict(role='system', content=system),
            dict(role='user', content=json.dumps(payload, ensure_ascii=False))]
