#!/usr/bin/env python3
"""Compile the user's phrase-by-phrase gestures using approved timing and silence."""
import argparse
import hashlib
import math
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO));sys.path.insert(0,str(Path(__file__).resolve().parent))
from run import inputs,dump,report
from complete_plan import phase_times,native_validate
from GuideBot.gesture.catalog import Catalog,minimal_document


def arrange(catalog,doc,*,closing="required"):
    # A final-frame target is not the same as arrival at the first frame.
    specs=[('最后这台','L_Short_Nudge',3,'final',0.),
           ('也就是我啦','R_Draw_In_Hold',17,'final',.3),
           ('双足','B_Parallel_Drop',21,'first',0.),
           ('自由度丰富','B_Lateral_Beat',32,'final',0.),
           ('行走稳定','B_Alternating_Swing',37,'final',0.),
           ('ROS2','L_Forward_Point',42,'first',.5),
           ('视觉、语音','R_Upright_Split',48,'first',0.),
           ('验证……算法','B_Sync_Push_Pull',73,'final',0.)]
    closing_name='B_Neutral_Rest' if closing=='B_Neutral_Rest' else ('R_Center_Rest' if 'R_Center_Rest' in catalog.actions else None)
    if closing_name:
        # Once the final static hold ends the controller remains at the same
        # pose through the audio tail; leave startup/dispatch slack in deadline.
        specs.append(('核心载体（回到中性姿态）' if closing_name=='B_Neutral_Rest' else '核心载体',
                      closing_name,112,'final',round(doc['duration_seconds']-doc['timestamps'][112]['start']-.3,3)))
    descriptions={a['id']:a['description'] for a in minimal_document(catalog)['actions']}
    approved_core=phase_times(catalog.assets['L_Short_Nudge'],None)[1]
    earliest=doc['timestamps'][3]['start']-1.-approved_core
    padding=math.ceil(max(0.,.3-earliest)*10)/10
    rows=[];previous_end=.001
    for phrase,name,anchor,reference,hold in specs:
        asset=catalog.assets[name];entry,core,_=phase_times(asset,None,transition_s=1.)
        base_core=core;target=doc['timestamps'][anchor]['start']+padding
        if name=='R_Upright_Split':
            # Frame 0 at 视觉, frame 1 at 语音; no guessed joint geometry.
            core=round(doc['timestamps'][51]['start']-doc['timestamps'][48]['start'],3)
        start=round(target-entry-(core if reference=='final' else 0.),3)
        end=round(start+entry+core+hold,3)
        minimum=asset['metadata'].get('timing_profile',{}).get('minimum_total_ms',0)/1000
        if start<previous_end-.001:raise ValueError('逐句安排仍存在时间冲突: '+name)
        if entry+core+hold+.001<minimum:raise ValueError('动作短于已验收总下限: '+name)
        if core+.000001<base_core:raise ValueError('核心压缩超出既有验收配置，须先重新试播: '+name)
        rows.append(dict(action=name,phrase=phrase,start_s=start,arrival_s=round(start+entry,3),
            target_s=round(target,3),target_frame=reference,end_s=end,transition_s=entry,core_s=core,hold_s=hold,
            approved_core_s=base_core,start_unit=anchor,arrival_unit=anchor,dispatch_s=start,
            anchor_text=phrase,description=descriptions[name],label=name))
        previous_end=end
    steps=[dict(type=catalog.assets['B_Parallel_Drop']['entry']['type'],name='B_Parallel_Drop',transition_ms=1,
                hold_ms=round(rows[0]['start_s']*1000)-1)]
    for i,row in enumerate(rows):
        gap=rows[i+1]['start_s']-row['end_s'] if i+1<len(rows) else 0.
        step=dict(type=catalog.assets[row['action']]['entry']['type'],name=row['action'],transition_ms=1000,
                  hold_ms=round((row['hold_s']+gap)*1000))
        if row['core_s']:step['duration_ms']=round(row['core_s']*1000)
        steps.append(step)
    return padding,rows,dict(sequence_name='g1_manual_semantic',preserve_transition=True,steps=steps)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--closing',choices=('required','B_Neutral_Rest'),default='required',help='B_Neutral_Rest明确以已有中性姿态替代缺失收束')
    parser.add_argument('--output',type=Path,default=REPO/'artifacts/gesture-from-audio/g1-self-introduction/manual-approved-timing-padded')
    args=parser.parse_args();out=args.output.expanduser().resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('请选择空的新目录，不覆盖既有规划')
    out.mkdir(parents=True,exist_ok=True)
    config,audio,doc,validation=inputs(Path(__file__).with_name('scenario.json'))
    catalog=Catalog();padding,actions,sequence=arrange(catalog,doc,closing=args.closing)
    import numpy as np
    import soundfile as sf
    signal,rate=sf.read(str(audio),dtype='float32',always_2d=True)
    prefix=np.zeros((round(padding*rate),signal.shape[1]),dtype='float32')
    padded=out/'audio.wav';sf.write(str(padded),np.concatenate([prefix,signal]),rate,subtype='PCM_16')
    decoded,decoded_rate=sf.read(str(padded),always_2d=True)
    assert np.all(decoded[:len(prefix)]==0)
    padded_doc=dict(doc,duration_seconds=len(decoded)/decoded_rate,
        timestamps=[dict(r,start=round(r['start']+padding,6),end=round(r['end']+padding,6)) for r in doc['timestamps']])
    validation=dict(validation,source_audio_sha256=validation['audio_sha256'],
                    audio_sha256=hashlib.sha256(padded.read_bytes()).hexdigest(),
                    original_duration_seconds=validation['duration_seconds'],
                    duration_seconds=padded_doc['duration_seconds'],silence_prefix_s=padding)
    dump(out/'padded-timestamps.json',padded_doc)
    check=native_validate(sequence,out)
    import re
    native=float(re.search(r'([0-9.]+) s from first entry pose',check).group(1))
    if abs(native-actions[-1]['end_s'])>.003:raise ValueError('原生完整轨迹时长与时间表不一致')
    missing=[] if args.closing=='B_Neutral_Rest' or 'R_Center_Rest' in catalog.actions else ['R_Center_Rest']
    # Do not invent or substitute the requested but absent closing posture.
    summary=dict(mode='complete',replay_ready=not missing,missing_assets=missing,action_limit=None,
        audio_file='audio.wav',initial_pose='B_Parallel_Drop',silence_prefix_s=padding,validation=validation,text=doc['text'],
        timestamps=padded_doc['timestamps'],actions=actions,compiled_actions=actions,sequence=sequence,closing_pose='B_Neutral_Rest' if args.closing=='B_Neutral_Rest' else 'R_Center_Rest',
        trajectory_seconds=native,method='按用户逐句安排；1秒切换；已验收核心时间；前置全零PCM静音；'+('按用户明确要求以B_Neutral_Rest收束。' if args.closing=='B_Neutral_Rest' else '收束资产缺失时禁止真机入口。'),
        native_offline_checks=dict(status='passed',note=check),attempts=[],
        notes=[('按用户授权以B_Neutral_Rest替代右臂腹前中线收束，到位后维持至语音结束。' if args.closing=='B_Neutral_Rest' else '右臂腹前中线收束缺失时不自动替换。'),
               '视觉/语音采用现有两个关键帧，不能证明实际分别精确指向眼睛/嘴部；未生成视线控制。'])
    dump(out/'sequence.json',sequence)
    dump(out/'motion-snapshot.json',{name:{k:catalog.assets[name]['metadata'][k] for k in ('sha256','version')}
        for name in {'B_Neutral_Rest',*(a['action'] for a in actions)}})
    report(out,padded,summary);dump(out/'summary.json',summary)
    report_path=out/'report.md'
    report_path.write_text(report_path.read_text()+f'\n## 准备状态\n\n语音前填充{padding:.3f}秒全零PCM；所有文字时间戳整体平移。\n\n'+
        ('**缺失R_Center_Rest收束姿态，当前禁止真机入口。** 前8段仅通过离线连续轨迹与时间检查；需补录该姿态，或明确指定替代后才能完整照此演练。\n' if missing else '收束已编入并通过原生整段校验；采用已有B_Neutral_Rest替代原腹前中线姿态。序列结束后仍维持同一中性姿态直至音频结束和释放。\n'))
    print('Results:',out,'silence_s:',padding,'actions:',len(actions),'native_seconds:',native,'missing:',missing)


if __name__=='__main__':main()
