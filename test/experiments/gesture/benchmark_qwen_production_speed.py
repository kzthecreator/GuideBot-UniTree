#!/usr/bin/env python3
"""Actual SemanticPlanner requests on 32 shared texts, no audio or motion."""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import requests
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from test.experiments.gesture.benchmark_qwen_speed import CONFIGS,Server
from test.experiments.gesture.evaluate_qwen_semantics import DATA,score
from GuideBot.gesture.catalog import Catalog
from GuideBot.gesture.semantic import bind,Chunk
from GuideBot.gesture.semantic_planner import SemanticPlanner


class CaptureSession(requests.Session):
 """Capture the existing streamed envelope; parse telemetry outside client timer."""
 def post(self,*args,**kwargs):
  response=super().post(*args,**kwargs)
  original=response.iter_content
  self.body=bytearray()
  def chunks(*chunk_args,**chunk_kwargs):
   for fragment in original(*chunk_args,**chunk_kwargs):
    self.body.extend(fragment)
    yield fragment
  response.iter_content=chunks
  return response


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--configs',nargs='+',choices=sorted(CONFIGS),default=['baseline','ngram-map'])
 a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 actions=json.loads((DATA/'fictional-actions.json').read_text())['actions']
 mapping={x['meaning']:x['id'] for x in actions};mapping['neutral']='neutral'
 reverse={x['real_analogue']:x['meaning'] for x in actions if x['real_analogue']};reverse['greet_wave']='reception_open'
 cases=list(map(json.loads,(DATA/'development-seeds.jsonl').read_text().splitlines()))[:32]
 for name in a.configs:
  d=a.output/name
  if (d/'summary.json').exists():continue
  rows=[]
  with Server(d,CONFIGS[name]) as server:
   os.environ.update(GUIDEBOT_PLANNER_PROVIDER='local_qwen',GUIDEBOT_PLANNER_MODEL='qwen-speed',GUIDEBOT_PLANNER_BASE_URL=server.url+'/v1')
   catalog=Catalog();session=CaptureSession();planner=SemanticPlanner(catalog,provider='local_qwen',session=session)
   (d/'prompt.txt').write_text(planner.instruct)
   (d/'metadata.json').write_text(json.dumps(dict(config=CONFIGS[name],note='Actual production client; telemetry parsed outside total_seconds; first request retained.'),indent=2))
   # First real request is retained to distinguish fresh-service speed.
   with (d/'requests.jsonl').open('w') as f:
    for case in cases:
     real=planner.analyze(case['text'])
     packet=json.loads(session.body.decode('utf-8'))
     valid=True
     try:
      for item in real['actions']:bind(catalog,item,Chunk(case['text'],0,case['text']))
     except ValueError:valid=False
     value={'actions':[{**item,'action':mapping.get(reverse.get(item['action']),item['action'])} for item in real['actions']]}
     row=dict(case_id=case['case_id'],text=case['text'],gold=case['gold'],real_result=real,seconds=real['total_seconds'],timings=packet.get('timings'),usage=packet.get('usage'),production_bind_valid=valid,**score(case,value,mapping,'J',False))
     row['production_binding_pass']=bool(row['production_binding_pass'] and valid)
     rows.append(row);f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
     print(name,case['case_id'],row['production_binding_pass'],round(row['seconds'],3),flush=True)
   planner.session.close()
  active=[r for r in rows if r['predicted']]
  summary=dict(n=len(rows),pass_count=sum(r['production_binding_pass'] for r in rows),positive_empty=sum(not r['predicted'] for r in rows if r['gold']['acceptable_action_sets'][0]),negative_trigger=sum(bool(r['predicted']) for r in rows if not r['gold']['acceptable_action_sets'][0]),active_count=len(active),active_median=statistics.median(r['seconds'] for r in active) if active else None,generated_tps_median=statistics.median(r['timings']['predicted_per_second'] for r in active) if active else None,output_tokens_median=statistics.median(r['usage']['completion_tokens'] for r in active) if active else None,first_seconds=rows[0]['seconds'])
  (d/'summary.json').write_text(json.dumps(summary,indent=2));print('SUMMARY',name,json.dumps(summary),flush=True)
if __name__=='__main__':main()
