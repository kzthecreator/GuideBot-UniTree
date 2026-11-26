"""Server-only evaluation and prompt inspection: python -m tools.gesture."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import threading

from GuideBot.gesture.catalog import Catalog, DIRECTORY, make_input, messages, strict_json
from GuideBot.gesture.planner import Planner
from GuideBot.gesture.service import load_targets


def evaluate(args, catalog):
    raise ValueError('Legacy anchor-only evaluation has been retired; use examples/gesture_from_audio planning tools')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=Path(__file__).resolve().parents[2] / 'assets/motion/actions.json')
    sub = parser.add_subparsers(dest='command', required=True)
    prompt = sub.add_parser('prompt', help='Print the actual system prompt and few-shot messages; no network')
    prompt.add_argument('--text', default='请注意这里的沙盘。')
    prompt.add_argument('--targets', type=Path, default=DIRECTORY / 'targets.example.json')
    evaluation = sub.add_parser('evaluate', help='Send synthetic fixture text to DeepSeek; no recording uploads')
    evaluation.add_argument('--cases', type=Path, default=Path(__file__).resolve().parent / 'evaluation.json')
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
        print(json.dumps(messages(catalog, dict(make_input('preview', args.text, load_targets(args.targets), complete=True), timing_contract='semantic_keyframes', playback_elapsed_s=0., playback_started=False, suggested_planning_lead_s=2.)),
                         ensure_ascii=False, indent=2))
    elif args.command == 'evaluate':
        if not 1 <= args.repeats <= 10:
            parser.error('--repeats must be 1..10')
        parser.error('Legacy anchor-only evaluation has been retired; use examples/gesture_from_audio planning tools')
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
