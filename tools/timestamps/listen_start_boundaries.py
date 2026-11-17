"""Insert silence at observed start anchors without repairing missing boundaries."""
import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--response-id', required=True)
    parser.add_argument('--alignment', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True,
                        help='Separate full alignment for error diagnostics only, never audio cuts')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pause-ms', type=float, default=150)
    args = parser.parse_args()
    if not 0 < args.pause_ms <= 1000:
        parser.error('--pause-ms must be in (0, 1000]')
    rid = args.response_id
    events = [r for r in read_rows(args.data/'events.jsonl') if r.get('response_id') == rid]
    audio_origin = next(e['elapsed'] for e in events if e['type'] == 'response.audio.delta')
    playback = next(e['elapsed'] for e in events if e['type'] == 'client.playback.started')-audio_origin
    audio, rate = sf.read(args.data/'speaker-16k.wav', dtype='int16')
    segments = [audio[r['sample_offset']:r['sample_offset']+r['samples']]
                for r in read_rows(args.data/'audio-index.jsonl')
                if r['track'] == 'speaker' and r.get('response_id') == rid]
    audio = np.concatenate(segments)
    logs = [r for r in read_rows(args.alignment) if r.get('response_id') == rid]
    reference = next(r for r in reversed(read_rows(args.reference))
                     if r['kind'] == 'alignment.final' and r.get('response_id') == rid)
    refs = {r['index']: r for r in reference['timestamps']}
    first, latest = {}, {}
    for event in logs:
        if event['kind'] != 'alignment.starts':
            continue
        latest = {r['index']: dict(r) for r in event['anchors']}
        for row in event['anchors']:
            first.setdefault(row['index'], dict(row, ready_playback_s=event['replay_elapsed']-playback,
                                                first_version=event['version']))
    args.output.mkdir(parents=True, exist_ok=True)
    sf.write(args.output/'original.wav', audio, rate, subtype='PCM_16')
    silence = np.zeros(round(rate*args.pause_ms/1000), dtype=np.int16)
    for name, boundaries in [('first', first), ('latest', latest)]:
        parts, cuts, cursor = [], [], 0
        for row in sorted(boundaries.values(), key=lambda r: (r['start'], r['index'])):
            sample = round(row['start']*rate)
            if not 0 <= sample <= len(audio):
                raise ValueError('Observed anchor falls outside the PCM')
            parts.extend([audio[cursor:sample], silence])
            cuts.append(dict(row, original_sample=sample,
                             paused_time_s=(sample+len(cuts)*len(silence))/rate))
            cursor = sample
        parts.append(audio[cursor:])
        rendered = np.concatenate(parts)
        assert len(rendered) == len(audio)+len(cuts)*len(silence)
        assert np.array_equal(np.concatenate(parts[::2]), audio)
        sf.write(args.output/f'{name}-start-pauses.wav', rendered, rate, subtype='PCM_16')
        (args.output/f'{name}-cuts.json').write_text(json.dumps(cuts, ensure_ascii=False, indent=2))
    errors = [abs(row['start']-refs[i]['start']) for i, row in first.items() if i in refs]
    margins = [refs[i]['start']-row['ready_playback_s'] for i, row in first.items() if i in refs]
    ordered = [first[i]['start'] for i in sorted(first)]
    updates = [r for r in logs if r['kind'] in ('alignment.update', 'alignment.final')]
    computes = [r['compute_seconds'] for r in updates if 'compute_seconds' in r]
    summary = dict(response_id=rid, source_seconds=len(audio)/rate, pause_ms=args.pause_ms,
                   reference_role='diagnostics_only_not_ground_truth_or_audio_cuts',
                   first_anchors=len(first), latest_anchors=len(latest), total_units=len(refs),
                   missing_first_indices=sorted(set(refs)-set(first)),
                   first_start_inversions=sum(a>b for a,b in zip(ordered, ordered[1:])),
                   first_start_error_p50_ms=float(np.percentile(errors, 50)*1000) if errors else None,
                   first_start_error_p95_ms=float(np.percentile(errors, 95)*1000) if errors else None,
                   first_start_error_max_ms=max(errors)*1000 if errors else None,
                   first_ready_before_reference_start=sum(m>=0 for m in margins),
                   worst_margin_s=min(margins) if margins else None,
                   compute_median_s=float(np.median(computes)) if computes else None,
                   compute_max_s=max(computes) if computes else None,
                   prefix_resyncs=sum(r.get('scope')=='prefix_resync' for r in updates),
                   final_scope=updates[-1].get('scope') if updates else None,
                   warnings=[r for r in logs if r['kind'] in ('alignment.warning', 'alignment.error')],
                   action_pairs=[])
    for start, arrival in [(29, 31), (50, 52)]:
        pair_event = next((r for r in logs if r['kind'] == 'alignment.starts' and
                           {start, arrival} <= {a['index'] for a in r['anchors']}), None)
        if pair_event:
            pair = {a['index']: a for a in pair_event['anchors']}
            ready = pair_event['replay_elapsed']-playback
            summary['action_pairs'].append(dict(start_index=start, arrival_index=arrival,
                first_pair_ready_s=ready, start_s=pair[start]['start'], arrival_s=pair[arrival]['start'],
                start_margin_s=pair[start]['start']-ready,
                arrival_margin_s=pair[arrival]['start']-ready,
                reference_arrival_margin_s=refs[arrival]['start']-ready))
    (args.output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
