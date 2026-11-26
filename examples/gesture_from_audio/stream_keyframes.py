#!/usr/bin/env python3
"""Exercise the production SSE planner/scheduler offline from a timed speech file.

Default: deterministic recorded intents; --live: DeepSeek network requests.
Neither mode initializes audio SDKs or robot control. Future timestamp exposure
is simulated lookahead, not evidence of actual streaming aligner latency.
"""
import argparse
import json
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from GuideBot.gesture.catalog import Catalog, make_input, messages
from GuideBot.gesture.planner import Planner
from GuideBot.gesture.scheduler import Scheduler
from GuideBot.runtime.workers.motion_executor import MotionExecutor
from run import inputs, dump
from complete_plan import native_validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='调用真实DeepSeek API，仍不播放或连接机器人')
    parser.add_argument('--lookahead',type=float,default=6.)
    parser.add_argument('--output',type=Path,default=REPO/'artifacts/gesture-from-audio/g1-self-introduction/stream-keyframes')
    args = parser.parse_args()
    if not 0 <= args.lookahead <= 30: parser.error('lookahead must be 0..30 seconds')
    out = args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    _,_,doc,_ = inputs(Path(__file__).with_name('scenario.json'))
    catalog = Catalog(); clock=[0.];events=[]; commands=[]
    executor = MotionExecutor(catalog,clock=lambda:clock[0])
    def emit(kind,**details):
        value = dict(kind=kind,simulation_elapsed_s=clock[0],**details)
        if kind == 'gesture.command':
            try:
                value['execution'] = executor.handle(kind,details)
                commands.append(value)
            except ValueError as error:
                value['execution_error'] = str(error)
        events.append(value)
        return value
    scheduler = Scheduler(catalog,emit,clock=lambda:clock[0])
    planner = Planner(catalog) if args.live else None
    # Fixture mirrors the manual semantic example but targets original audio times.
    fixture = [('L_Short_Nudge',3),('R_Draw_In_Hold',17),('B_Parallel_Drop',21),
               ('B_Lateral_Beat',32),('B_Alternating_Swing',37),('L_Forward_Point',42),
               ('R_Upright_Split',48),('B_Sync_Push_Pull',73),('B_Neutral_Rest',112)]
    emitted=set(); request=0; last_count=-1
    rows=doc['timestamps']; duration=doc['duration_seconds']
    while clock[0] <= duration+3.+.2:
        count=sum(row['start'] <= max(0.,clock[0]-3.)+args.lookahead for row in rows)
        text=''.join(row['text'] for row in rows[:count])
        scheduler.text('r',text)
        units=scheduler.replies['r'].units
        anchors=[dict(index=i,start=row['start'],text=units[i]['text'],text_offset=units[i]['text_offset'])
                 for i,row in enumerate(rows[:count])]
        scheduler.alignment('r',dict(version=request+round(clock[0]*1000),anchors=anchors))
        if clock[0] >= 3.: scheduler.playback('r',3.)
        if count != last_count and count:
            payload=make_input('r',text,existing=scheduler.planning_history('r'),complete=count==len(rows))
            from GuideBot.gesture.timing import phases
            payload.update(timing_contract='semantic_keyframes',playback_elapsed_s=max(0.,clock[0]-3.),
                playback_started=clock[0]>=3.,suggested_planning_lead_s=2.,alignment_anchors=anchors,
                execution_timing=[dict(id=name,minimum_core_s=phases(catalog.assets[name])[1],
                    minimum_hold_s=phases(catalog.assets[name])[2],transition_s=1.,
                    keyframe_count=catalog.assets[name]['frames']) for name in catalog.actions])
            dump(out/('request-%02d.json'%request),dict(messages=messages(catalog,payload)))
            def accept(plan): scheduler.add('r',plan,units,request)
            if planner:
                started=time.monotonic()
                stats=planner.plan(payload,accept)
                clock[0] += time.monotonic()-started
                dump(out/('response-%02d.json'%request),stats)
            else:
                for name,unit in fixture:
                    if unit < count and (name,unit) not in emitted:
                        if name == 'R_Upright_Split' and count <= 51:
                            continue
                        frames = [dict(frame=catalog.assets[name]['frames']-1,unit=unit)]
                        if name == 'R_Upright_Split':
                            frames = [dict(frame=0,unit=48),dict(frame=1,unit=51)]
                        accept(catalog.validate(dict(action=name,keyframes=frames,hold_s=
                            .3 if name=='R_Draw_In_Hold' else .5 if name=='L_Forward_Point' else 0.),range(count),[]))
                        emitted.add((name,unit))
            request+=1; last_count=count
        scheduler.tick()
        if scheduler.active and clock[0]>=scheduler.active['busy_until']:
            scheduler.execution_result(scheduler.active['job'].id,True,'simulated_completion')
        clock[0]=round(clock[0]+.02,3)
    # Validate every dispatched physical command through the native parser.
    for i,command in enumerate(commands):
        directory=out/('native-%02d'%i);directory.mkdir(exist_ok=True)
        native_validate(command['execution']['sequence']['序列'],directory)
    dump(out/'events.json',events)
    dump(out/'summary.json',dict(mode='live_deepseek_simulated_playback' if args.live else 'offline_fixture',
        commands=len(commands),skipped=[e for e in events if e['kind']=='gesture.skipped'],
        lookahead_s=args.lookahead,startup_buffer_s=3.,hardware_started=False,
        limitation='未来时间戳提前量为模拟，不证明真实流式对齐器能提前给出时间戳。'))
    (out/'report.md').write_text('# 流式关键词规划验证\n\n模式：'+('真实 DeepSeek SSE，模拟播放' if args.live else '离线意图夹具，模拟播放')+
        '\n\n下发并通过原生解析：%d 个动作。未播放音频、未连接真机。\n\n'%len(commands)+
        '时间戳采用模拟提前量；实际 DeepSeek 延迟、时间戳提前量和真机协调仍须现场验证。\n',encoding='utf-8')
    print('Checked %d native commands; no audio or robot started. Report: %s'%(len(commands),out/'report.md'))

if __name__ == '__main__': main()
