#!/usr/bin/env python3
"""Paired comparison report; no requests, credentials, audio or robot operations."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from GuideBot.gesture.catalog import strict_json
from test.experiments.gesture.evaluate_qwen_semantics import DATA,score
from test.experiments.gesture.summarize_qwen_semantics import summarize


def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path,default=Path.home()/'.local/state/guidebot/experiments/qwen-vs-deepseek');a=p.parse_args()
    root=Path(__file__).resolve().parents[3]
    out=a.output;out.mkdir(parents=True,exist_ok=True)
    cases={r['case_id']:r for path in [DATA/'development-seeds.jsonl',DATA/'expansion-probe.jsonl'] for r in map(json.loads,path.read_text().splitlines())}
    mapping={x['meaning']:x['id'] for x in json.loads((DATA/'fictional-actions.json').read_text())['actions']}
    def read(path):
        rows=[]
        for raw in map(json.loads,path.read_text().splitlines()):
            r=dict(raw)
            try:
                value=strict_json(r['content']) if 'content' in r else r['result']
                r.update(result=value,**score(cases[r['case_id']],value,mapping,'J',False))
                if r.get('finish_reason','stop')!='stop':r['production_binding_pass']=False;r['mechanical_pass']=False
            except (ValueError,KeyError,TypeError):
                r.update(production_binding_pass=False,production_binding_valid=False,mechanical_pass=False,format_and_quotes_valid=False,action_set_correct=False,predicted=[])
            rows.append(r)
        return rows
    def metrics(rows):
        v=summarize(rows);times=sorted(r['seconds'] for r in rows)
        pos=[r['seconds'] for r in rows if r['gold']['acceptable_action_sets'][0]]
        v.update(max_seconds=max(times),positive_input_median_seconds=statistics.median(pos) if pos else None,
            unique_texts=len({r['case_id'] for r in rows}),returned_models=dict(collections.Counter(r.get('model_returned','qwen3-1.7b') for r in rows)),
            input_tokens=sum(r.get('usage',{}).get('prompt_tokens',0) for r in rows),
            output_tokens=sum(r.get('usage',{}).get('completion_tokens',0) for r in rows),
            cached_input_tokens=sum(r.get('usage',{}).get('prompt_cache_hit_tokens',r.get('usage',{}).get('prompt_tokens_details',{}).get('cached_tokens',0)) for r in rows))
        return v
    groups={name:read(a.root/name/'requests.jsonl') for name in ['deepseek-main','deepseek-probe','deepseek-edges','qwen-best-main','qwen-best-probe','qwen-json-main','qwen-json-probe']}
    for phase in ['main','probe']:
        assert len(groups['deepseek-'+phase])==48 and len(groups['qwen-best-'+phase])==48
        assert {r['case_id'] for r in groups['deepseek-'+phase]}=={r['case_id'] for r in groups['qwen-best-'+phase]}
    groups['deepseek-all']=groups['deepseek-main']+groups['deepseek-probe']
    groups['qwen-best-all']=groups['qwen-best-main']+groups['qwen-best-probe']
    groups['qwen-json-all']=groups['qwen-json-main']+groups['qwen-json-probe']
    historical=Path.home()/'.local/state/guidebot/qwen-eval-20261125/analysis/thinking/requests.jsonl'
    groups['qwen-thinking-12']=read(historical)
    ids={r['case_id'] for r in groups['qwen-thinking-12']}
    groups['deepseek-same-12']=[r for r in groups['deepseek-all'] if r['case_id'] in ids]
    groups['qwen-best-same-12']=[r for r in groups['qwen-best-all'] if r['case_id'] in ids]
    summary={k:metrics(v) for k,v in groups.items()}
    paired={}
    for phase in ['main','probe','all']:
        ds={r['case_id']:r for r in groups['deepseek-'+phase]};qs={r['case_id']:r for r in groups['qwen-best-'+phase]}
        counts=collections.Counter();byfamily=collections.defaultdict(list)
        for cid,d in ds.items():
            q=qs[cid];counts[(bool(d['production_binding_pass']),bool(q['production_binding_pass']))]+=1
            byfamily[d['family']].append(int(bool(d['production_binding_pass']))-int(bool(q['production_binding_pass'])))
        rng=random.Random(1337);names=list(byfamily);diff=[]
        for _ in range(2000):
            values=[v for f in rng.choices(names,k=len(names)) for v in byfamily[f]];diff.append(statistics.mean(values))
        diff.sort()
        paired[phase]=dict(both_pass=counts[(True,True)],deepseek_only=counts[(True,False)],qwen_only=counts[(False,True)],both_fail=counts[(False,False)],family_bootstrap95_difference=[diff[50],diff[1949]])
    hashes={name:hashlib.sha256((a.root/name/'full-J-prompt.txt').read_bytes()).hexdigest() for name in ['deepseek-main','qwen-best-main','qwen-json-main']}
    assert len(set(hashes.values()))==1
    (out/'metrics.json').write_text(json.dumps(dict(groups=summary,paired=paired,prompt_hashes=hashes),ensure_ascii=False,indent=2))
    failures=['# 同文本成对差异\n','通过=动作集合正确+现有原文绑定；不是独立语义锚点复核。\n']
    for phase in ['main','probe']:
        q={r['case_id']:r for r in groups['qwen-best-'+phase]}
        for d in groups['deepseek-'+phase]:
            r=q[d['case_id']]
            if d['production_binding_pass'] and r['production_binding_pass']:continue
            failures += ['## '+d['case_id'],d['text'],'', '预期：`'+json.dumps(d['gold']['acceptable_action_sets'],ensure_ascii=False)+'`',
              '','DeepSeek：`'+json.dumps(d.get('result'),ensure_ascii=False)+'`',
              '','Qwen：`'+json.dumps(r.get('result'),ensure_ascii=False)+'`','']
    (out/'paired-failures.md').write_text('\n'.join(failures))
    for k in ['deepseek-all','qwen-best-all','qwen-json-all','deepseek-same-12','qwen-thinking-12','qwen-best-same-12']:
        v=summary[k];print(k,json.dumps({x:v[x] for x in ['n','production_binding_pass','recall','negative_trigger','negative','emitted_production_binding_valid','emitted','median_seconds','emitted_median_seconds','p95_seconds','max_seconds','input_tokens','output_tokens']},ensure_ascii=False))
    print('Paired',json.dumps(paired,ensure_ascii=False))
if __name__=='__main__':main()
