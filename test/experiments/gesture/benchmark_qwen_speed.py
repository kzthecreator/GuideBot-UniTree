#!/usr/bin/env python3
"""Isolated native-CUDA speed/quality lab. Own port/process; no API/audio/motion."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
import requests
from test.experiments.gesture.evaluate_qwen_semantics import DATA,prompt,schema,score
from GuideBot.gesture.catalog import strict_json
BASE=Path.home()/'.local/share/guidebot'
WEIGHT=BASE/'models/qwen3-1.7b/Qwen3-1.7B-Q8_0.gguf'
CONFIGS={
 'baseline':{},'flash-on':{'flash':'on'},'flash-off':{'flash':'off'},
 'threads1':{'threads':1},'threads2':{'threads':2},'threads8':{'threads':8},
 'max128':{'max_tokens':128},
 'tuple':{'protocol':'tuple'},
 'json-object':{'json_object':True},
 'ngram-map':{'extra':['--spec-type','ngram-map-k','--spec-ngram-map-k-size-n','4','--spec-ngram-map-k-size-m','16','--spec-ngram-map-k-min-hits','1']},
 'ctx2304':{'ctx':2304},'kv-q8':{'flash':'on','kv':'q8_0'},
 'ngram':{'extra':['--spec-type','ngram-simple','--spec-ngram-simple-size-n','8','--spec-ngram-simple-size-m','16']},
 'ngram4x8':{'extra':['--spec-type','ngram-simple','--spec-ngram-simple-size-n','4','--spec-ngram-simple-size-m','8']},
 'ngram8x8':{'extra':['--spec-type','ngram-simple','--spec-ngram-simple-size-n','8','--spec-ngram-simple-size-m','8']},
 'ngram4x16':{'extra':['--spec-type','ngram-simple','--spec-ngram-simple-size-n','4','--spec-ngram-simple-size-m','16']},
 'q4':{'model':str(WEIGHT.parent/'bartowski/Qwen_Qwen3-1.7B-Q4_K_M.gguf')},
 'q5':{'model':str(WEIGHT.parent/'bartowski/Qwen_Qwen3-1.7B-Q5_K_M.gguf')},
 'q6':{'model':str(WEIGHT.parent/'bartowski/Qwen_Qwen3-1.7B-Q6_K.gguf')},
}
CONFIGS['qwen06']={'model':str(BASE/'models/qwen3-0.6b/Qwen3-0.6B-Q8_0.gguf')}
CONFIGS['qwen06-ngram']={**CONFIGS['qwen06'],**CONFIGS['ngram']}

def protocol(system, output_schema, config):
 """Offline wire variant retaining both quotes and occurrence indices."""
 if config.get('protocol') != 'tuple':return system,output_schema
 old='actions中每项包含action、begin、finish_by。begin与finish_by均为{"text":"原文连续引用","occurrence":1}。'
 new='actions中每项是五元素数组：[动作ID,begin原文引用,begin出现次数,finish_by原文引用,finish_by出现次数]。'
 if old not in system:raise ValueError('Output contract changed')
 system=system.replace(old,new)
 lines=[]
 for line in system.splitlines():
  if line.startswith('输出：'):
   value=json.loads(line[3:])
   value={'actions':[[a['action'],a['begin']['text'],a['begin']['occurrence'],a['finish_by']['text'],a['finish_by']['occurrence']] for a in value['actions']]}
   line='输出：'+json.dumps(value,ensure_ascii=False,separators=(',',':'))
  lines.append(line)
 output_schema=json.loads(json.dumps(output_schema))
 ids=output_schema['properties']['actions']['items']['properties']['action']['enum']
 output_schema['properties']['actions']['items']={'type':'array','prefixItems':[{'type':'string','enum':ids},{'type':'string','minLength':1},{'type':'integer','minimum':1},{'type':'string','minLength':1},{'type':'integer','minimum':1}],'minItems':5,'maxItems':5}
 return '\n'.join(lines),output_schema

def canonical(value, config):
 if config.get('protocol') != 'tuple':return value
 return {'actions':[{'action':a,'begin':{'text':b,'occurrence':bn},'finish_by':{'text':e,'occurrence':en}} for a,b,bn,e,en in value['actions']]}

class Server:
 def __init__(self,directory,config):
  self.directory=directory;self.config=config;self.process=self.log=None
  self.http=requests.Session();self.http.trust_env=False
 def __enter__(self):
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  self.url='http://127.0.0.1:'+str(port)
  c=self.config;self.directory.mkdir(parents=True,exist_ok=True)
  self.args=[str(BASE/'deps/llama.cpp/build/bin/llama-server'),'--model',c.get('model',str(WEIGHT)),
   '--alias','qwen-speed','--host','127.0.0.1','--port',str(port),'--ctx-size',str(c.get('ctx',4096)),
   '--parallel','1','--threads',str(c.get('threads',4)),'--threads-batch','4','--device','CUDA0','--n-gpu-layers','99',
   '--log-verbosity','4','--fit','off','--cache-type-k',c.get('kv','f16'),'--cache-type-v',c.get('kv','f16'),
   '--jinja','--reasoning','off','--no-webui']
  if 'flash' in c:self.args+=['--flash-attn',c['flash']]
  self.args+=c.get('extra',[])
  (self.directory/'server-command.json').write_text(json.dumps(self.args,indent=2))
  self.log=(self.directory/'server.log').open('w')
  env={k:v for k,v in os.environ.items() if not k.startswith(('DEEPSEEK_','STEP_','DOUBAO_'))}
  self.process=subprocess.Popen(self.args,stdout=self.log,stderr=subprocess.STDOUT,env=env)
  try:
   end=time.monotonic()+60
   while time.monotonic()<end:
    if self.process.poll() is not None:raise RuntimeError('Native server exited; see server.log')
    try:
     if self.http.get(self.url+'/health',timeout=1).status_code==200:return self
    except requests.RequestException:pass
    time.sleep(.1)
   raise RuntimeError('Native server startup timeout')
  except BaseException:self.__exit__(None,None,None);raise
 def __exit__(self,*_):
  if self.process is not None and self.process.poll() is None:
   self.process.terminate()
   try:self.process.wait(timeout=10)
   except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
  if self.log:self.log.close()
  self.http.close()
 def call(self,payload):
  start=time.monotonic();r=self.http.post(self.url+'/v1/chat/completions',json=payload,timeout=(5,90));r.raise_for_status()
  packet=r.json();return packet,time.monotonic()-start

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--configs',nargs='+',choices=sorted(CONFIGS),default=['baseline']);p.add_argument('--mode',choices=['smoke','sweep','quality','challenge'],default='sweep')
 p.add_argument('--require-median-under',type=float);p.add_argument('--repeat',type=int,default=3)
 args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
 actions=json.loads((DATA/'fictional-actions.json').read_text())['actions'];mapping={a['meaning']:a['id'] for a in actions}
 base_system=prompt(actions,mapping,'J','full');base_schema=schema(list(mapping.values()),'J')
 seeds=list(map(json.loads,(DATA/'development-seeds.jsonl').read_text().splitlines()))
 cases=seeds[:48]
 if args.mode=='quality':cases+=list(map(json.loads,(DATA/'expansion-probe.jsonl').read_text().splitlines()))
 elif args.mode=='challenge':cases=seeds[48:64]
 elif args.mode=='smoke':cases=[cases[i] for i in [0,8,20]]
 else:cases=[r for i,r in enumerate(cases) if i%4 in {0,2}]
 summaries={}
 for name in args.configs:
  c=CONFIGS[name];d=args.output/name;d.mkdir(parents=True,exist_ok=True)
  system,output_schema=protocol(base_system,base_schema,c)
  if (d/'summary.json').exists():
   summaries[name]=json.loads((d/'summary.json').read_text());print('REUSE',name,flush=True);continue
  rows=[]
  # A partial run has no summary: restart it rather than appending duplicate cases.
  (d/'requests.jsonl').write_text('')
  def payload(text,forced=False):
   v=dict(model='qwen-speed',messages=[dict(role='system',content=system),dict(role='user',content=text)],stream=False,temperature=0,seed=42,max_tokens=128 if forced else c.get('max_tokens',384),cache_prompt=True,chat_template_kwargs={'enable_thinking':False})
   if forced:v['ignore_eos']=True
   elif c.get('json_object'):v['response_format']={'type':'json_object'}
   else:v['response_format']={'type':'json_schema','json_schema':{'name':'speed','strict':True,'schema':output_schema}}
   return v
  (d/'prompt.txt').write_text(system)
  (d/'metadata.json').write_text(json.dumps(dict(config=c,mode=args.mode,repeat=args.repeat,prompt_sha256=hashlib.sha256(system.encode()).hexdigest(),note='seconds is HTTP-envelope elapsed only, score outside timer; compare against same-harness baseline.'),indent=2))
  try:
   with Server(d,c) as server:
    server.call(payload(cases[0]['text'])) # warmup excluded
    if args.mode!='smoke':
     core=[]
     for rep in range(3):
      packet,seconds=server.call(payload(cases[0]['text'],True));core.append(dict(seconds=seconds,timings=packet.get('timings'),usage=packet.get('usage')))
     (d/'fixed128.json').write_text(json.dumps(core,ensure_ascii=False,indent=2))
    for rep in range(args.repeat if args.mode=='smoke' else 1):
     for case in cases:
      packet,seconds=server.call(payload(case['text']));choice=packet['choices'][0]
      row=dict(case_id=case['case_id'],text=case['text'],family=case['family'],gold=case['gold'],repeat=rep,seconds=seconds,content=choice['message']['content'],usage=packet.get('usage'),timings=packet.get('timings'),finish_reason=choice['finish_reason'])
      try:
       value=canonical(strict_json(row['content']),c);row.update(result=value,**score(case,value,mapping,'J',False))
       if row['finish_reason']!='stop':row['production_binding_pass']=False
      except (ValueError,KeyError,TypeError):row.update(error='Output contract/parse failure',predicted=[],production_binding_pass=False)
      rows.append(row)
      with (d/'requests.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
      print(name,case['case_id'],row['production_binding_pass'],round(seconds,3),flush=True)
   active=[r for r in rows if r['predicted']];pos=[r for r in rows if r['gold']['acceptable_action_sets'][0]];neg=[r for r in rows if not r['gold']['acceptable_action_sets'][0]]
   summary=dict(n=len(rows),pass_count=sum(bool(r['production_binding_pass']) for r in rows),positive_empty=sum(not r['predicted'] for r in pos),negative_trigger=sum(bool(r['predicted']) for r in neg),active_count=len(active),active_median=statistics.median(r['seconds'] for r in active) if active else None,generated_tps_median=statistics.median(r['timings']['predicted_per_second'] for r in active) if active else None,output_tokens_median=statistics.median(r['usage']['completion_tokens'] for r in active) if active else None)
   if args.mode!='smoke':summary['fixed128_tps_median']=statistics.median(r['timings']['predicted_per_second'] for r in core)
  except Exception as error:summary=dict(error=str(error),completed=len(rows))
  (d/'summary.json').write_text(json.dumps(summary,indent=2));summaries[name]=summary;print('SUMMARY',name,json.dumps(summary),flush=True)
 (args.output/'summaries.json').write_text(json.dumps(summaries,indent=2))
 if args.require_median_under is not None:
  if any(v.get('active_median') is None or v['active_median']>args.require_median_under for v in summaries.values()):raise SystemExit(2)
if __name__=='__main__':main()
