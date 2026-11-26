#!/usr/bin/env python3
"""Select action intents, compile a continuous executable speech timeline."""
import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from run import inputs,dump,report
from GuideBot.gesture.catalog import Catalog,minimal_document
from drivers.unitree_motion.paths import ASSETS,BUILD,LIMITS


def phase_times(asset,from_pose,*,transition_s=1.0):
    # Timing comes only from recorded/physically approved timing, never angles,
    # velocities, accelerations, or the distance between consecutive poses.
    meta=asset['metadata'];profile=meta.get('timing_profile')
    entry=1.0 if transition_s is None else transition_s
    if not math.isfinite(entry) or not 0 < entry <= 30:
        raise ValueError("切换时长必须在0到30秒之间")
    minimum=profile['minimum_total_ms']/1000 if profile else meta['nominal_duration_ms']/1000+.5
    from GuideBot.gesture.timing import phases
    core=phases(asset)[1]
    hold=max(.3,minimum-entry-core)
    return tuple(math.ceil(x*1000)/1000 for x in (entry,core,hold))



def compile_timeline(catalog,doc,intents,*,action_limit=3,allow_repeats=False,transition_s=1.0):
    if action_limit is not None and len(intents)>action_limit:raise ValueError('整段最多3个动作意图')
    initial=catalog.assets['B_Neutral_Rest']['points'][0][1]
    previous=initial;previous_end=.1;accepted=[];rejected=[]
    rows=doc['timestamps'];used=set()
    for item in sorted(intents,key=lambda r:r.get('anchor_unit',-1)):
        name=item.get('action');anchor=item.get('anchor_unit')
        if name not in catalog.actions or type(anchor) is not int or not 0<=anchor<len(rows) or (not allow_repeats and name in used) or (name,anchor) in used:
            rejected.append(dict(intent=item,reason='动作、锚点无效或重复'));continue
        entry,core,hold=phase_times(catalog.assets[name],previous,transition_s=transition_s)
        arrival=rows[anchor]['start'];start=round(arrival-entry,3);end=round(arrival+core+hold,3)
        if start<previous_end or end>doc['duration_seconds']-.2:
            rejected.append(dict(intent=item,reason='连续切换或动作核心无法在目标语音窗口完成',
                                 transition_s=entry,core_s=core,earliest_arrival_s=previous_end+entry));continue
        accepted.append(dict(action=name,anchor_unit=anchor,start_s=start,arrival_s=arrival,end_s=end,
            transition_s=entry,core_s=core,hold_s=hold,
            description=next(a['description'] for a in minimal_document(catalog)['actions'] if a['id']==name)))
        previous=catalog.assets[name]['points'][-1][1];previous_end=end;used.add(name);used.add((name,anchor))
    if not accepted:return None,accepted,rejected
    first=accepted[0]
    steps=[dict(type=catalog.assets['B_Neutral_Rest']['entry']['type'],name='B_Neutral_Rest',transition_ms=1,
                hold_ms=max(0,round(first['start_s']*1000)-1))]
    for i,action in enumerate(accepted):
        target_end=accepted[i+1]['start_s'] if i+1<len(accepted) else action['end_s']
        # Silence between gestures becomes a static hold, not another RPC/action.
        step=dict(type=catalog.assets[action['action']]['entry']['type'],name=action['action'],
                  transition_ms=round(action['transition_s']*1000),
                  hold_ms=round((action['hold_s']+target_end-action['end_s'])*1000))
        if action['core_s']:step['duration_ms']=round(action['core_s']*1000)
        steps.append(step)
    return dict(sequence_name='g1_complete_timeline',preserve_transition=True,steps=steps),accepted,rejected


def native_validate(sequence,out):
    command=[str(BUILD/'motion_library_server'),'--check-sequence','-',
             '--catalog',str(ASSETS/'config/motion_catalog.json'),'--dir',str(ASSETS/'motions'),
             '--poses',str(ASSETS/'poses'),'--metadata',str(ASSETS/'metadata'),'--limits',str(LIMITS)]
    result=subprocess.run(command,input=json.dumps(sequence),text=True,capture_output=True)
    dump(out/'native-continuous-check.json',dict(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr))
    if result.returncode:raise RuntimeError('完整连续轨迹预检失败: '+result.stderr.strip())
    return result.stdout


def intent_messages(catalog,doc,feedback,*,unlimited=False,transition_s=1.0):
    library=minimal_document(catalog)
    payload=dict(text=doc['text'],duration_s=doc['duration_seconds'],
                 word_timestamps=[dict(unit_id=i,text=r['text'],start=r['start'],end=r['end']) for i,r in enumerate(doc['timestamps'])],
                 previous_conflicts=feedback,
                 execution_timing=[dict(id=name,transition_s=transition_s,core_s=phase_times(
                     catalog.assets[name],catalog.assets['B_Neutral_Rest']['points'][0][1],transition_s=transition_s)[1],
                     minimum_hold_s=phase_times(catalog.assets[name],catalog.assets['B_Neutral_Rest']['points'][0][1],
                                               transition_s=transition_s)[2]) for name in catalog.actions])
    if unlimited:
        count_rule='整段不设置动作数量上限，可在不同表达位置重复使用同一动作，由你根据播报内容决定数量；不需要为了增加数量而堆叠动作。'
    else:
        count_rule='为整段播报选择最多3个稀疏、自然的动作，不重复同一动作。'
    system=count_rule+f'\n每个动作的入口切换固定为{transition_s:g}秒，不按关节距离额外加长。核心与必要保持时长见输入execution_timing。选择锚点时必须容纳完整切换、核心和保持，不能只计算到位时间。'+'''
可以少选或不选。只选择动作和希望到位的文字编号，不猜测精确动作起止秒数。程序会根据固定切换、核心和保持校验完整时间表，冲突时请换更短动作、较晚锚点或删去低价值动作。
每个动作需在目标词之前留足切换时间，不能重叠。只输出JSON {"intents":[{"action":"动作id","anchor_unit":文字编号}]}。
动作库：'''+json.dumps(library,ensure_ascii=False)
    return [dict(role='system',content=system),dict(role='user',content=json.dumps(payload,ensure_ascii=False))]


def select_intents(catalog,doc,feedback,out,*,unlimited=False,transition_s=1.0):
    import requests
    messages=intent_messages(catalog,doc,feedback,unlimited=unlimited,transition_s=transition_s)
    dump(out/'messages.json',messages)
    response=requests.post(os.getenv('DEEPSEEK_BASE_URL','https://api.deepseek.com').rstrip('/')+'/chat/completions',
        headers={'Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY']},
        json=dict(model=os.getenv('DEEPSEEK_MODEL','deepseek-chat'),messages=messages,
                  response_format={'type':'json_object'},temperature=0,max_tokens=4096 if unlimited else 600),timeout=(5,45))
    if response.status_code!=200:raise RuntimeError(f'DeepSeek HTTP {response.status_code}')
    packet=response.json()
    choice=packet['choices'][0]
    content=choice['message']['content']
    (out/'raw-response.txt').write_text(content,encoding='utf-8')
    dump(out/'response-metadata.json',dict(model=packet.get('model'),usage=packet.get('usage'),finish_reason=choice.get('finish_reason')))
    if choice.get('finish_reason')!='stop':raise ValueError('模型输出未正常完成，不能作为完整方案')
    result=json.loads(content)
    if set(result)!= {'intents'} or not isinstance(result['intents'],list):raise ValueError('模型意图格式无效')
    return result['intents']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='新的结果目录；不覆盖当前采用方案')
    parser.add_argument('--recompile-from',type=Path,help='从既有完整方案复用动作/锚点，仅重算时间表，不调用LLM')
    parser.add_argument('--transition-seconds',type=float,default=1.,help='动作切换秒数，默认固定1秒；不修改动作核心时长')
    parser.add_argument('--unlimited',action='store_true',help='不限制动作总数量或同一动作在不同位置的复用')
    args=parser.parse_args();out=args.output.expanduser().resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('请选新的结果目录，避免覆盖既有方案')
    out.mkdir(parents=True,exist_ok=True)
    if not math.isfinite(args.transition_seconds) or not 0<args.transition_seconds<=30:parser.error('切换时长必须在0到30秒之间')
    config,audio,doc,validation=inputs(Path(__file__).with_name('scenario.json'))
    from dotenv import load_dotenv
    load_dotenv(Path(os.getenv('GUIDEBOT_CONFIG_FILE',Path.home()/'.config/guidebot/conversation.env')),interpolate=False)
    if not args.recompile_from and not os.getenv('DEEPSEEK_API_KEY'):raise ValueError('未配置DEEPSEEK_API_KEY')
    catalog=Catalog();feedback=[];best=None;cached=None
    if args.recompile_from:
        source=args.recompile_from.expanduser().resolve()
        source=source/'summary.json' if source.is_dir() else source
        old=json.loads(source.read_text())
        if old.get('mode')!='complete' or old['validation']['audio_sha256']!=validation['audio_sha256']:
            raise ValueError('复用方案必须是同一音频的完整规划')
        snapshot=json.loads((source.parent/'motion-snapshot.json').read_text())
        for name,receipt in snapshot.items():
            if name not in catalog.assets or any(catalog.assets[name]['metadata'][k]!=receipt[k] for k in ('sha256','version')):
                raise ValueError('复用方案的动作资产已变化，请重新规划')
        cached=[dict(action=a['action'],anchor_unit=a['anchor_unit']) for a in old['compiled_actions']]
        dump(out/'recompile-source.json',dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    for attempt in range(1 if cached is not None else 2):
        directory=out/f'intents-{attempt:02}';directory.mkdir()
        intents=cached if cached is not None else select_intents(catalog,doc,feedback,directory,unlimited=args.unlimited,transition_s=args.transition_seconds)
        sequence,actions,feedback=compile_timeline(catalog,doc,intents,
            action_limit=None if args.unlimited else 3,allow_repeats=args.unlimited,transition_s=args.transition_seconds)
        dump(directory/'compiled.json',dict(intents=intents,actions=actions,conflicts=feedback))
        if sequence:best=(sequence,actions)
        if sequence and not feedback:break
    if not best:raise ValueError('未得到可执行方案，保留失败原因，不生成真机演练计划')
    sequence,actions=best
    check=native_validate(sequence,out)
    # Native checks include the B_Neutral_Rest start and all transitions/holds in one sequence.
    expected=actions[-1]['end_s']
    import re
    parsed=re.search(r'([0-9.]+) s from first entry pose',check)
    if not parsed or abs(float(parsed.group(1))-expected)>.003:raise ValueError('Python和原生完整轨迹时长不一致')
    dump(out/'sequence.json',sequence)
    dump(out/'motion-snapshot.json',{name:dict(sha256=catalog.assets[name]['metadata']['sha256'],version=catalog.assets[name]['metadata']['version']) for name in {'B_Neutral_Rest',*(a['action'] for a in actions)}})
    summary=dict(mode='complete',validation=validation,text=doc['text'],timestamps=doc['timestamps'],actions=[],
                 sequence=sequence,compiled_actions=actions,trajectory_seconds=expected,
                 action_limit=None if args.unlimited else 3,allow_repeated_actions=args.unlimited,
                 transition_policy="fixed",fixed_transition_s=args.transition_seconds,
                 method=('LLM不限数量且允许动作复用；' if args.unlimited else 'LLM最多3个动作；')+'程序按完整关节切换和核心轨迹计算连续时间表，整段原生预检。',attempts=[],
                 native_offline_checks=dict(status='passed',note=check),
                 notes=['初始姿态为B_Neutral_Rest，真机播放前先到B_Neutral_Rest并复核，不承诺严格DAC同步。'])
    for a in actions:
        summary['actions'].append(dict(a,dispatch_s=a['start_s'],start_unit=a['anchor_unit'],arrival_unit=a['anchor_unit'],
            anchor_text=doc['timestamps'][a['anchor_unit']]['text'],label=a['action']))
    dump(out/'summary.json',summary);report(out,audio,summary)
    print(check.strip());print('Results:',out)
    for a in actions:print(a['action'],a['start_s'],a['arrival_s'],a['end_s'])


if __name__=='__main__':main()
