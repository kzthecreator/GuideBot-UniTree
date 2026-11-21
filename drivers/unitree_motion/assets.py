"""Validate published motion bindings without importing authoring tools or SDKs."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'assets/motion'
DEFAULT_MANIFEST = ROOT / 'conversation.json'


def conversation_assets(manifest=DEFAULT_MANIFEST):
    manifest = Path(manifest)
    source = json.loads(manifest.read_text(encoding='utf-8'))
    if source.get('schema_version') != 1:
        raise ValueError('Unsupported conversation motion manifest')
    inventory = json.loads((ROOT/'config/motion_catalog.json').read_text())
    inventory = {item['name']: item for item in inventory['actions']}
    bindings, actions = {}, []
    for entry in source['actions']:
        if not entry.get('enabled', True):
            continue
        name = entry['asset']
        asset = inventory.get(name)
        if not asset or asset['type'] != 'motion' or entry['id'] in bindings:
            raise ValueError('Unknown, duplicate or unsupported motion binding')
        metadata = json.loads((ROOT/'metadata'/f'{name}.json').read_text())
        trajectory = ROOT/'motions'/asset['category']/f'{name}.dat'
        if metadata.get('status') != 'approved' or metadata.get('name') != name:
            raise ValueError(f'Motion not published: {name}')
        if hashlib.sha256(trajectory.read_bytes()).hexdigest() != metadata.get('sha256'):
            raise ValueError(f'Motion checksum mismatch: {name}')
        rows = trajectory.read_text().splitlines()
        if int(rows[0]) < 1 or int(rows[1]) != 14:
            raise ValueError(f'Motion needs a 14-joint trajectory: {name}')
        minimum = metadata['timing_profile']['minimum_total_ms']
        if type(minimum) is not int or minimum <= 0:
            raise ValueError('Invalid minimum motion duration')
        bindings[entry['id']] = dict(asset=name, minimum_total_ms=minimum)
        actions.append(dict(id=entry['id'], name=entry['name'], kind='motion', enabled=True,
            description=entry['description'], parameters=dict(duration_s=dict(
                type='number', minimum=minimum/1000., maximum=max(6., minimum/1000.+3.))),
            required=['duration_s']))
    if not actions:
        raise ValueError('No published conversation motions enabled')
    return dict(version=1, hardware=source['hardware'], actions=actions), bindings
