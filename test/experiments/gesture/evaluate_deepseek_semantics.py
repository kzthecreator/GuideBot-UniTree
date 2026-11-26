#!/usr/bin/env python3
"""Explicitly requested cloud comparison on synthetic text; no audio or robot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from dotenv import load_dotenv
import requests
from GuideBot.gesture.catalog import strict_json
from test.experiments.gesture.evaluate_qwen_semantics import DATA,prompt,score


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--data',type=Path,default=DATA/'development-seeds.jsonl')
    p.add_argument('--start',type=int,default=0)
    p.add_argument('--limit',type=int,default=48)
    args=p.parse_args()
    config=Path(os.environ.get('GUIDEBOT_CONFIG_FILE',Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'guidebot/conversation.env'))
    load_dotenv(config,override=False,interpolate=False)
    key=os.environ.get('DEEPSEEK_API_KEY','').strip()
    if not key:raise SystemExit('DEEPSEEK_API_KEY not configured')
    endpoint=os.environ.get('DEEPSEEK_BASE_URL','https://api.deepseek.com').rstrip('/')
    model=os.environ.get('DEEPSEEK_MODEL','deepseek-chat')
    args.output.mkdir(parents=True,exist_ok=True)
    acts=json.loads((DATA/'fictional-actions.json').read_text())['actions']
    mapping={x['meaning']:x['id'] for x in acts}
    system=prompt(acts,mapping,'J','full')
    frozen=Path.home()/'.local/state/guidebot/qwen-eval-20261125/full/full-J-prompt.txt'
    if system!=frozen.read_text():raise SystemExit('Frozen full prompt mismatch; do not silently change comparison')
    (args.output/'full-J-prompt.txt').write_text(system)
    meta=dict(provider='deepseek',model_requested=model,mapping=mapping,
        temperature=0,max_tokens=384,response_format={'type':'json_object'},stream=False,http_keepalive=True,
        prompt_sha256=hashlib.sha256(system.encode()).hexdigest(),data_sha256=hashlib.sha256(args.data.read_bytes()).hexdigest(),
        note='Same frozen Qwen full prompt and texts. Provider API supports JSON object; local Qwen original uses schema. Synthetic development data only.')
    (args.output/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    cases=list(map(json.loads,args.data.read_text().splitlines()))[args.start:args.start+args.limit]
    path=args.output/'requests.jsonl';done=set()
    if path.exists():done={r['case_id'] for r in map(json.loads,path.read_text().splitlines())}
    session=requests.Session()
    try:
        for case in cases:
            if case['case_id'] in done:continue
            row=dict(arm='full:J',case_id=case['case_id'],text=case['text'],gold=case['gold'],family=case['family'])
            started=time.monotonic();fatal=False
            try:
                response=session.post(endpoint+'/chat/completions',headers={'Authorization':'Bearer '+key},
                    json=dict(model=model,messages=[dict(role='system',content=system),dict(role='user',content=case['text'])],
                        temperature=0,max_tokens=384,stream=False,response_format={'type':'json_object'}),timeout=(10,60))
                if response.status_code!=200:
                    fatal=response.status_code in {401,402,403,404,429}
                    raise RuntimeError('DeepSeek HTTP '+str(response.status_code))
                packet=response.json();choice=packet['choices'][0]
                row.update(model_returned=packet.get('model'),usage=packet.get('usage'),finish_reason=choice.get('finish_reason'),content=choice['message']['content'])
                value=strict_json(row['content']);row.update(result=value,**score(case,value,mapping,'J',False))
                if row['finish_reason']!='stop':
                    row['mechanical_pass']=False;row['production_binding_pass']=False
            except requests.RequestException:
                row.update(error='DeepSeek network/transport failure',predicted=[],action_set_correct=False,mechanical_pass=False,format_and_quotes_valid=False,production_binding_pass=False,production_binding_valid=False)
            except (RuntimeError,ValueError,KeyError,TypeError) as error:
                message=str(error) if isinstance(error,RuntimeError) else 'DeepSeek envelope or output parse failure'
                row.update(error=message,predicted=[],action_set_correct=False,mechanical_pass=False,format_and_quotes_valid=False,production_binding_pass=False,production_binding_valid=False)
            row['seconds']=time.monotonic()-started
            with path.open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            print('{} bound={} {:.2f}s {}'.format(row['case_id'],row['production_binding_pass'],row['seconds'],row.get('error','')),flush=True)
            if fatal:raise SystemExit('Cloud comparison stopped: '+row['error'])
    finally:session.close()
if __name__=='__main__':main()
