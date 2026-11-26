#!/usr/bin/env python3
"""Historical non-SSE latency probe (retired after production switched to SSE).

Instrument existing requests/urllib3 calls; do not replace transport behavior.
Never record credentials, request headers, or provider error bodies.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import socket
import statistics
import sys
import time
from unittest.mock import patch
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
import requests
import urllib3.connection
import urllib3.util.connection
from dotenv import load_dotenv
from GuideBot.gesture.catalog import Catalog
from GuideBot.gesture.semantic_planner import SemanticPlanner
import GuideBot.gesture.semantic_planner as semantic_module

TEXTS=[
 '各位朋友，欢迎来到展厅，请告诉我您最想了解的内容。',
 '接下来，请看左侧的机器人演示区，了解机械臂的工作方式。',
 '在继续介绍之前，请留意右侧的绿色能源展柜。',
 '这里的讲解已经结束，请各位跟随我前往下一处展台。',
 '为了核对最新开放时间，请大家稍等片刻。',
 '刚才现场声音有点大，我没有听清，请您再说一次需求。',
 '这台设备使用电力驱动，展馆在每周二进行例行维护。',
 '档案记载，去年开馆仪式上有人说过欢迎各位来宾。',
]


class Trace:
 def __init__(self):self.row=None
 def start(self):
  self.started=time.monotonic();self.row=dict(dns_ms=0.,tcp_setup_ms=0.,tls_setup_ms=0.,new_connections=0,json_decode_ms=[])
  self.body=bytearray()
 def instrument(self,stack):
  original_dns=socket.getaddrinfo
  original_tcp=urllib3.util.connection.create_connection
  original_tls=urllib3.connection._ssl_wrap_socket_and_match_hostname
  original_send=requests.Session.send
  original_json=semantic_module.strict_json
  original_validate=semantic_module.validate_output
  def dns(*a,**k):
   start=time.monotonic()
   try:return original_dns(*a,**k)
   finally:
    if self.row is not None:self.row['dns_ms']+=(time.monotonic()-start)*1000
  def tcp(*a,**k):
   start=time.monotonic();prior=self.row['dns_ms'] if self.row is not None else 0.
   try:return original_tcp(*a,**k)
   finally:
    if self.row is not None:
     self.row['new_connections']+=1
     self.row['tcp_setup_ms']+=max(0.,(time.monotonic()-start)*1000-(self.row['dns_ms']-prior))
  def tls(*a,**k):
   start=time.monotonic()
   try:return original_tls(*a,**k)
   finally:
    if self.row is not None:self.row['tls_setup_ms']+=(time.monotonic()-start)*1000
  def send(session,request,**kwargs):
   response=original_send(session,request,**kwargs)
   if self.row is None:return response
   self.row.update(headers_ms=(time.monotonic()-self.started)*1000,status=response.status_code,
                   server_timing=response.headers.get('Server-Timing'),redirects=len(response.history),body_chunks=0)
   original_chunks=response.iter_content
   def chunks(*a,**k):
    for fragment in original_chunks(*a,**k):
     now=(time.monotonic()-self.started)*1000
     self.row.setdefault('first_transport_chunk_ms',now)
     if fragment.strip():self.row.setdefault('first_nonwhite_chunk_ms',now)
     self.row['body_chunks']+=1;self.body.extend(fragment)
     yield fragment
    self.row['body_complete_ms']=(time.monotonic()-self.started)*1000
   response.iter_content=chunks
   return response
  def decode(*a,**k):
   start=time.monotonic()
   try:return original_json(*a,**k)
   finally:
    if self.row is not None:self.row['json_decode_ms'].append((time.monotonic()-start)*1000)
  def validate(*a,**k):
   start=time.monotonic()
   try:return original_validate(*a,**k)
   finally:
    if self.row is not None:self.row['contract_validate_ms']=(time.monotonic()-start)*1000
  for target,value in [('socket.getaddrinfo',dns),('urllib3.util.connection.create_connection',tcp),
      ('urllib3.connection._ssl_wrap_socket_and_match_hostname',tls),('requests.Session.send',send),
      ('GuideBot.gesture.semantic_planner.strict_json',decode),('GuideBot.gesture.semantic_planner.validate_output',validate)]:
   stack.enter_context(patch(target,value))
 def finish(self,result):
  row=self.row;row['validated_total_ms']=(time.monotonic()-self.started)*1000
  row['client_reported_ms']=result['total_seconds']*1000
  row['request_prepare_upload_headers_wait_ms']=row['headers_ms']-sum(row[k] for k in ['dns_ms','tcp_setup_ms','tls_setup_ms'])
  row['headers_to_body_complete_ms']=row['body_complete_ms']-row['headers_ms']
  row['envelope_json_ms']=row['json_decode_ms'][0]
  row['action_json_ms']=row['json_decode_ms'][1]
  parts=['dns_ms','tcp_setup_ms','tls_setup_ms','request_prepare_upload_headers_wait_ms','headers_to_body_complete_ms','envelope_json_ms','action_json_ms','contract_validate_ms']
  row['other_client_ms']=row['validated_total_ms']-sum(row[k] for k in parts)
  packet=json.loads(self.body.decode('utf-8'))
  row.update(model_returned=packet.get('model'),usage=packet.get('usage'),body_bytes=len(self.body),
             action_count=len(result['actions']),finish_reason=packet['choices'][0].get('finish_reason'),
             content=packet['choices'][0]['message']['content'],
             reasoning_characters=len(packet['choices'][0]['message'].get('reasoning_content') or ''))
  self.row=None
  return row


def summarize(rows):
 ok=[r for r in rows if 'error' not in r]
 def stats(group):
  if not group:return None
  fields=['validated_total_ms','client_reported_ms','dns_ms','tcp_setup_ms','tls_setup_ms',
          'request_prepare_upload_headers_wait_ms','headers_to_body_complete_ms','envelope_json_ms','action_json_ms','contract_validate_ms','other_client_ms']
  times=sorted(r['validated_total_ms'] for r in group)
  return dict(n=len(group),mean={k:statistics.mean(r[k] for r in group) for k in fields},
              median_ms=statistics.median(times),p95_ms=times[max(0,__import__('math').ceil(len(times)*.95)-1)],
              min_ms=times[0],max_ms=times[-1],completion_tokens_mean=statistics.mean(r['usage']['completion_tokens'] for r in group),
              model_returned=sorted(set(r['model_returned'] for r in group)))
 return dict(n=len(rows),errors=len(rows)-len(ok),all=stats(ok),new_connection=stats([r for r in ok if r['new_connections']]),
             reused_connection=stats([r for r in ok if not r['new_connections']]),
             nonempty=stats([r for r in ok if r['action_count']]),empty=stats([r for r in ok if not r['action_count']]))


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--rounds',type=int,default=3);p.add_argument('--limit',type=int,default=8)
 p.add_argument('--modes',nargs='+',choices=['current','keepalive','production'],default=['current','keepalive'])
 args=p.parse_args()
 p.error("Historical non-SSE probe: use test/experiments/gesture/probe_deepseek_sse_latency.py for SSE latency; old phase attribution is incompatible with streaming.")
 config=Path(os.environ.get('GUIDEBOT_CONFIG_FILE',Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'guidebot/conversation.env'))
 load_dotenv(config,override=False,interpolate=False)
 if not os.environ.get('DEEPSEEK_API_KEY','').strip():raise SystemExit('DEEPSEEK_API_KEY not configured')
 endpoint=urlparse(os.environ.get('DEEPSEEK_BASE_URL','https://api.deepseek.com'))
 if endpoint.scheme!='https' or endpoint.username or endpoint.password or endpoint.query:raise SystemExit('Latency probe requires credential-free HTTPS endpoint URL')
 if requests.utils.get_environ_proxies(endpoint.geturl()):raise SystemExit('Proxy active: stage attribution requires explicit separate proxy instrumentation')
 args.output.mkdir(parents=True,exist_ok=True)
 (args.output/'metadata.json').write_text(json.dumps(dict(model_requested=os.environ.get('DEEPSEEK_MODEL','deepseek-chat'),endpoint_host=endpoint.hostname,
   rounds=args.rounds,texts=TEXTS[:args.limit],modes=args.modes,payload_stream=False,transport_stream=True,quality_scoring=False,
   note='Actual SemanticPlanner. current explicitly injects requests module to reproduce pre-change fresh connections; keepalive injects a persistent Session; production uses the client default. DNS/TCP/TLS instrumented; headers/body phases mix network and remote computation. No inference-only timing inferred.'),ensure_ascii=False,indent=2))
 summaries={}
 trace=Trace()
 with ExitStack() as stack:
  trace.instrument(stack)
  for mode in args.modes:
   d=args.output/mode;d.mkdir(parents=True,exist_ok=True)
   if (d/'requests.jsonl').exists():raise SystemExit('Use fresh output directory')
   rows=[]
   for rep in range(args.rounds):
    session=requests.Session() if mode=='keepalive' else None
    planner=SemanticPlanner(Catalog(),provider='deepseek',**({'session':session} if session else {'session':requests} if mode=='current' else {}))
    (d/'system.txt').write_text(planner.instruct)
    try:
     for index,text in enumerate(TEXTS[:args.limit]):
      trace.start()
      try:
       result=planner.analyze(text);row=trace.finish(result)
      except Exception as error:
       trace.row=None
       # Exception messages and raw provider error bodies can contain private data.
       row=dict(error=type(error).__name__)
      row.update(round=rep,text_index=index,text=text)
      rows.append(row)
      with (d/'requests.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
      print(mode,rep,index,round(row.get('validated_total_ms',0),1),'ms',row.get('error',''),flush=True)
      if 'error' in row:raise SystemExit('Stopped on client failure; sanitized error type stored')
    finally:
     if session:session.close()
     planner.close()
   summary=summarize(rows);summaries[mode]=summary
   (d/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
   print('SUMMARY',mode,json.dumps(summary['all']),flush=True)
 (args.output/'summaries.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
