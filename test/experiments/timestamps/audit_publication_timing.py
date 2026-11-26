"""Audit first streaming anchors versus final repair and estimated playback."""
import argparse
import json
from pathlib import Path
import statistics


def audit(events, alignment):
    reports = []
    origins = {e['response_id']:e['elapsed'] for e in events if e['type']=='client.playback.started'}
    for rid, origin in origins.items():
        starts = [e for e in alignment if e.get('response_id')==rid and e['type']=='alignment.starts']
        finals = [e for e in alignment if e.get('response_id')==rid and e['type']=='alignment.final']
        if not starts or not finals:
            reports.append(dict(response_id=rid, complete_reference=False))
            continue
        reference = finals[-1]['timestamps']
        first = {}
        for event in starts:
            for row in event['anchors']:
                first.setdefault(row['index'], (event['elapsed'], row['start']))
        rows = []
        for ref in reference:
            if ref['index'] not in first:
                continue
            received, initial = first[ref['index']]
            rows.append(dict(index=ref['index'], lead_s=origin+ref['start']-received,
                             first_start_error_s=abs(initial-ref['start'])))
        lead = [r['lead_s'] for r in rows]
        reports.append(dict(response_id=rid, complete_reference=True,
            full_repair_reference=finals[-1].get('full_repair', True), total_units=len(reference),
            published_units=len(rows), before_speech=sum(t>=0 for t in lead),
            at_least_half_second_early=sum(t>=.5 for t in lead),
            min_lead_s=min(lead) if lead else None, median_lead_s=statistics.median(lead) if lead else None,
            first_start_within_100ms_of_final=sum(r['first_start_error_s']<=.1 for r in rows), units=rows))
    return dict(note='Final repair is model agreement, not acoustic ground truth; playback is submission-based estimate.',
                responses=reports)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--replay', type=Path, help='Replay events.jsonl whose clock starts at the first audio delta')
    args = parser.parse_args()
    events = [json.loads(s) for s in (args.session/'events.jsonl').read_text().splitlines()]
    if args.replay:
        raw = [json.loads(s) for s in args.replay.read_text().splitlines()]
        origins = {}
        for event in events:
            if event['type'] == 'response.audio.delta':
                origins.setdefault(event['response_id'], event['elapsed'])
        alignment = [dict(e, type=e['kind'], elapsed=e['replay_elapsed']+origins[e['response_id']])
                     for e in raw if e.get('response_id') in origins and e.get('replay_elapsed') is not None]
    else:
        alignment = [json.loads(s) for s in (args.session/'alignment.jsonl').read_text().splitlines()]
    report = audit(events, alignment)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for r in report['responses']:
        print(json.dumps({k:v for k,v in r.items() if k!='units'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
