"""Count real planner messages with official tokenizers/templates, without model inference.

Read tokenizer.json/tokenizer_config.json from a local metadata directory;
never download weights, use Torch, call a planner API, or touch robot/audio I/O.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from jinja2.sandbox import ImmutableSandboxedEnvironment
from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from GuideBot.gesture.catalog import Catalog, make_input
from test.archive.anchor_planner.prompts import messages


def fail(message):
    raise ValueError(message)


def audit(directory):
    config_path = directory / 'tokenizer_config.json'
    tokenizer_path = directory / 'tokenizer.json'
    config = json.loads(config_path.read_text())
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    environment = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    environment.globals['raise_exception'] = fail
    template = environment.from_string(config['chat_template'])

    def count(text):
        return len(tokenizer.encode(text, add_special_tokens=False).ids)

    def render(prompt):
        return template.render(messages=prompt, add_generation_prompt=True,
                               enable_thinking=False, tools=None)

    catalog = Catalog()
    report = dict(tokenizer=directory.name, enable_thinking=False,
                  source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (config_path, tokenizer_path)}, samples=[])
    texts = ['你好欢迎参观', '欢迎参观香洲创港中心。' * 21,
             '欢迎参观香洲创港中心。' * 101]
    for text in texts:
        payload = make_input('test', text)
        payload.update(timing_contract='fixed_deadline', playback_elapsed_s=2.,
                       playback_started=True, suggested_planning_lead_s=2.)
        prompt = messages(catalog, payload)
        content = [count(message['content']) for message in prompt]
        total = count(render(prompt))
        # Candidate wire format only: NOT accepted by the existing planner.
        # Absolute IDs = unit_base + array index; keep full source_units locally.
        candidate = {k: v for k, v in payload.items()
                     if k not in {'units', 'eligible_anchor_ids'}}
        candidate.update(unit_base=0, unit_texts=[u['text'] for u in payload['units']],
                         eligible_anchor_ranges=[[0, len(payload['units']) - 1]])
        candidate_json = json.dumps(candidate, ensure_ascii=False, separators=(',', ':'))
        candidate_prompt = [*prompt[:-1], dict(role='user', content=candidate_json)]
        # Plain text requires quoted-span output and local resolution rather
        # than asking a model to infer the existing numeric unit IDs.
        plain = {k: v for k, v in payload.items()
                 if k not in {'units', 'eligible_anchor_ids'}}
        plain.update(text=text, eligible_text_start_offset=0)
        plain_json = json.dumps(plain, ensure_ascii=False, separators=(',', ':'))
        plain_prompt = [*prompt[:-1], dict(role='user', content=plain_json)]
        report['samples'].append(dict(
            text=text, unicode_characters=len(text),
            han_characters=sum('\u3400' <= c <= '\u9fff' for c in text),
            source_units=len(payload['units']), raw_text_tokens=count(text),
            system_tokens=content[0], user_json_tokens=content[-1],
            chat_template_tokens=total - sum(content), full_input_tokens=total,
            message_count=len(prompt), user_json_characters=len(prompt[-1]['content']),
            units_field_tokens=count(json.dumps({'units': payload['units']}, ensure_ascii=False)),
            eligible_ids_field_tokens=count(json.dumps(
                {'eligible_anchor_ids': payload['eligible_anchor_ids']}, ensure_ascii=False)),
            independent_field_counts_are_not_additive=True,
            one_unit=payload['units'][0],
            one_unit_json_tokens=count(json.dumps(payload['units'][0], ensure_ascii=False)),
            candidate_indexed_list=dict(existing_contract_supported=False,
                                        full_input_tokens=count(render(candidate_prompt)),
                                        user_json_tokens=count(candidate_json)),
            candidate_plain_text=dict(existing_contract_supported=False,
                                      full_input_tokens=count(render(plain_prompt)),
                                      user_json_tokens=count(plain_json))))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokenizer-root', type=Path, required=True,
                        help='Directory containing one subdirectory per official tokenizer')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = dict(schema_version=1, contract='fixed_deadline',
                  sample_note='Synthetic repeated text; punctuation included in character count',
                  tokenizers=[audit(args.tokenizer_root / name) for name in
                              ('Qwen2.5-3B-Instruct', 'Qwen3-1.7B')])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for result in report['tokenizers']:
        for row in result['samples']:
            print(json.dumps(dict(tokenizer=result['tokenizer'],
                                  characters=row['unicode_characters'],
                                  raw=row['raw_text_tokens'], system=row['system_tokens'],
                                  user_json=row['user_json_tokens'],
                                  template=row['chat_template_tokens'],
                                  total=row['full_input_tokens'],
                                  candidate_total=row['candidate_indexed_list']['full_input_tokens'],
                                  plain_text_total=row['candidate_plain_text']['full_input_tokens'])))


if __name__ == '__main__':
    main()
