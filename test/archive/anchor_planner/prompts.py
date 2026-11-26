"""Archived anchor prompt and few-shot construction, separate from live rules."""
import json
from pathlib import Path

from GuideBot.gesture.catalog import make_input, strict_json

DIRECTORY = Path(__file__).resolve().parent
PROMPT = DIRECTORY / 'prompt.md'
EXAMPLES = DIRECTORY / 'conversation-few-shots.json'


def messages(catalog, payload, examples_path=EXAMPLES):
    document = catalog.prompt_document()
    if payload.get('timing_contract') == 'fixed_deadline':
        document = dict(document, actions=[dict(item,
            parameters={k:v for k,v in item['parameters'].items() if k != 'duration_s'},
            required=[k for k in item['required'] if k != 'duration_s'],
            **catalog.execution_timing(item['id']))
            for item in document['actions']])
    system = PROMPT.read_text(encoding='utf-8').strip().replace(
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
