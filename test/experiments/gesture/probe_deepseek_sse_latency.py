#!/usr/bin/env python3
"""SSE timing diagnostic only; never changes or dispatches production behavior."""
import argparse,json,os,statistics,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
import requests
from dotenv import load_dotenv
from GuideBot.gesture.catalog import Catalog,strict_json
from GuideBot.gesture.semantic_planner import SemanticPlanner
from test.experiments.gesture.benchmark_deepseek_latency import TEXTS


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--rounds',type=int,default=2);a=p.parse_args()
 config=Path(os.environ.get('GUIDEBOT_CONFIG_FILE',Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'guidebot/conversation.env'))
 load_dotenv(config,override=False,interpolate=False)
 a.output.mkdir(parents=True,exist_ok=True)
 path=a.output/'requests.jsonl'
 if path.exists():raise SystemExit('Use fresh output directory')
 rows=[]
 with requests.Session() as session:
  planner=SemanticPlanner(Catalog(),provider='deepseek',session=session)
  if not planner.api_key:raise SystemExit('DEEPSEEK_API_KEY not configured')
  (a.output/'system.txt').write_text(planner.instruct)
  for rep in range(a.rounds):
   for index,text in enumerate(TEXTS):
    payload=dict(model=planner.model,messages=[dict(role='system',content=planner.instruct),dict(role='user',content=text)],temperature=0,max_tokens=384,stream=True,response_format={'type':'json_object'})
    start=time.monotonic();content=[];first=last=None;finish=None;model=None;usage=None;deltas=0;reasoning=0;done=False
    try:
     with session.post(planner.base_url+'/chat/completions',headers={'Authorization':'Bearer '+planner.api_key},json=payload,stream=True,timeout=(5,20)) as response:
      headers=(time.monotonic()-start)*1000
      if response.status_code!=200:raise RuntimeError('HTTP status')
      response.encoding='utf-8';encoding=response.headers.get('Transfer-Encoding')
      for line in response.iter_lines(chunk_size=1024,decode_unicode=True):
       if time.monotonic()-start>40:raise RuntimeError('Total deadline')
       if not line or not line.startswith('data:'):continue
       data=line[5:].strip()
       if data=='[DONE]':done=True;break
       packet=json.loads(data)
       if 'error' in packet:raise RuntimeError('Provider stream error')
       model=packet.get('model',model);usage=packet.get('usage') or usage
       for choice in packet.get('choices',[]):
        if choice.get('finish_reason') is not None:finish=choice['finish_reason']
        delta=choice.get('delta',{});fragment=delta.get('content') or ''
        reasoning+=len(delta.get('reasoning_content') or '')
        if fragment:
         now=(time.monotonic()-start)*1000
         if first is None:first=now
         last=now;content.append(fragment);deltas+=1
     received=(time.monotonic()-start)*1000
     value=strict_json(''.join(content))
     row=dict(round=rep,text_index=index,text=text,headers_ms=headers,first_content_ms=first,last_content_ms=last,
              first_to_last_content_ms=last-first if first is not None else None,total_receive_ms=received,
              content=''.join(content),action_count=len(value['actions']),content_delta_events=deltas,model_returned=model,
              usage=usage,reasoning_characters=reasoning,finish_reason=finish,done=done,transfer_encoding=encoding)
    except Exception as error:
     row=dict(round=rep,text_index=index,error=type(error).__name__)
    rows.append(row)
    with path.open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(rep,index,round(row.get('first_content_ms') or 0,1),round(row.get('first_to_last_content_ms') or 0,1),round(row.get('total_receive_ms') or 0,1),row.get('error',''),flush=True)
    if 'error' in row:raise SystemExit('SSE timing stopped: sanitized failure stored')
 def stats(group):
  return dict(n=len(group),mean={k:statistics.mean(r[k] for r in group) for k in ['headers_ms','first_content_ms','first_to_last_content_ms','total_receive_ms']}) if group else None
 summary=dict(all=stats(rows),warm=stats(rows[1:]),nonempty=stats([r for r in rows if r['action_count']]),empty=stats([r for r in rows if not r['action_count']]),model_returned=sorted(set(r['model_returned'] for r in rows)),note='First content is first nonempty delta, not isolated server prefill. Generation window includes delivery and buffering; no downstream actions. Same production prompt, only API stream flag changed.')
 (a.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary),flush=True)
if __name__=='__main__':main()
