#!/usr/bin/env python3
"""Rehearse the current complete plan with real arms, after explicit Enter only."""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
import time

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from GuideBot.gesture.catalog import Catalog
from GuideBot.runtime.workers.motion import MotionRuntime
from GuideBot.runtime.workers.motion_executor import MotionExecutor
# Importing the adapter does not load or initialize the Unitree SDK.
sys.path.insert(0,str(Path(__file__).resolve().parent))
from speaker_g1 import G1Speaker

DEFAULT_RESULT=REPO/'artifacts/gesture-from-audio/g1-self-introduction/manual-neutral-closing'


def load_plan(result,catalog):
    summary=json.loads((result/'summary.json').read_text(encoding='utf-8'))
    if summary.get('mode') not in {'stream','complete'}:raise ValueError('仅接受完整预规划或stream结果，不接受未编译的preplan方案')
    if summary.get('replay_ready') is False:
        raise ValueError('方案尚未满足完整演练条件: '+', '.join(summary.get('missing_assets',[])))
    audio=result/summary.get('audio_file','audio.mp3')
    if hashlib.sha256(audio.read_bytes()).hexdigest()!=summary['validation']['audio_sha256']:
        raise ValueError('报告音频与生成规划时的音频不一致')
    snapshot=json.loads((result/'motion-snapshot.json').read_text(encoding='utf-8'))
    actions=summary['actions'];previous_end=0.
    if not actions:raise ValueError('方案没有可执行动作')
    for action in actions:
        name=action['action']
        if name not in catalog.actions:raise ValueError('动作未启用或未验收: '+name)
        meta=catalog.assets[name]['metadata']
        if any(snapshot[name][key]!=meta[key] for key in ('sha256','version')):
            raise ValueError('动作录制或时间配置已变化，请重新规划: '+name)
        row={key:action[key] for key in ('action','start_unit','arrival_unit','start_s','end_s')}
        catalog.validate(row,range(len(summary['timestamps'])),[])
        if not 0<=action['start_s']<=action['dispatch_s']<action['end_s']<=summary['validation']['duration_seconds']:
            raise ValueError('动作窗口越界')
        if action['start_s']<previous_end:raise ValueError('方案窗口有重叠')
        previous_end=action['end_s']
        # Verify current execution translation without sockets or hardware.
        if summary['mode']=='stream':
            MotionExecutor(catalog,mode='simulation',clock=lambda a=action:1000+a['dispatch_s']).sequence(dict(
                action=name,job_id='check',start_monotonic=1000+action['start_s'],
                arrival_monotonic=1000+action['end_s'],end_monotonic=1000+action['end_s']))
    if summary['mode']=='complete':
        limit=summary.get('action_limit',3)
        if (limit is not None and (type(limit) is not int or limit<1 or len(actions)>limit)) or 'B_Neutral_Rest' not in snapshot:
            raise ValueError('完整规划必须包含B_Neutral_Rest起始姿态且符合方案声明的数量策略')
        initial_name=summary.get('initial_pose','B_Neutral_Rest')
        if initial_name not in catalog.actions or initial_name not in snapshot:
            raise ValueError('起始姿态未验收或缺少资产快照')
        initial_meta=catalog.assets[initial_name]['metadata']
        if any(snapshot[initial_name][k]!=initial_meta[k] for k in ('sha256','version')):
            raise ValueError('起始姿态已经变化，请重新规划')
        B_Neutral_Rest=catalog.assets['B_Neutral_Rest']['metadata']
        if any(snapshot['B_Neutral_Rest'][k]!=B_Neutral_Rest[k] for k in ('sha256','version')):
            raise ValueError('B_Neutral_Rest已经变化，请重新规划')
        from complete_plan import native_validate
        check=native_validate(summary['sequence'],result)
        import re
        match=re.search(r'([0-9.]+) s from first entry pose',check)
        if not match or abs(float(match.group(1))-summary['trajectory_seconds'])>.003:
            raise ValueError('完整时间表与原生轨迹总时长不一致')
    return summary,audio


def rehearse(result,catalog,summary,audio_path,logdir,*,runtime_factory=MotionRuntime,
             speaker_factory=G1Speaker,clock=time.monotonic,sleep=time.sleep):
    logdir.mkdir(parents=True,exist_ok=True)
    runtime=runtime_factory();runtime.log_directory=logdir
    if isinstance(runtime, MotionRuntime):
        from functools import partial
        from GuideBot.runtime.environment import sdk_environment
        runtime.popen=partial(runtime.popen,env=sdk_environment())
    audio=None;executor=MotionExecutor(catalog,mode='robot',request=runtime.request,clock=clock)
    events=(logdir/'events.jsonl').open('w',encoding='utf-8');last_native=None
    def emit(kind,**fields):
        record=dict(event=kind,**fields)
        events.write(json.dumps(record,ensure_ascii=False)+'\n');events.flush()
        print(json.dumps(record,ensure_ascii=False),flush=True)
    try:
        runtime.start()  # Acquire before establishing audio time zero.
        audio=speaker_factory()
        origin=audio.start(audio_path,logdir);index=0
        emit('audio_started',clock_reference='G1 SDK playback.started after first successful PlayStream, not DAC timestamp',origin=origin)
        while audio.poll() is None:
            elapsed=clock()-origin
            if runtime.process.poll() is not None:raise RuntimeError('原生运动服务退出，终止演练')
            status=runtime._status()
            if status.get('ownership')!='owned':raise RuntimeError('双臂控制权已释放或失效，终止演练')
            native=status.get('execution')
            signature=json.dumps(native,sort_keys=True)
            if native and signature!=last_native:
                emit('native_execution',elapsed_s=elapsed,details=native);last_native=signature
            while index<len(summary['actions']) and summary['actions'][index]['dispatch_s']<=elapsed:
                action=summary['actions'][index];job=f'rehearsal-{index}'
                event=dict(action=action['action'],job_id=job,
                    start_monotonic=origin+action['start_s'],arrival_monotonic=origin+action['end_s'],
                    end_monotonic=origin+action['end_s'])
                try:
                    response=executor.handle('gesture.command',event)
                    emit('submitted',elapsed_s=clock()-origin,job_id=job,action=action['action'],response=response)
                except ValueError as error:
                    # Expired/too short/busy: skip, never move a deadline later.
                    emit('skipped',elapsed_s=clock()-origin,job_id=job,action=action['action'],reason=str(error))
                index+=1
            sleep(.02)
        if audio.returncode:raise RuntimeError('G1扬声器播放失败，检查audio-events.jsonl与audio-stderr.log')
        emit('audio_finished',elapsed_s=clock()-origin)
    except BaseException as error:
        emit('stopping',reason=type(error).__name__)
        raise
    finally:
        # Cleanup also runs if acquire or audio startup fails, or Ctrl+C occurs.
        try:
            if audio is not None:
                audio.close()
        finally:
            try:runtime.stop()
            finally:
                emit('session_closed');events.close()



def complete_rehearsal(catalog,summary,audio_path,logdir,*,runtime_factory=MotionRuntime,
                       speaker_factory=G1Speaker,clock=time.monotonic,sleep=time.sleep):
    """One precompiled sequence; no per-action queueing or late duration guesses."""
    import copy
    logdir.mkdir(parents=True,exist_ok=True)
    runtime=runtime_factory();runtime.log_directory=logdir
    if isinstance(runtime,MotionRuntime):
        from functools import partial
        from GuideBot.runtime.environment import sdk_environment
        runtime.popen=partial(runtime.popen,env=sdk_environment())
    speaker=None
    log=(logdir/'events.jsonl').open('w',encoding='utf-8')
    def emit(kind,**fields):
        record=dict(event=kind,**fields)
        log.write(json.dumps(record,ensure_ascii=False)+'\n');log.flush()
        print(json.dumps(record,ensure_ascii=False),flush=True)
    def wait_job(job,timeout):
        deadline=clock()+timeout
        while clock()<deadline:
            if runtime.process.poll() is not None:raise RuntimeError('运动服务退出')
            status=runtime._status();execution=status.get('execution') or {}
            if status.get('ownership')!='owned':raise RuntimeError('双臂控制权失效')
            if execution.get('job_id')==job:
                if execution['state']=='rejected':raise RuntimeError(execution.get('reason','动作被拒绝'))
                if execution['state']=='completed' and status['state']=='idle':return
            sleep(.02)
        raise TimeoutError('等待准备动作完成超时')
    try:
        runtime.start()
        initial_name=summary.get('initial_pose','B_Neutral_Rest')
        B_Neutral_Rest=catalog.assets[initial_name]['entry']
        state=runtime._status()
        pose=state.get('commanded_arm')
        if not isinstance(pose,list) or len(pose)!=14:
            raise RuntimeError('缺少接管后关节姿态，请更新原生运动服务')
        entry=2.0  # Explicit preparation duration; no geometric timing estimate.
        if entry>30:raise RuntimeError('初始姿态切换超过支持时长，未开始音频')
        runtime.request({'序列':dict(sequence_name='prepare_neutral',steps=[dict(
            type=B_Neutral_Rest['type'],name=initial_name,transition_ms=round(entry*1000),hold_ms=500)]),
            'end_monotonic':clock()+entry+6,'job_id':'prepare-neutral'})
        wait_job('prepare-neutral',entry+6)
        emit('initial_pose_ready',pose=initial_name,message='播放前准备完成，连续轨迹从已验收起始姿态开始')
        speaker=speaker_factory();origin=speaker.start(audio_path,logdir)
        sequence=copy.deepcopy(summary['sequence'])
        # Only trim initial static waiting; never shorten any moving segment.
        elapsed_ms=math.ceil(max(0.,clock()-origin)*1000)
        first=sequence['steps'][0]
        if first['hold_ms']-elapsed_ms<50:
            raise RuntimeError('音频启动传递超过预留初始等待，未发送任何正式轨迹')
        first['hold_ms']-=elapsed_ms
        emit('audio_started',origin=origin,trimmed_initial_hold_ms=elapsed_ms)
        response=runtime.request({'序列':sequence,'end_monotonic':origin+summary['validation']['duration_seconds'],
                                  'job_id':'complete-timeline'})
        emit('timeline_submitted',response=response)
        last=None;started=False;completed=False
        while speaker.poll() is None:
            if runtime.process.poll() is not None:raise RuntimeError('运动服务退出')
            status=runtime._status();execution=status.get('execution') or {}
            if status.get('ownership')!='owned':raise RuntimeError('双臂控制权失效')
            signature=(execution.get('state'),status.get('active_step_index'))
            if execution.get('job_id')=='complete-timeline':
                if signature!=last:emit('timeline_execution',elapsed_s=clock()-origin,
                                       details=execution,active_step_index=status.get('active_step_index'));last=signature
                if execution['state']=='rejected':raise RuntimeError(execution.get('reason','连续轨迹被拒绝'))
                started=started or execution['state'] in {'running','completed'}
                completed=completed or execution['state']=='completed'
            if not started and clock()-origin>1.:raise RuntimeError('连续轨迹未及时启动')
            sleep(.02)
        if speaker.returncode:raise RuntimeError('G1扬声器播放失败')
        if not completed:raise RuntimeError('音频结束时完整轨迹尚未确认完成')
        emit('complete',message='音频和完整连续轨迹完成')
    finally:
        try:
            if speaker is not None:speaker.close()
        finally:
            try:runtime.stop()
            finally:emit('session_closed');log.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result',type=Path,default=DEFAULT_RESULT)
    parser.add_argument('--legacy-stream',action='store_true',help='明确请求旧stream回放，不推荐用于本轮完整规划')
    parser.add_argument('--robot',action='store_true',help='Enter确认后才连接机器人；默认只检查')
    args=parser.parse_args();result=args.result.expanduser().resolve()
    catalog=Catalog();summary,audio=load_plan(result,catalog)
    if summary["mode"]=="stream" and not args.legacy_stream:
        raise ValueError("新入口默认完整规划；旧stream须显式--legacy-stream")
    print(f"{summary['mode']}方案：{len(summary['actions'])}个动作，{summary['validation']['duration_seconds']:.3f}秒。")
    print('完整规划在播放前已完成；演练不会现场重新调用LLM。')
    if not args.robot:
        print('只读检查通过；未连接机器人或播放音频。真机演练需显式添加--robot，并按Enter。')
        return
    print('将连接真机并接管双臂。请先关闭导览、网页试播及其他运动控制程序。')
    print('确认机器人运控模式、稳定站立、急停可用且现场有人监护。音频通过G1扬声器SDK播放。')
    answer=input('按 Enter 开始，输入其他内容取消：')
    if answer:return
    catalog=Catalog();summary,audio=load_plan(result,catalog)
    logdir=REPO/'artifacts/gesture-from-audio/rehearsals'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    if summary["mode"]=="complete":complete_rehearsal(catalog,summary,audio,logdir)
    else:rehearse(result,catalog,summary,audio,logdir)
    print('演练结束，控制权已释放；日志：',logdir)


if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('\n演练已停止')
