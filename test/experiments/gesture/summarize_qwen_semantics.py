#!/usr/bin/env python3
"""Summarize offline development results; does not equate quote validity with meaning."""
import argparse
import collections
import json
from pathlib import Path
import statistics
import random
import math


def summarize(rows):
    positive = [r for r in rows if r['gold']['acceptable_action_sets'][0]]
    negative = [r for r in rows if not r['gold']['acceptable_action_sets'][0]]
    emitted = [r for r in rows if r['predicted']]
    tp=fp=fn=0
    by_class=collections.defaultdict(lambda:[0,0,0])
    for r in rows:
        gold=set(r['gold']['acceptable_action_sets'][0]); pred=set(r['predicted'])
        tp+=len(gold&pred);fp+=len(pred-gold);fn+=len(gold-pred)
        for c in gold|pred:
            by_class[c][0]+=int(c in gold and c in pred)
            by_class[c][1]+=int(c not in gold and c in pred)
            by_class[c][2]+=int(c in gold and c not in pred)
    times=sorted(r['seconds'] for r in rows)
    families=collections.defaultdict(list)
    for row in rows: families[row['family']].append(row)
    rng=random.Random(1337); samples=[]; production_samples=[]
    names=list(families)
    for _ in range(2000):
        draw=[r for name in rng.choices(names,k=len(names)) for r in families[name]]
        samples.append(sum(r['mechanical_pass'] for r in draw)/len(draw))
        production_samples.append(sum(bool(r.get('production_binding_pass')) for r in draw)/len(draw))
    samples.sort(); production_samples.sort()
    quote_task=rows[0]['arm'].split(':')[-1] not in {'S','C'}
    return dict(n=len(rows), families=len(families), mechanical_family_bootstrap95=[samples[50],samples[1949]], production_binding_family_bootstrap95=[production_samples[50],production_samples[1949]] if quote_task else None, positive=len(positive), negative=len(negative),
        exact=sum(r['action_set_correct'] for r in rows),
        mechanical_pass=sum(r['mechanical_pass'] for r in rows),
        production_binding_pass=sum(bool(r.get('production_binding_pass')) for r in rows) if rows[0].get('production_binding_pass') is not None else None,
        emitted_production_binding_valid=sum(bool(r.get('production_binding_valid')) for r in emitted) if rows[0].get('production_binding_valid') is not None else None,
        positive_empty=sum(not r['predicted'] for r in positive),
        negative_trigger=sum(bool(r['predicted']) for r in negative),
        precision=tp/(tp+fp) if tp+fp else 0, recall=tp/(tp+fn) if tp+fn else 0,
        macro_f1=statistics.mean(2*t/(2*t+p+n) if 2*t+p+n else 0 for t,p,n in by_class.values()),
        emitted=len(emitted), emitted_quotes_valid=sum(r['format_and_quotes_valid'] for r in emitted) if quote_task else None,
        median_seconds=statistics.median(times), p95_seconds=times[math.ceil(.95*len(times))-1], emitted_median_seconds=statistics.median(r['seconds'] for r in emitted) if emitted else None,
        per_class=dict(by_class), errors=sum('error' in r for r in rows))


def main():
    p=argparse.ArgumentParser();p.add_argument('directories',type=Path,nargs='+');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    groups=collections.defaultdict(list)
    for d in a.directories:
        for r in map(json.loads,(d/'requests.jsonl').read_text().splitlines()):
            if not r['case_id'].startswith('seed_') or int(r['case_id'].split('_')[1])<=48:
                groups[d.name+'/'+r['arm']].append(r)
    result={k:summarize(v) for k,v in groups.items()}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    for k,v in result.items():print(k,json.dumps({key:val for key,val in v.items() if key!='per_class'},ensure_ascii=False))

if __name__=='__main__':main()
