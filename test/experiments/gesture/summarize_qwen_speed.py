#!/usr/bin/env python3
"""Pair same-case active outputs; never award latency credit for lost actions."""
import argparse
import json
from pathlib import Path
import statistics


def load(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def paired(before, after, key='result'):
    a={r['case_id']:r for r in before};b={r['case_id']:r for r in after}
    common=sorted(set(a)&set(b))
    active=[k for k in common if a[k]['predicted'] and b[k]['predicted']]
    correct_positive=[k for k in active if a[k]['gold']['acceptable_action_sets'][0]
                      and a[k]['production_binding_pass'] and b[k]['production_binding_pass']]
    def times(keys):
        if not keys:return None
        old=statistics.median(a[k]['seconds'] for k in keys)
        new=statistics.median(b[k]['seconds'] for k in keys)
        return dict(n=len(keys),baseline_median=old,candidate_median=new,
                    reduction_percent=100*(1-new/old))
    def output(row):
        v=row[key]
        return v['actions'] if key=='real_result' else v
    return dict(common_n=len(common),matched_active=times(active),matched_correct_positive=times(correct_positive),
                regressions=[k for k in common if a[k]['production_binding_pass'] and not b[k]['production_binding_pass']],
                improvements=[k for k in common if not a[k]['production_binding_pass'] and b[k]['production_binding_pass']],
                changed_outputs=[k for k in common if output(a[k])!=output(b[k])],
                changed_action_sets=[k for k in common if a[k]['predicted']!=b[k]['predicted']])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline',default='baseline',help='Reference configuration directory name')
    a=p.parse_args();result={'baseline':a.baseline,'phases':{},'paired':{}}
    for phase in ['repro','sweep','sweep-extra','quant-sweep','quality','production','final-sweep','challenge','final-smoke']:
        folder=a.root/phase
        if not folder.exists():continue
        result['phases'][phase]={f.parent.name:json.loads(f.read_text()) for f in sorted(folder.glob('*/summary.json'))}
        base=folder/a.baseline/'requests.jsonl'
        if base.exists():
            result['paired'][phase]={f.parent.name:paired(load(base),load(f),'real_result' if phase=='production' else 'result')
                for f in sorted(folder.glob('*/requests.jsonl'))
                if f!=base and load(f) and all('result' in r or 'real_result' in r for r in load(f))}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(a.output)
if __name__=='__main__':main()
