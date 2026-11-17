"""Server-only evaluation and prompt inspection: python -m GuideBot.gesture."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import threading

from .catalog import Catalog, DIRECTORY, make_input, messages, strict_json
from .planner import Planner
from .service import load_targets


def evaluate(args, catalog):
    planner = Planner(catalog, model=args.model)
    if not planner.api_key:
        raise RuntimeError('DEEPSEEK_API_KEY is not set; source your environment file first')
    cases = strict_json(args.cases.read_text(encoding='utf-8'))
    examples = strict_json((DIRECTORY / 'few_shots.json').read_text(encoding='utf-8'))
    shown = {a['action'] for e in examples if all(a['action'] in catalog.actions for a in e['actions'])
             for a in e['actions']}
    targets = load_targets(args.targets)
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    for repeat in range(args.repeats):
        for case in cases:
            if args.case and case['id'] not in args.case:
                continue
            plans = []
            payload = make_input(case['id'], case['text'], case.get('targets', targets), complete=True)
            try:
                stats = planner.plan(payload, lambda p: plans.append(p.as_dict()), threading.Event())
                names = [p['action'] for p in plans]
                exact = sorted(names) == sorted(case['expected']) and not stats['invalid_actions']
                parameters_ok = all(all(p.get(k) == v for k, v in case.get('parameters', {}).items())
                                    and ('target_id' not in case or p.get('target_id') == case['target_id'])
                                    for p in plans)
                row = dict(case_id=case['id'], repeat=repeat, expected=case['expected'],
                           plans=plans, detection_pass=exact, parameters_pass=exact and parameters_ok,
                           few_shot_group=('negative' if not case['expected'] else
                                           'seen' if set(case['expected']) <= shown else 'unseen'), **stats)
            except Exception as error:
                row = dict(case_id=case['id'], repeat=repeat, expected=case['expected'], plans=plans,
                           detection_pass=False, parameters_pass=False, error=str(error),
                           few_shot_group=('negative' if not case['expected'] else
                                           'seen' if set(case['expected']) <= shown else 'unseen'))
            results.append(row)
            (args.output / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
            print(case['id'], 'PASS' if row['parameters_pass'] else 'FAIL',
                  [p['action'] for p in plans], flush=True)
    summary = dict(cases=len(results), model=planner.model, shown_actions=sorted(shown),
                   registry_sha256=hashlib.sha256(json.dumps(catalog.prompt_document(), sort_keys=True,
                                                             ensure_ascii=False).encode()).hexdigest(),
                   prompt_sha256=hashlib.sha256((DIRECTORY/'prompt.md').read_bytes()).hexdigest(),
                   examples_sha256=hashlib.sha256((DIRECTORY/'few_shots.json').read_bytes()).hexdigest(),
                   registered_actions=sorted(catalog.actions), detection_pass=sum(r['detection_pass'] for r in results),
                   parameters_pass=sum(r['parameters_pass'] for r in results),
                   network_or_format_errors=sum('error' in r for r in results))
    for group in ('seen', 'unseen', 'negative'):
        rows = [r for r in results if r.get('few_shot_group') == group]
        summary[group] = dict(cases=len(rows), passed=sum(r['parameters_pass'] for r in rows))
    for metric in ('first_action_seconds', 'total_seconds'):
        values = sorted(r[metric] for r in results if r.get(metric) is not None)
        summary[metric] = dict(median=statistics.median(values), maximum=max(values)) if values else {}
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=DIRECTORY / 'actions.json')
    sub = parser.add_subparsers(dest='command', required=True)
    prompt = sub.add_parser('prompt', help='Print the actual system prompt and few-shot messages; no network')
    prompt.add_argument('--text', default='请注意这里的沙盘。')
    prompt.add_argument('--targets', type=Path, default=DIRECTORY / 'targets.example.json')
    evaluation = sub.add_parser('evaluate', help='Send synthetic fixture text to DeepSeek; no recording uploads')
    evaluation.add_argument('--cases', type=Path, default=DIRECTORY / 'evaluation.json')
    evaluation.add_argument('--targets', type=Path, default=DIRECTORY / 'targets.example.json')
    evaluation.add_argument('--model')
    evaluation.add_argument('--case', action='append')
    evaluation.add_argument('--repeats', type=int, default=1)
    evaluation.add_argument('--output', type=Path, default=Path.home() / '.local/state/guidebot/gesture-evaluation')
    replay = sub.add_parser('replay', help='Replay recorded PCM and timestamps with explicit cached plans; no network')
    replay.add_argument('--data', type=Path, required=True)
    replay.add_argument('--plans', type=Path, required=True)
    replay.add_argument('--response-id')
    replay.add_argument('--output', type=Path, required=True)
    replay.add_argument('--no-resync', action='store_true',
                        help='Disable periodic/conflict prefix resync AND complete-response full repair')
    replay.add_argument('--reuse-predictor', action='store_true',
                        help='Experimental same-window alpha reuse; does not cache encoder state')
    replay.add_argument('--tail', type=float, default=.25,
                        help='Experimental publication tail in seconds (default .25)')
    replay.add_argument('--window', type=float, default=4.)
    replay.add_argument('--step', type=float, default=.5)
    replay.add_argument('--threads', type=int, choices=range(1, 9), default=2)
    replay.add_argument('--quantized', action='store_true')
    replay.add_argument('--cursor-from-starts', action='store_true')
    replay.add_argument('--resync-every', type=float, default=10.)
    replay.add_argument('--no-final-repair', action='store_true')
    replay.add_argument('--count-offset', type=int, choices=(-2,-1,0,1), default=-1)
    args = parser.parse_args()
    catalog = Catalog(args.registry)
    if args.command == 'prompt':
        print(json.dumps(messages(catalog, make_input('preview', args.text, load_targets(args.targets), complete=True)),
                         ensure_ascii=False, indent=2))
    elif args.command == 'evaluate':
        if not 1 <= args.repeats <= 10:
            parser.error('--repeats must be 1..10')
        evaluate(args, catalog)
    else:
        if not 0 <= args.tail <= 1:
            parser.error('--tail must be in [0, 1]')
        if not 0 < args.window <= 120 or not 0 < args.step <= 10:
            parser.error('--window must be in (0,120], --step in (0,10]')
        if not 0 <= args.resync_every <= 120:
            parser.error('--resync-every must be in [0,120]')
        from .replay import replay
        replay(args, catalog)


if __name__ == '__main__':
    main()
