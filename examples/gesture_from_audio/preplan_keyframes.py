#!/usr/bin/env python3
"""Preplan a complete reply with the exact production stream system prompt.

Real DeepSeek SSE, multiple batches, known offline timestamps; never starts audio
or robot SDKs. This is complete preplanning, not a live streaming latency test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO));sys.path.insert(0,str(Path(__file__).resolve().parent))
from GuideBot.gesture.catalog import Catalog,make_input,messages,minimal_document,strict_json
from GuideBot.gesture.planner import Planner
from GuideBot.gesture.timing import phases,compile_intent
from complete_plan import native_validate
from run import dump,report,inputs


class RecordedSession:
    def __init__(self,directory):
        import requests
        self.session=requests.Session();self.directory=directory;self.fragments=[]
    def post(self,*args,**kwargs):
        # Record only prompt content, never headers, credentials or env values.
        dump(self.directory/'messages.json',kwargs['json']['messages'])
        response=self.session.post(*args,**kwargs)
        original=response.iter_lines
        def lines(*args,**kwargs):
            try:
                for line in original(*args,**kwargs):
                    if line and line.startswith('data:') and line[5:].strip()!='[DONE]':
                        packet=json.loads(line[5:])
                        for choice in packet.get('choices',[]):
                            self.fragments.append(choice.get('delta',{}).get('content') or '')
                    yield line
            finally:
                (self.directory/'raw-response.txt').write_text(''.join(self.fragments),encoding='utf-8')
        response.iter_lines=lines
        return response


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--scenario',type=Path,help='导览素材scenario.json；省略时使用原自我介绍')
    parser.add_argument('--whole-text',action='store_true',help='使用prompt_preplan.md一次规划全文，冲突时最多全局修订两次')
    parser.add_argument('--auto-prefix',action='store_true',help='按实际开场动作需要补静音')
    parser.add_argument('--finalize-conflicts',action='store_true',help='修订后排除冲突项并编译通过项')
    parser.add_argument('--resume',action='store_true',help='复用输入完全相同且已正常完成的已保存批次')
    args=parser.parse_args()
    from dotenv import load_dotenv
    configs=[args.config] if args.config else [Path(os.getenv('GUIDEBOT_CONFIG_FILE',Path.home()/'.config/guidebot/conversation.env')),Path.home()/'test/.env']
    for config in configs:
        load_dotenv(config,override=False,interpolate=False)
    if not os.getenv('DEEPSEEK_API_KEY'):raise RuntimeError('DEEPSEEK_API_KEY is not configured')
    out=args.output.expanduser().resolve()
    if out.exists() and any(out.iterdir()) and not args.resume:raise ValueError('Output must be a new or empty directory')
    out.mkdir(parents=True,exist_ok=True)
    if args.scenario:
        _,audio,doc,validation=inputs(args.scenario.expanduser().resolve())
        source=audio.parent
        manifest=source/'manifest.json'
        prefix=json.loads(manifest.read_text()).get('silence_prefix_s',0.) if manifest.is_file() else 0.
        previous=dict(text=doc['text'],timestamps=doc['timestamps'],validation=validation,silence_prefix_s=prefix)
    else:
        source=REPO/'artifacts/gesture-from-audio/g1-self-introduction/manual-neutral-closing'
        previous=json.loads((source/'summary.json').read_text())
        audio=source/'audio.wav'
        if hashlib.sha256(audio.read_bytes()).hexdigest()!=previous['validation']['audio_sha256']:
            raise ValueError('Reference audio hash mismatch')
    rows=previous['timestamps'];duration=previous['validation']['duration_seconds']
    catalog=Catalog();descriptions={r['id']:r['description'] for r in minimal_document(catalog)['actions']}
    anchors={i:dict(index=i,**row) for i,row in enumerate(rows)}
    accepted=[];attempts=[];history=[];frontier=.001;empty=0
    original_rows=json.loads(json.dumps(rows));original_duration=duration;added_prefix=0.
    feedback=[]
    for batch in range(3 if args.whole_text else 10):
        if args.whole_text:
            accepted=[];history=[];frontier=.001
            rows=json.loads(json.dumps(original_rows));duration=original_duration
            anchors={i:dict(index=i,**row) for i,row in enumerate(rows)}
        eligible=[i for i,row in enumerate(rows) if row['start']>frontier]
        if not eligible or frontier>=duration-1.:break
        payload=make_input('g1-self-introduction-preplan',previous['text'],existing=history,eligible=eligible,complete=True)
        payload.update(timing_contract='semantic_keyframes',playback_started=False,playback_elapsed_s=0.,
            suggested_planning_lead_s=2.,audio_duration_s=duration,
            alignment_anchors=list(anchors.values()),
            execution_timing=[dict(id=n,transition_s=1.,minimum_core_s=phases(catalog.assets[n])[1],
                minimum_hold_s=phases(catalog.assets[n])[2],keyframe_count=catalog.assets[n]['frames']) for n in catalog.actions],
            planning_mode='complete_preplan_before_playback',earliest_available_start_s=frontier)
        if args.whole_text:
            payload.update(planning_mode='whole_text_preplan',revision_feedback=feedback,
                revision_instruction='此前候选若有错误，必须修改而非重复提交。多帧时间不匹配时优先只指定一个最有意义的关键帧，程序仍播放完整轨迹；相邻动作冲突时调整锚点或删减，不能保持冲突。返回修改后的完整全文方案，不是增量。',
                alignment_advice='优先每动作仅对齐一个关键帧；多帧仅在时间比例确实可行时使用。')
        directory=out/('batch-%02d'%batch);directory.mkdir(exist_ok=args.resume)
        session=RecordedSession(directory);candidates=[]
        if not (directory/'messages.json').exists():dump(directory/'messages.json',messages(catalog,payload))
        try:
            cached=directory/'compiled.json'
            if args.resume and cached.is_file():
                if json.loads((directory/'messages.json').read_text())!=messages(catalog,payload):
                    raise ValueError('Saved batch input differs; use a new output directory')
                stats=json.loads(cached.read_text())['stats']
                for row in strict_json((directory/'raw-response.txt').read_text())['actions']:
                    candidates.append(catalog.validate(row,payload['eligible_anchor_ids'],[]))
            else:
                stats=Planner(catalog,session=session,timeout=90).plan(payload,candidates.append)
        finally:session.session.close()
        if args.auto_prefix:
            required=0.
            probe={i:dict(row,start=row['start']+10.) for i,row in anchors.items()}
            for plan in candidates:
                try:
                    timing=compile_intent(catalog.assets[plan.action],plan.parameters['keyframes'],probe,plan.parameters.get('hold_s',0.))
                    required=max(required,10.001-timing['start_s'])
                except ValueError:
                    pass
            import math
            added_prefix=math.ceil(required*16000)/16000
            for row in rows:
                row['start']+=added_prefix;row['end']+=added_prefix
            duration=original_duration+added_prefix
            anchors={i:dict(index=i,**row) for i,row in enumerate(rows)}
        compiled=[];rejected=[]
        for plan in candidates:
            intent=plan.as_dict()
            try:
                timing=compile_intent(catalog.assets[plan.action],plan.parameters['keyframes'],anchors,plan.parameters.get('hold_s',0.))
                timing={k:round(v,3) for k,v in timing.items()}
                if timing['start_s']<frontier:raise ValueError('overlaps_preceding_action_or_starts_before_available_time')
                if timing['end_s']>duration-.1:raise ValueError('extends_beyond_audio_deadline')
                if any(a['action']==plan.action and a['keyframes']==plan.parameters['keyframes'] for a in accepted):
                    raise ValueError('duplicate_expression')
                selected=plan.parameters['keyframes']
                label=' / '.join(str(f['frame'])+'→'+rows[f['unit']]['text'] for f in selected)
                offset_start=rows[plan.start_unit]['text_offset'];offset_end=rows[plan.arrival_unit]['text_offset']+len(rows[plan.arrival_unit]['text'])
                text=previous['text'];left=max((text.rfind(mark,0,offset_start) for mark in '，。！？；'),default=-1)+1
                endings=[text.find(mark,offset_end) for mark in '，。！？；']
                right=min((x for x in endings if x>=0),default=len(text))
                context=text[left:right]
                action=dict(intent,**timing,dispatch_s=timing['start_s'],start_unit=plan.start_unit,
                    arrival_unit=plan.arrival_unit,anchor_text=context+'（'+label+'）',label=plan.action,
                    description=descriptions[plan.action],batch=batch,status='accepted')
                accepted.append(action);compiled.append(action);frontier=timing['deadline_s']
                history.append(dict(intent,status='committed',resolved_timing=timing))
            except ValueError as error:
                rejected.append(dict(intent=intent,reason=str(error)))
                history.append(dict(intent,status='skipped',reason=str(error)))
        dump(directory/'compiled.json',dict(accepted=compiled,rejected=rejected,stats=stats))
        attempts.append(dict(index=batch,playback_elapsed_s=0.,visible_units=len(rows),stats=stats,
            actions=compiled+[dict(r['intent'],status='rejected',reason=r['reason']) for r in rejected]))
        print('Batch',batch,'valid',len(candidates),'accepted',len(compiled),'rejected',len(rejected),flush=True)
        if args.whole_text:
            feedback=[dict(intent=r['intent'],reason=r['reason']) for r in rejected]
            if stats.get('invalid_actions'):
                feedback.append(dict(invalid_reasons=stats['invalid_reasons']))
            if not feedback:break
            if batch==2:
                if args.finalize_conflicts:break
                raise RuntimeError('Whole-text plan still has conflicts after revisions; inspect batches')
            continue
        if compiled:empty=0
        else:
            empty+=1
            if not candidates or empty>=2:break
    if not accepted:raise RuntimeError('No executable actions produced; inspect saved batches')
    if added_prefix:
        import soundfile as sf
        import numpy as np
        signal,rate=sf.read(str(audio),dtype='float32',always_2d=True)
        padded=out/'prefixed-audio.wav'
        sf.write(str(padded),np.concatenate([np.zeros((round(added_prefix*rate),signal.shape[1])),signal]),rate,subtype='PCM_16')
        audio=padded
        previous['validation']=dict(previous['validation'],duration_seconds=duration,audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest())
    previous['silence_prefix_s']+=added_prefix
    end=max(accepted[-1]['end_s'],round(duration-.3,3))
    initial='B_Parallel_Drop'
    steps=[dict(type=catalog.assets[initial]['entry']['type'],name=initial,transition_ms=1,
                hold_ms=max(0,round(accepted[0]['start_s']*1000)-1))]
    for i,action in enumerate(accepted):
        next_start=accepted[i+1]['start_s'] if i+1<len(accepted) else end
        step=dict(type=catalog.assets[action['action']]['entry']['type'],name=action['action'],transition_ms=1000,
            hold_ms=round((next_start-action['start_s']-1.-action['core_s'])*1000))
        if action['core_s']:step['duration_ms']=round(action['core_s']*1000)
        steps.append(step)
    sequence=dict(sequence_name='g1_latest_prompt_preplan',preserve_transition=True,steps=steps)
    dump(out/'sequence.json',sequence)
    check=native_validate(sequence,out)
    native=float(re.search(r'([0-9.]+) s from first entry pose',check).group(1))
    if abs(native-end)>.003:raise ValueError('Native timeline duration mismatch')
    dump(out/'motion-snapshot.json',{n:{k:catalog.assets[n]['metadata'][k] for k in ('sha256','version')}
        for n in {initial,'B_Neutral_Rest',*(a['action'] for a in accepted)}})
    dump(out/'padded-timestamps.json',dict(text=previous['text'],duration_seconds=duration,timestamps=rows))
    summary=dict(mode='complete',replay_ready=True,missing_assets=[],action_limit=None,initial_pose=initial,
        silence_prefix_s=previous['silence_prefix_s'],validation=previous['validation'],text=previous['text'],
        excluded_candidates=rejected,added_silence_s=added_prefix,timestamps=rows,actions=accepted,compiled_actions=accepted,sequence=sequence,trajectory_seconds=native,
        attempts=attempts,method=('整段表达Prompt；DeepSeek全文规划，冲突时全局修订；固定1秒切换与验收核心下限。' if args.whole_text else '生产流式Prompt多批预规划。'),
        native_offline_checks=dict(status='passed',note=check),notes=[f"前置静音{previous['silence_prefix_s']}秒，未播放语音、未启动真机。",
        '所有文本与离线时间戳在规划前已知。'],
        prompt_sha256=hashlib.sha256(json.loads((out/'batch-00/messages.json').read_text())[0]['content'].encode()).hexdigest(),
        planning_statistics=dict(batches=len(attempts),candidates=sum(len(a['actions']) for a in attempts),
            accepted=len(accepted),rejected=sum(len(a['actions']) for a in attempts)-len(accepted)))
    report(out,audio,summary);dump(out/'summary.json',summary)
    (out/'system-prompt.md').write_text(json.loads((out/'batch-00/messages.json').read_text())[0]['content'],encoding='utf-8')
    shutil.copy2(REPO/'GuideBot/gesture/prompt_descriptions.json',out/'prompt-descriptions.json')
    print('Result:',out,'actions:',len(accepted),'native_seconds:',native)

if __name__=='__main__':main()
