#!/usr/bin/env python3
"""Plan gestures for a recorded reply; no hardware initialization or auto-play."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
from datetime import datetime

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from GuideBot.gesture.catalog import Catalog, make_input, messages, units_for, minimal_document
from GuideBot.gesture.planner import Planner
from GuideBot.runtime.workers.motion_executor import MotionExecutor

EXAMPLE_NOTE='\n本次是固定录音示例。word_timestamps给出可见文字的实际发音时间（秒），请据此安排动作窗口并参考audio_duration_s。'


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs(scenario_path, audio_override=None, timestamps_override=None):
    import soundfile as sf
    config=json.loads(scenario_path.read_text(encoding='utf-8'))
    base=scenario_path.parent
    audio=Path(audio_override).expanduser().resolve() if audio_override else (base/config['audio']).resolve()
    timestamps=Path(timestamps_override).expanduser().resolve() if timestamps_override else (base/config['timestamps']).resolve()
    signal,rate=sf.read(str(audio),dtype='float32',always_2d=True)
    duration=len(signal)/rate
    doc=json.loads(timestamps.read_text(encoding='utf-8'))
    text=doc['text'];expected=units_for(text);rows=doc['timestamps']
    if len(expected)!=len(rows):raise ValueError('文字单元数与时间戳数量不符')
    previous_start=0.;previous_end=0.;warnings=[]
    for i,(unit,row) in enumerate(zip(expected,rows)):
        if unit['text']!=row['text'] or unit['text_offset']!=row['text_offset']:
            raise ValueError(f'第{i}个文字单元与原文不符')
        start,end=row['start'],row['end']
        if (type(start) not in (int,float) or type(end) not in (int,float)
                or not math.isfinite(start) or not math.isfinite(end)
                or not 0<=start<end<=duration+.02 or start<previous_start or end<previous_end):
            raise ValueError(f'第{i}个时间区间无效')
        if start<previous_end-.02:warnings.append(f'第{i}单元与前一单元重叠')
        if start-previous_end>1.:warnings.append(f'第{i}单元前有超过1秒空隙')
        previous_start,previous_end=start,end
    if abs(doc['duration_seconds']-duration)>.05:raise ValueError('JSON时长与音频不符')
    if not math.isfinite(float(config.get('stream_step_s',4))) or float(config.get('stream_step_s',4))<=0:
        raise ValueError('stream_step_s必须大于0')
    if not math.isfinite(float(config.get('text_lookahead_s',6))) or float(config.get('text_lookahead_s',6))<0:
        raise ValueError('text_lookahead_s必须非负')
    return config,audio,doc,dict(duration_seconds=duration,sample_rate=rate,channels=signal.shape[1],
        text_units=len(rows),audio_sha256=sha(audio),timestamps_sha256=sha(timestamps),warnings=warnings,
        note='结构校验不能证明逐字边界和音频内容完全一致，仍需试听核对。')


def visible_text(doc,elapsed,lookahead,mode):
    if mode=='preplan':return doc['text'],len(doc['timestamps']),True
    rows=[r for r in doc['timestamps'] if r['start']<=elapsed+lookahead]
    if not rows:return '',0,False
    count=len(rows)
    text=doc['text'] if count==len(doc['timestamps']) else doc['text'][:rows[-1]['text_offset']+len(rows[-1]['text'])]
    return text,count,count==len(doc['timestamps'])


def candidate(catalog,row,doc,arrival,existing,mode):
    try:
        if any(type(row.get(k)) not in (int,float) or not math.isfinite(row[k]) for k in ('start_s','end_s')):
            raise ValueError('missing_or_invalid_window')
        if row['end_s']>doc['duration_seconds']:raise ValueError('beyond_audio')
        if any(row['start_s']<a['end_s'] and a['start_s']<row['end_s'] for a in existing):
            raise ValueError('overlapping_window')
        plan=catalog.validate(row,range(len(doc['timestamps'])),[])
        if plan.end_s is None:raise ValueError('fixed_window_required')
        dispatch=max(row['start_s'],arrival) if mode=='stream' else row['start_s']
        executor=MotionExecutor(catalog,mode='simulation',clock=lambda:1000.+dispatch)
        event=dict(action=row['action'],job_id='example',start_monotonic=1000.+row['start_s'],
                   arrival_monotonic=1000.+row['end_s'],end_monotonic=1000.+row['end_s'])
        sequence=executor.handle('gesture.command',event)['sequence']
        anchors=doc['timestamps'][row['start_unit']:row['arrival_unit']+1]
        minimum=catalog.execution_timing(row['action'])
        return dict(row,status='accepted',dispatch_s=dispatch,arrival_s=arrival,sequence=sequence,
                    label=catalog.actions[row['action']]['name'],description=(
                        next(a['description'] for a in minimal_document(catalog)['actions'] if a['id']==row['action'])),
                    minimum_duration_s=minimum.get('minimum_total_ms',0)/1000 if 'minimum_total_ms' in minimum else minimum['minimum_remaining_s'],
                    anchor_text=''.join(r['text'] for r in anchors),
                    anchor_start_s=anchors[0]['start'],anchor_end_s=anchors[-1]['end'])
    except (ValueError,KeyError,TypeError) as error:
        return dict(row,status='rejected',reason=str(error),arrival_s=arrival)


class RecordedHTTP:
    """Capture model content exactly while retaining the production SSE parser."""
    def __init__(self,directory):
        import requests
        self.session=requests.Session();self.directory=directory;self.fragments=[]
    def post(self,*args,**kwargs):
        kwargs['json']['messages'][0]['content']+=EXAMPLE_NOTE
        dump(self.directory/'messages.json',kwargs['json']['messages'])
        response=self.session.post(*args,**kwargs)
        original=response.iter_lines
        def lines(*args,**kwargs):
            try:
                for line in original(*args,**kwargs):
                    if line and line.startswith('data:') and line[5:].strip()!='[DONE]':
                        try:
                            packet=json.loads(line[5:])
                            for choice in packet.get('choices',[]):
                                text=choice.get('delta',{}).get('content')
                                if text:self.fragments.append(text)
                        except (ValueError,TypeError):pass
                    yield line
            finally:
                (self.directory/'raw-response.txt').write_text(''.join(self.fragments),encoding='utf-8')
        response.iter_lines=lines
        return response
    def close(self):self.session.close()


def build_payload(doc,text,count,complete,elapsed,history):
    payload=make_input('g1-example',text,existing=history,complete=complete)
    payload.update(timing_contract='fixed_deadline',playback_elapsed_s=elapsed,
                   playback_started=elapsed>0,suggested_planning_lead_s=2.,
                   audio_duration_s=doc['duration_seconds'],
                   word_timestamps=[dict(unit_id=i,start=r['start'],end=r['end']) for i,r in enumerate(doc['timestamps'][:count])],
                   timestamp_reference='Seconds from audio start; these are offline reference timestamps.')
    return payload


def plan_run(config,audio,doc,validation,out,mode,catalog,planner_factory=None):
    if planner_factory is None:
        raise ValueError('Fixed-window LLM planning retired; use preplan_keyframes.py for whole-text planning')
    dump(out/'motion-snapshot.json', {name:dict(sha256=catalog.assets[name]['metadata']['sha256'],
        version=catalog.assets[name]['metadata']['version'],timing=catalog.execution_timing(name)) for name in catalog.actions})
    actions=[];attempts=[];history=[];elapsed=0.;index=0
    maximum=config.get('max_actions_per_request',3)
    while elapsed<doc['duration_seconds']:
        text,count,complete=visible_text(doc,elapsed,config.get('text_lookahead_s',6.),mode)
        if not text:
            elapsed+=config.get('stream_step_s',4.);continue
        directory=out/f'request-{index:02}';directory.mkdir(parents=True,exist_ok=True)
        for item in history:
            if item['status']!='skipped':
                item['status']='completed' if item['end_s']<=elapsed else ('running' if item['start_s']<=elapsed else 'scheduled')
        payload=build_payload(doc,text,count,complete,elapsed,history)
        # Historical fixed-planner replay has no LLM prompt.
        prompt=[]
        dump(directory/'messages.json',prompt)
        wire=RecordedHTTP(directory) if planner_factory is None else None
        planner=planner_factory(directory) if planner_factory else Planner(catalog,session=wire,timeout=45)
        start=time.monotonic();received=[]
        def on_action(plan):received.append((plan.as_dict(),time.monotonic()-start))
        try:
            stats=planner.plan(payload,on_action)
            if stats.get('cancelled'):raise RuntimeError('Planner request cancelled')
        except Exception as error:
            dump(directory/'error.json',dict(error=str(error)))
            raise
        finally:
            if wire:wire.close()
        duration=stats.get('total_seconds',time.monotonic()-start)
        reviewed=[]
        for row,delay in received:
            arrival=elapsed+delay if mode=='stream' else 0.
            if len(reviewed)>=maximum:
                result=dict(row,status='rejected',reason='request_action_limit',arrival_s=arrival)
            else:
                result=candidate(catalog,row,doc,arrival,actions,mode)
            reviewed.append(result)
            if result['status']=='accepted':actions.append(result)
            history.append(dict(row,status='scheduled' if result['status']=='accepted' else 'skipped',reason=result.get('reason','')))
        # Keep malformed/invalid raw output in raw-response.txt, as production parser may reject rows.
        attempt=dict(index=index,playback_elapsed_s=elapsed,visible_units=count,response_complete=complete,
                     stats=stats,actions=reviewed)
        dump(directory/'result.json',attempt);attempts.append(attempt)
        print(f'{mode} request {index}: {count} units, {duration:.2f}s, accepted {sum(r["status"]=="accepted" for r in reviewed)}',flush=True)
        index+=1
        if mode=='preplan':break
        elapsed=max(elapsed+config.get('stream_step_s',4.),elapsed+duration)
        # No sleep/audio: virtual playback advances by measured request time.
    summary=dict(mode=mode,validation=validation,text=doc['text'],timestamps=doc['timestamps'],
                 actions=sorted(actions,key=lambda r:r['start_s']),attempts=attempts,
                 method='Full text planned before playback' if mode=='preplan' else
                 f'Serialized requests on a virtual playback clock, {config.get("text_lookahead_s",6)}s transcript lookahead; known offline timestamps. Not live ASR/TTS.',
                 max_actions_per_request=maximum,prompt_variant=os.getenv('GUIDEBOT_GESTURE_PROMPT','minimal'),
                 notes=['Only structural/execution checks are automatic; naturalness needs listening and observation.',
                        'No robot connection or audio playback was started.'])
    native_checks(out,summary)
    report(out,audio,summary)
    dump(out/'summary.json',summary)
    return summary



def native_checks(out,summary):
    """Parse sequences from their own entry poses; never initialize DDS."""
    import subprocess
    from drivers.unitree_motion.paths import ASSETS,BUILD,LIMITS
    binary=BUILD/'motion_library_server'
    if not binary.is_file():
        summary['native_offline_checks']=dict(status='not_run',reason='Native binary not built')
        return
    results=[]
    for action in summary['actions']:
        result=subprocess.run([str(binary),'--check-sequence','-',
            '--catalog',str(ASSETS/'config/motion_catalog.json'),'--dir',str(ASSETS/'motions'),
            '--poses',str(ASSETS/'poses'),'--metadata',str(ASSETS/'metadata'),'--limits',str(LIMITS)],
            input=json.dumps(action['sequence']['序列']),text=True,capture_output=True)
        results.append(dict(action=action['action'],exit_code=result.returncode,
                            stdout=result.stdout,stderr=result.stderr))
    dump(out/'native-offline-checks.json',results)
    summary['native_offline_checks']=dict(status='passed' if all(r['exit_code']==0 for r in results) else 'failed',
        checked=len(results),note='Resolved from each action entry pose, not measured inter-action transitions or hardware execution.')


def report(out,audio,summary):
    audio_name='audio.wav' if audio.suffix.lower()=='.wav' else 'audio.mp3'
    summary['audio_file']=audio_name
    destination=out/audio_name
    if audio.resolve()!=destination.resolve():shutil.copy2(audio,destination)
    # Generate an explicitly simulated event list; opening the report never plays automatically.
    events=[]
    for a in summary['actions']:
        events.extend([dict(time_s=a['dispatch_s'],event='simulated_action_start',action=a['action']),
                       dict(time_s=a['end_s'],event='simulated_window_end',action=a['action'])])
    dump(out/'simulated-events.json',sorted(events,key=lambda r:r['time_s']))
    data=json.dumps(summary,ensure_ascii=False).replace('<','\\u003c')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>G1 语音动作规划示例</title><style>body{font:16px/1.7 system-ui;background:#f3f5ef;color:#203b34;margin:32px auto;max-width:1000px;padding:0 20px}section{background:white;border:1px solid #d8e1da;border-radius:12px;padding:20px;margin:20px 0}audio{width:100%}.word{padding:2px}.active{background:#b4e7cb}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;text-align:left;padding:10px}button{cursor:pointer}small{color:#62736c}</style><h1>G1 自我介绍 · 动作规划</h1><p id="method"></p><p id="native"></p><small>播放只展示模拟动作事件，不控制机器人。自然程度需结合试听和实机观察判断。</small><section><audio id="audio" controls preload="metadata" src="audio.mp3"></audio><p id="clock"></p><p id="text"></p><strong id="current">尚未播放</strong></section><section><h2>动作时间轴</h2><table><thead><tr><th>动作</th><th>窗口（秒）</th><th>对应文字</th><th>姿态／轨迹</th></tr></thead><tbody id="rows"></tbody></table></section><section><h2>请求与校验</h2><pre id="stats"></pre></section><script>const data=__DATA__;const audio=document.getElementById('audio');document.getElementById('method').textContent=data.mode+' · '+data.method;document.getElementById('native').textContent='原生离线检查：'+(data.native_offline_checks?data.native_offline_checks.status:'见 native-offline-checks.json');const words=[];data.timestamps.forEach((r)=>{const s=document.createElement('span');s.textContent=r.text+' ';s.className='word';document.getElementById('text').append(s);words.push(s);});data.actions.forEach(a=>{const tr=document.createElement('tr');[a.action,a.start_s.toFixed(2)+' – '+a.end_s.toFixed(2),a.anchor_text,a.description].forEach(t=>{const td=document.createElement('td');td.textContent=t;tr.append(td);});tr.onclick=()=>{audio.currentTime=Math.max(0,a.start_s-1);};document.getElementById('rows').append(tr);});document.getElementById('stats').textContent=JSON.stringify(data.attempts.map(r=>({request:r.index,elapsed:r.playback_elapsed_s,visible:r.visible_units,stats:r.stats,actions:r.actions.map(a=>({action:a.action,status:a.status,reason:a.reason}))})),null,2);audio.ontimeupdate=()=>{const t=audio.currentTime;document.getElementById('clock').textContent=t.toFixed(2)+' / '+data.validation.duration_seconds.toFixed(2)+' 秒';words.forEach((s,i)=>s.classList.toggle('active',data.timestamps[i].start<=t&&t<data.timestamps[i].end));const active=data.actions.filter(a=>a.dispatch_s<=t&&t<a.end_s);document.getElementById('current').textContent=active.length?'模拟执行：'+active.map(a=>a.action).join(', '):'当前无动作窗口';};</script></html>'''
    (out/'report.html').write_text(page.replace('src="audio.mp3"','src="'+audio_name+'"').replace('__DATA__',data),encoding='utf-8')
    lines=['# 固定语音动作规划结果','',f'模式：{summary["mode"]}',f'方法：{summary["method"]}','',
           f'音频：{summary["validation"]["duration_seconds"]:.3f} 秒；文字单元：{summary["validation"]["text_units"]}；可执行规划：{len(summary["actions"])} 个。','',
           '| 动作 | 起止（秒） | 对应文字 |','| --- | --- | --- |']
    for a in summary['actions']:lines.append(f'| {a["action"]} | {a["start_s"]:.2f}–{a["end_s"]:.2f} | {a["anchor_text"]} |')
    lines+=['','以上仅证明本地校验及指令生成通过，不能自动判定自然程度。没有启动真机或自动播放音频。']
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('check','plan','serve','replay'))
    parser.add_argument('--scenario',type=Path,default=Path(__file__).with_name('scenario.json'))
    parser.add_argument('--audio',type=Path);parser.add_argument('--timestamps',type=Path)
    parser.add_argument('--mode',choices=('preplan','stream'),default='preplan')
    parser.add_argument('--variant',choices=('minimal',))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--port',type=int,default=8767)
    args=parser.parse_args()
    if args.command in ('serve','replay'):
        if not args.output:parser.error('serve/replay需要--output指向已有结果目录')
        out=args.output.expanduser().resolve()
        if args.command=='serve':
            from functools import partial
            from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
            page='index.html' if (out/'index.html').is_file() else 'report.html'
            print(f'报告：http://127.0.0.1:{args.port}/{page}（点击播放才播放音频）',flush=True)
            ThreadingHTTPServer(('127.0.0.1',args.port),partial(SimpleHTTPRequestHandler,directory=str(out))).serve_forever()
        else:
            summary=json.loads((out/'summary.json').read_text())
            print('仅播放本机音频和打印模拟事件，不连接机器人。')
            input('按 Enter 开始，Ctrl+C 停止：')
            import soundfile as sf
            import subprocess
            if shutil.which('aplay') is None:
                raise RuntimeError('未安装aplay；可使用serve网页播放，无需安装Python音频依赖')
            signal,rate=sf.read(str(out/summary.get('audio_file','audio.mp3')),dtype='float32')
            wav=out/'replay-audio.wav'
            sf.write(str(wav),signal,rate,subtype='PCM_16')
            events=json.loads((out/'simulated-events.json').read_text());index=0
            process=subprocess.Popen(['aplay','-q',str(wav)])
            origin=time.monotonic()
            try:
                while process.poll() is None:
                    elapsed=time.monotonic()-origin
                    while index<len(events) and events[index]['time_s']<=elapsed:
                        print(events[index],flush=True);index+=1
                    time.sleep(.02)
                if process.returncode:raise RuntimeError('本机音频播放失败，请检查ALSA输出设备')
            finally:
                if process.poll() is None:
                    process.terminate();process.wait(timeout=5)
        return
    config,audio,doc,validation=inputs(args.scenario.resolve(),args.audio,args.timestamps)
    print(json.dumps(validation,ensure_ascii=False,indent=2))
    if args.command=='check':return
    from dotenv import load_dotenv
    config_file=Path(os.getenv('GUIDEBOT_CONFIG_FILE',Path.home()/'.config/guidebot/conversation.env'))
    load_dotenv(config_file,override=False,interpolate=False)
    if not os.getenv('DEEPSEEK_API_KEY'):raise RuntimeError('DEEPSEEK_API_KEY未配置，不输出密钥')
    os.environ['GUIDEBOT_GESTURE_PROMPT']=args.variant or config.get('prompt_variant','minimal')
    out=(args.output or REPO/'artifacts/gesture-from-audio'/datetime.now().strftime('%Y%m%d-%H%M%S')/args.mode).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('结果目录已有文件，请选新目录以保留既有实验')
    out.mkdir(parents=True,exist_ok=True)
    dump(out/'validation.json',validation)
    plan_run(config,audio,doc,validation,out,args.mode,Catalog())
    print('Results:',out)


if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('\n已停止')
