"""Sonify actual simulated gesture commands without delaying recorded speech."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.timestamps.optimize_realtime import evaluate, load_cases, preview


def add_tone(audio, at, frequency, duration=.08):
    start = round(at*16000)
    size = round(duration*16000)
    tone = .18*np.sin(2*np.pi*frequency*np.arange(size)/16000)*np.sin(np.pi*np.arange(size)/size)**2
    left, right = max(0,start), min(len(audio),start+size)
    if right > left:
        audio[left:right] += tone[left-start:right-start]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('recordings'))
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads((args.run/'summary.json').read_text())
    case = next(c for c in load_cases(args.data) if c['rid']==summary['response_id'])
    reference = json.loads(args.reference.read_text())
    aligned = [json.loads(s) for s in (args.run/'alignment.jsonl').read_text().splitlines()]
    measured = [dict(row, elapsed=row['replay_elapsed'],
                     start_update=row if row['kind']=='alignment.starts' else None)
                for row in aligned if row.get('replay_elapsed') is not None]
    metrics = evaluate(case, measured, reference)
    (args.run/'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
    preview(case, metrics, args.run, measured)
    events = [json.loads(s) for s in (args.run/'gesture.jsonl').read_text().splitlines()]
    origin = summary['replay_clock_monotonic']+summary['playback_offset']
    original = case['audio'].astype(np.float32)/32768
    actual, ideal = original.copy(), original.copy()
    commands = []
    for event in events:
        if event['kind'] == 'gesture.command':
            start, arrival = event['start_monotonic']-origin, event['arrival_monotonic']-origin
            start_ref, arrival_ref = (reference[event[k]] for k in ('start_unit','arrival_unit'))
            add_tone(actual, start, 440)
            add_tone(actual, arrival, 880)
            add_tone(ideal, start_ref['start'], 440)
            add_tone(ideal, arrival_ref['start'], 880)
            commands.append(dict(action=event['action'], target=event.get('target_id'),
                                 actual_start=start, actual_arrival=arrival,
                                 reference_start=start_ref['start'], reference_arrival=arrival_ref['start'],
                                 start_error=start-start_ref['start'], arrival_error=arrival-arrival_ref['start'],
                                 start_tolerance=start_ref['end']-start_ref['start'],
                                 arrival_tolerance=arrival_ref['end']-arrival_ref['start'],
                                 compressed=event['compressed']))
        elif event['kind'] == 'gesture.skipped':
            add_tone(actual, event['monotonic']-origin, 180, .15)
            commands.append(dict(skipped=event))
    for name, audio in [('actions-realtime',actual),('actions-reference',ideal),('original',original)]:
        sf.write(args.run/(name+'.wav'), np.clip(audio,-1,1), 16000, subtype='PCM_16')
    (args.run/'action-timing.json').write_text(json.dumps(commands, ensure_ascii=False, indent=2))
    print(json.dumps(commands, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
