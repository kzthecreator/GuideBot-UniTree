"""Plain-text semantic protocol and exact local quote binding. No audio or clocks."""
from dataclasses import dataclass
import json
import unicodedata

from GuideBot.gesture.catalog import units_for
from GuideBot.configuration import read_prompt


@dataclass(frozen=True)
class Chunk:
    text: str
    offset: int
    snapshot: str


def next_chunk(text, offset, complete=False, minimum=10):
    """Earliest punctuation boundary with ten letters/numbers; keep exact source."""
    count = 0
    for i in range(offset, len(text)):
        char = text[i]
        count += unicodedata.category(char)[0] in {'L', 'N'}
        if char not in '，。！？；：,.!?;:' or count < minimum:
            continue
        if char == '.' and i and text[i-1].isalnum():
            # A delta may end in a decimal/abbreviation prefix. Wait to know
            # the next character; EOF still provides the final boundary.
            if i+1 == len(text) and not complete:
                continue
            if i+1 < len(text) and text[i+1].isalnum():
                continue
        end = i+1
        while end < len(text) and text[end] in '”’"\'）)]】》':
            end += 1
        return Chunk(text[offset:end], offset, text)
    if complete and count >= minimum:
        return Chunk(text[offset:], offset, text)
    return None


def instructions(catalog):
    actions = [dict(id=a['id'], description=a['description'],
                    when_to_use=a['when_to_use'], avoid_when=a['avoid_when'])
               for a in catalog.actions.values()
               if not (set(a['parameters']) - {'duration_s'})]
    prompt = read_prompt('actions/prompt.md')
    # Only registry data is appended; every instruction lives in the visible file.
    return prompt + '\n' + json.dumps(actions, ensure_ascii=False, separators=(',', ':'))


def validate_output(catalog, value):
    if not isinstance(value, dict) or set(value) != {'actions'}:
        raise ValueError('Invalid semantic envelope')
    rows = value['actions']
    if not isinstance(rows, list) or len(rows) > 3:
        raise ValueError('Invalid semantic action count')
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'action', 'begin', 'finish_by'}:
            raise ValueError('Invalid semantic action fields')
        action = row['action']
        if not isinstance(action, str) or action not in catalog.actions:
            raise ValueError('Unknown semantic action')
        if set(catalog.actions[action]['parameters']) - {'duration_s'}:
            raise ValueError('Unsupported semantic parameters')
        for name in ('begin', 'finish_by'):
            ref = row[name]
            if (not isinstance(ref, dict) or set(ref) != {'text', 'occurrence'}
                    or not isinstance(ref['text'], str) or not ref['text']
                    or type(ref['occurrence']) is not int or ref['occurrence'] < 1):
                raise ValueError('Invalid semantic quote')
    return rows


def bind(catalog, row, chunk):
    """Return old unit IDs locally, never ask the model to count characters."""
    validate_output(catalog, {'actions': [row]})
    units = units_for(chunk.snapshot)
    offsets = {u['text_offset']: u['unit_id'] for u in units}
    indices = []
    for name in ('begin', 'finish_by'):
        ref = row[name]
        matches = [i for i in range(len(chunk.text)) if chunk.text.startswith(ref['text'], i)]
        if ref['occurrence'] > len(matches):
            raise ValueError('quote_not_found')
        offset = chunk.offset + matches[ref['occurrence']-1]
        if offset not in offsets:
            raise ValueError('quote_not_unit_boundary')
        end = offset + len(ref['text'])
        if any(u['text_offset'] < end < u['text_offset'] + len(u['text']) for u in units):
            raise ValueError('quote_not_unit_boundary')
        indices.append(offsets[offset])
    if indices[0] >= indices[1]:
        raise ValueError('quote_order_invalid')
    return indices[0], indices[1], tuple(units[:indices[1]+1])


def local_instructions(catalog):
    """Both providers use the same visible prompt, followed only by registry data."""
    return instructions(catalog)
