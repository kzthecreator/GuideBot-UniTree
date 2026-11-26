"""Keyword timing through real local ROS + native offline Player; no devices/API."""
import argparse
import json
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def probe(session):
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor
    from GuideBot.ros2.nodes.gesture_node import ROSMotionExecutor
    from GuideBot.runtime.ipc import call
    from GuideBot.gesture.catalog import Catalog
    from GuideBot.gesture.scheduler import Scheduler
    from GuideBot.ros2.nodes.common import ROOT

    rclpy.init()
    node = Node('guidebot_deadline_probe')
    results, events = queue.Queue(), []
    node.service = SimpleNamespace(submit=lambda kind, **fields: results.put(fields))
    shared = SimpleNamespace(node=node, mode='simulation',
        fence=SimpleNamespace(session=session, generation=1),
        host=lambda value: call(ROOT/'host.sock', dict(value, session_id=session, generation=1)),
        notify=lambda kind, value: events.append(dict(kind=kind, **value)))
    executor = ROSMotionExecutor(node, shared, on_result=node.service.submit)
    def emit(kind, **event):
        row = dict(kind=kind, **event)
        events.append(row)
        try:
            return executor.handle(kind, event)
        except Exception as error:
            row['execution_error'] = str(error)
            return dict(execution_error=str(error))
    catalog = Catalog()
    scheduler = Scheduler(catalog, emit, immediate=True)
    spinning = MultiThreadedExecutor(num_threads=3)
    spinning.add_node(node)
    thread = threading.Thread(target=spinning.spin, daemon=True)
    thread.start()
    try:
        origin = time.monotonic()
        scheduler.text('keyframe-probe', '视觉语音')
        units = scheduler.replies['keyframe-probe'].units
        plan = catalog.validate(dict(action='R_Upright_Split', keyframes=[
            dict(frame=0,unit=0),dict(frame=1,unit=3)],hold_s=.3),range(4),[])
        scheduler.add('keyframe-probe',plan,units)
        scheduler.alignment('keyframe-probe',dict(version=1,anchors=[
            dict(index=i,text=u['text'],text_offset=u['text_offset'],start=t)
            for i,(u,t) in enumerate(zip(units,[2.,2.3,2.6,3.2]))]))
        scheduler.playback('keyframe-probe',origin)
        completed = None
        deadline = origin+7.
        while time.monotonic() < deadline:
            scheduler.tick()
            try:
                result=results.get(timeout=.01)
            except queue.Empty:
                continue
            scheduler.execution_result(result['job_id'],result['success'],result.get('reason',''))
            completed=result
            break
        assert completed and completed['success'], (completed,events)
        commands=[e for e in events if e['kind']=='gesture.command']
        assert len(commands)==1,events
        command=commands[0]
        assert command['timing_mode']=='semantic_keyframes'
        assert abs(command['core_s']-1.2)<.001, command
        assert not any(e['kind']=='gesture.reset' for e in events),events
        assert not any('execution_error' in e for e in events),events
        return dict(ok=True,checks=['typed_semantic_phases_through_ROS_IPC',
            'native_completed_extended_core', 'no_preemption'],events=events)
    finally:
        spinning.shutdown()
        thread.join(3)
        node.destroy_node()
        rclpy.shutdown()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe')
    args=parser.parse_args()
    if args.probe:
        print(json.dumps(probe(args.probe),ensure_ascii=False))
        return
    from GuideBot.runtime.local_runtime import LocalRuntime
    from GuideBot.runtime.transport import ROSGestureService
    from GuideBot.gesture.catalog import Catalog
    from tools.ros2.offline_native import OfflineNative
    runtime=LocalRuntime(offline=True,timing='aligned')
    native=proxy=None
    try:
        runtime.start()
        native=OfflineNative(runtime.root).start()
        proxy=ROSGestureService(runtime.root/'voice-session',catalog=Catalog(),
            execution_mode='simulation',root=runtime.root/'ipc',native_test_request=native.call)
        proxy.start()
        result=runtime.run('-m','tools.ros2.keyframe_acceptance','--probe',proxy.session_id,check=False)
        (runtime.root/'keyframe-probe.stdout').write_text(result.stdout)
        (runtime.root/'keyframe-probe.stderr').write_text(result.stderr)
        assert result.returncode==0,result.stderr
        report=json.loads(result.stdout)
        report.update(hardware=False,cloud=False,audio=False)
        evidence=runtime.root/'keyframe-acceptance.json'
        evidence.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(json.dumps(dict(ok=True,evidence=str(evidence))))
    finally:
        if proxy: proxy.close()
        runtime.stop()
        if native: native.stop()


if __name__=='__main__': main()
