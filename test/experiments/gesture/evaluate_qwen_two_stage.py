#!/usr/bin/env python3
"""Actual sequential selection then localization; counts both calls and upstream errors."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from test.experiments.gesture.evaluate_qwen_semantics import DATA, prompt, schema, score
from runtime.app.planner_server import PlannerServer
from GuideBot.gesture.provider import local_base_url
import requests


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--limit',type=int,default=48);p.add_argument('--style',default='examples');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    actions=json.loads((DATA/'fictional-actions.json').read_text())['actions'];mapping={x['meaning']:x['id'] for x in actions}
    cases=list(map(json.loads,(DATA/'development-seeds.jsonl').read_text().splitlines()))[:a.limit]
    os.environ['GUIDEBOT_PLANNER_PROVIDER']='local_qwen';server=PlannerServer(a.output);http=requests.Session();http.trust_env=False
    def call(task,text):
        payload=dict(model='qwen3-1.7b',messages=[dict(role='system',content=prompt(actions,mapping,task,a.style)),dict(role='user',content=text)],temperature=0,max_tokens=384,seed=42,stream=False,cache_prompt=True,chat_template_kwargs={'enable_thinking':False},response_format={'type':'json_schema','json_schema':{'name':'experiment','strict':True,'schema':schema(list(mapping.values()),task)}})
        r=http.post(local_base_url()+'/chat/completions',json=payload,timeout=(5,90));r.raise_for_status();packet=r.json()
        if packet['choices'][0]['finish_reason']!='stop':raise ValueError('unfinished')
        return json.loads(packet['choices'][0]['message']['content']),packet
    (a.output/'metadata.json').write_text(json.dumps(dict(model='qwen3-1.7b',mapping=mapping,style=a.style,temperature=0,seed=42,max_tokens_per_call=384,thinking=False,cache_prompt=True,runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),note='Actual serial two-call requests; selection error retained in mechanical pass.'),ensure_ascii=False,indent=2))
    path=a.output/'requests.jsonl';done=set()
    if path.exists():done={x['case_id'] for x in map(json.loads,path.read_text().splitlines())}
    try:
        server.start()
        for case in cases:
            if case['case_id'] in done:continue
            row=dict(arm=a.style+':two_stage',case_id=case['case_id'],text=case['text'],gold=case['gold'],family=case['family'])
            start=time.monotonic()
            try:
                selection,packet=call('S',case['text']);row.update(selection=selection,selection_packet=packet)
                selected=selection['actions']
                if selected:
                    result,packet=call('Q','给定动作ID：'+json.dumps(selected)+'\n播报原文：'+case['text']);row['localization_packet']=packet
                else:result={'actions':[]}
                row.update(result=result,**score(case,result,mapping,'J',False))
                # Report upstream errors separately; allow genuine final-stage correction.
                upstream=score(case,selection,mapping,'S',False)
                row['selection_correct']=upstream['action_set_correct']
                row['both_stages_correct']=row['mechanical_pass'] and row['selection_correct']
            except Exception as e:row.update(error=str(e),predicted=[],mechanical_pass=False,action_set_correct=False,format_and_quotes_valid=False)
            row['seconds']=time.monotonic()-start
            with path.open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            print(case['case_id'],row['mechanical_pass'],round(row['seconds'],2),flush=True)
    finally:server.stop();http.close()
if __name__=='__main__':main()
