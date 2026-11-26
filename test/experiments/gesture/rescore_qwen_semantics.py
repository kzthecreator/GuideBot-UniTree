#!/usr/bin/env python3
"""Derived scoring, preserving original request evidence unchanged."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from test.experiments.gesture.evaluate_qwen_semantics import DATA,score

def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);args=p.parse_args()
    cases={r['case_id']:r for path in [DATA/'development-seeds.jsonl',DATA/'expansion-probe.jsonl'] for r in map(json.loads,path.read_text().splitlines())}
    default={a['meaning']:a['id'] for a in json.loads((DATA/'fictional-actions.json').read_text())['actions']}
    for path in sorted(args.root.glob('*/requests.jsonl')):
        if path.parent.name=='analysis':continue
        metadata=path.parent/'metadata.json';mapping=json.loads(metadata.read_text()).get('mapping',default) if metadata.exists() else default
        out=args.root/'analysis'/path.parent.name;out.mkdir(parents=True,exist_ok=True)
        rows=[]
        for raw in map(json.loads,path.read_text().splitlines()):
            row=dict(raw,raw_mechanical_pass=raw['mechanical_pass']);style,task=raw['arm'].split(':')
            if 'result' in raw:
                row.update(score(cases[raw['case_id']],raw['result'],mapping,'J' if task=='two_stage' else task,'compact' in style))
                if task=='two_stage':row['both_stages_correct']=row['mechanical_pass'] and row.get('selection_correct',False)
                if raw.get('finish_reason','stop')!='stop':
                    row['mechanical_pass']=False
                    row['production_binding_pass']=False
            rows.append(row)
        (out/'requests.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
        print(path.parent.name,len(rows))
if __name__=='__main__':main()
