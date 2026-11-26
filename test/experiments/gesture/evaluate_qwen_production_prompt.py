#!/usr/bin/env python3
"""Real production prompt, text-only, against the shared 8-meaning development slice."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from test.experiments.gesture.evaluate_qwen_semantics import DATA,score
from GuideBot.gesture.catalog import Catalog
from GuideBot.gesture.semantic import bind,Chunk
from GuideBot.gesture.semantic_planner import SemanticPlanner
from runtime.app.planner_server import PlannerServer

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    os.environ['GUIDEBOT_PLANNER_PROVIDER']='local_qwen'
    catalog=Catalog();planner=SemanticPlanner(catalog,provider='local_qwen');server=PlannerServer(a.output)
    acts=json.loads((DATA/'fictional-actions.json').read_text())['actions'];mapping={x['meaning']:x['id'] for x in acts}
    mapping['neutral']='neutral'
    real_to_meaning={x['real_analogue']:x['meaning'] for x in acts if x['real_analogue']};real_to_meaning['greet_wave']='reception_open'
    (a.output/'production-prompt.txt').write_text(planner.instruct)
    (a.output/'metadata.json').write_text(json.dumps(dict(mapping=mapping,note='Actual SemanticPlanner; normalize greet_open/greet_wave into reception_open only for shared meaning scoring. Original real_result retained.'),ensure_ascii=False,indent=2))
    cases=list(map(json.loads,(DATA/'development-seeds.jsonl').read_text().splitlines()))[:32]
    path=a.output/'requests.jsonl'
    done={r['case_id'] for r in map(json.loads,path.read_text().splitlines())} if path.exists() else set()
    try:
        server.start()
        for case in cases:
            if case['case_id'] in done:continue
            row=dict(arm='production:J',case_id=case['case_id'],text=case['text'],gold=case['gold'],family=case['family'])
            start=time.monotonic()
            try:
                real=planner.analyze(case['text']);row['real_result']=real
                try:
                    for item in real['actions']:bind(catalog,item,Chunk(case['text'],0,case['text']))
                    row['production_bind_valid']=True
                except ValueError:row['production_bind_valid']=False
                value={'actions':[{**item,'action':mapping.get(real_to_meaning.get(item['action']),item['action'])} for item in real['actions']]}
                row.update(result=value,**score(case,value,mapping,'J',False))
            except Exception as e:row.update(error=str(e),predicted=[],mechanical_pass=False,action_set_correct=False,format_and_quotes_valid=False)
            row['seconds']=time.monotonic()-start
            with (a.output/'requests.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            print(case['case_id'],row['mechanical_pass'],flush=True)
    finally:server.stop()
if __name__=='__main__':main()
