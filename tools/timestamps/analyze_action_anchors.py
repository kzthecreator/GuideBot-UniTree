"""Measure availability and revision separately; model agreement is not accuracy."""
import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
STATE = Path.home() / '.local/state/guidebot/server-timestamps'


def quantiles(values):
    return dict(zip(('min', 'p50', 'p95', 'max'),
                    [round(float(v), 4) for v in np.quantile(values, [0, .5, .95, 1])])) if values else {}


def commitment(starts, reference, playback, lead):
    pending, committed = {}, {}
    def dispatch(now):
        for i, row in list(pending.items()):
            due = playback + row['start'] - lead
            if due <= now:
                committed[i] = (max(row['received'], due), row['start'])
                del pending[i]
    for event in starts:
        now = event['replay_elapsed']
        dispatch(now)
        for i in event['removed_indices']:
            pending.pop(i, None)
        for row in event['anchors']:
            if row['index'] not in committed:
                pending[row['index']] = {**row, 'received': now}
        dispatch(now)
    dispatch(float('inf'))
    errors = [abs(committed[r['index']][1] - r['start']) for r in reference]
    late = [max(0, committed[r['index']][0] + lead - playback - r['start']) for r in reference]
    return dict(lead=lead, ontime=sum(v<=.001 for v in late),
                within_100ms=sum(v<=.1 for v in errors), error_seconds=quantiles(errors),
                lost_preparation_seconds=quantiles(late))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--long-folder', default='improved-starts')
    parser.add_argument('--output', type=Path, default=STATE / 'action-anchor-metrics.json')
    args = parser.parse_args()
    comparisons = json.loads((STATE / 'qwen-comparison/comparison.json').read_text())
    reports = []
    for case in comparisons:
        name = case['name']
        folder = {'long': args.long_folder, 'short': 'improved-short', 'medium': 'improved-medium'}[name]
        events = [json.loads(s) for s in (STATE / folder / 'events.jsonl').read_text().splitlines()]
        source = ROOT / 'recordings' / ('long-reply' if name == 'long' else 'live-session')
        source_events = [json.loads(s) for s in (source / 'events.jsonl').read_text().splitlines()]
        final = next(e for e in events if e['kind'] == 'alignment.final')
        source_events = [e for e in source_events if e.get('response_id') == final['response_id']]
        origin = next(e['elapsed'] for e in source_events if e['type'] == 'response.audio.delta')
        playback = next(e['elapsed'] for e in source_events if e['type'] == 'client.playback.started') - origin
        starts = [e for e in events if e['kind'] == 'alignment.starts']
        first = {}
        first_spans = {}
        for event in starts:
            for row in event['anchors']:
                first.setdefault(row['index'], (event['replay_elapsed'], row['start']))
        for event in events:
            if event['kind'] in {'alignment.update', 'alignment.final'}:
                for row in event['timestamps']:
                    first_spans.setdefault(row['index'], event['replay_elapsed'])
        reference = final['timestamps']
        margins = [playback + row['start'] - first[row['index']][0] for row in reference]
        drifts = [abs(first[row['index']][1] - row['start']) for row in reference]
        agreement = [abs(a['start'] - b['start_time']) for a, b in zip(reference, case['qwen'])]
        assert [r['text'] for r in reference] == [r['text'] for r in case['qwen']]
        keywords = []
        for word in ['GuideBot', '创港中心', '招商中心', '沙盘', '企业展示墙', '前台']:
            offset = case['text'].find(word)
            if offset < 0:
                continue
            row = next(r for r in reference if r['text_offset'] == offset)
            i = row['index']
            transition = reference[max(0, i-2)]
            pair_ready = max(first[i][0], first[transition['index']][0])
            keywords.append(dict(text=word, index=i, final_start=row['start'],
                                 first_start_margin=playback+row['start']-first[i][0],
                                 first_full_span_margin=playback+row['start']-first_spans[i],
                                 first_to_final_shift=abs(first[i][1]-row['start']),
                                 qwen_disagreement=agreement[i],
                                 surrogate_transition_start_index=transition['index'],
                                 surrogate_two_unit_pair_margin=playback+transition['start']-pair_ready,
                                 commitment_300ms=commitment(starts, [row], playback, .3)))
        report = dict(name=name, units=len(reference), playback_offset=playback,
                      first_publication=starts[0]['replay_elapsed'],
                      margin_seconds=quantiles(margins), first_to_final_shift=quantiles(drifts),
                      qwen_final_start_disagreement=quantiles(agreement),
                      max_start_revision_ms=max(c['shift_ms'] for e in starts for c in e['changes']),
                      start_retractions=sum(len(e['removed_indices']) for e in starts),
                      full_span_ontime=sum(playback+r['start']>=first_spans[r['index']] for r in reference),
                      budget_sweep={str(b): sum(m >= b for m in margins) for b in [0, .1, .3, .5, 1.]},
                      commitment_sweep=[commitment(starts, reference, playback, lead) for lead in [0, .3, .5, 1.]],
                      opening_3s=dict(units=sum(r['start']<3 for r in reference),
                                      ontime=sum(m>=0 for r,m in zip(reference,margins) if r['start']<3)),
                      keywords=keywords)
        reports.append(report)
    args.output.write_text(json.dumps(reports, ensure_ascii=False, indent=2))
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
