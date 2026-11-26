"""No cloud/audio/robot: real ROS conversation/gesture/motion Action communication acceptance."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from runtime.app.local_runtime import LocalRuntime
from GuideBot.gesture.catalog import Catalog
from runtime.ipc.transport import ROSGestureService


def until(predicate, seconds=12):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError('Acceptance condition timed out')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native', action='store_true')
    args = parser.parse_args()
    native = None
    runtime = LocalRuntime(offline=True, timing='immediate')
    proxy = None
    events = []
    try:
        runtime.start()
        if args.native:
            from test.integration.ros2.offline_native import OfflineNative
            native = OfflineNative(runtime.root).start()
        proxy = ROSGestureService(runtime.root/'voice-session',
                  lambda kind, **details: events.append(dict(kind=kind, **details)),
                  catalog=Catalog(), execution_mode='simulation', root=runtime.root/'ipc',
                  native_test_request=native.call if native else None)
        proxy.start()
        proxy.request_base_pose('session_started')
        until(lambda: any(e['kind']=='gesture.execution_result' and e.get('action')=='neutral'
                          and e.get('success') for e in events))
        proxy.submit('text', 'r1', text='欢迎参观。')
        proxy.submit('done', 'r1')
        until(lambda: any(e['kind']=='gesture.planned' and e.get('response_id')=='r1' for e in events))
        assert not any(e['kind']=='gesture.command' and e.get('response_id')=='r1' for e in events)
        proxy.submit('playback', 'r1', origin=time.monotonic())
        until(lambda: any(e['kind']=='gesture.command' for e in events))
        until(lambda: any(e['kind']=='gesture.execution_result' and e.get('response_id')=='r1'
                          and e.get('success') for e in events))
        probe = runtime.run('-m','test.integration.ros2.contract_checks',proxy.session_id, check=False)
        (runtime.root/'contract-checks.json').write_text(probe.stdout)
        assert probe.returncode == 0, probe.stderr
        # Sequential event latency: submit enqueue -> ROS subscriber, including host IPC.
        for number in range(100):
            before = sum(e['kind']=='gesture.transport_received' for e in events)
            proxy.submit('playback', 'latency', origin=time.monotonic())
            until(lambda: sum(e['kind']=='gesture.transport_received' for e in events)>before)
        # A rejected high-version context must not poison later trusted updates.
        from runtime.interfaces.contracts import context_to_wire
        proxy.rpc({'op':'context', 'context':context_to_wire(
            {'stage':'untrusted','history':[],'facts':[]}, proxy.session_id, 1,
            999, time.monotonic()+5, 'model_speech')})
        until(lambda: any(e['kind']=='gesture.context_rejected' for e in events))
        assert not any(e['kind']=='gesture.context' and
                       e.get('interaction_context',{}).get('stage')=='untrusted' for e in events)
        # Typed context is installed, then expires instead of remaining trusted indefinitely.
        proxy.set_interaction_context({'scene':dict(confirmed=True,direction='left',target_id='A')}, ttl=.5)
        until(lambda: any(e['kind']=='gesture.context' and e.get('interaction_context',{}).get('scene') for e in events))
        until(lambda: any(e['kind']=='gesture.context_expired' for e in events))
        # Cancel an in-flight goal and fence later messages for the same response.
        proxy.submit('text', 'r2', text='欢迎再次参观。')
        proxy.submit('done', 'r2')
        proxy.submit('playback', 'r2', origin=time.monotonic())
        until(lambda: any(e['kind']=='gesture.command' and e.get('response_id')=='r2' for e in events))
        proxy.submit('cancel','r2',reason='acceptance_interrupt')
        until(lambda: any(e['kind']=='gesture.execution_result' and e.get('response_id')=='r2'
                          and not e.get('success') for e in events))
        until(lambda: any(e['kind']=='gesture.execution_result' and e.get('job_id')=='base_pose:2'
                          and e.get('success') for e in events))
        proxy.submit('text','r2',text='旧回复不得恢复。')
        until(lambda: any(e['kind']=='gesture.input_rejected' for e in events))
        assert not proxy.failed.is_set(), proxy.error
        runtime.pause()
        try:
            until(lambda: proxy.failed.is_set(), seconds=5)
            assert proxy.error == 'ROS heartbeat expired'
        finally:
            runtime.resume()
        if native:
            until(lambda: native.call({'状态':True})['status']['state']=='idle')
        proxy.close()
        proxy = None
        latencies = sorted(e['latency_ms'] for e in events
                           if e['kind']=='gesture.transport_received' and e.get('response_id')=='latency')
        report = dict(latency_ms={key:latencies[min(len(latencies)-1, int(len(latencies)*p))]
                                  for key,p in [('p50',.50),('p95',.95),('p99',.99)]},
                      ok=True, hardware=False, cloud=False, native_player=bool(native),
                      checks=['typed_conversation', 'local_planner_stream', 'motion_action_result',
                              'initial_listening_neutral','no_action_before_playback','cancel_then_neutral',
                              'context_source_rejection','context_expiry','action_cancel','closed_reply_fence','heartbeat_loss','session_shutdown'],
                      events=events)
        (runtime.root/'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(dict(ok=True, evidence=str(runtime.root/'acceptance.json')), ensure_ascii=False))
    finally:
        if proxy:
            proxy.close()
        runtime.stop()
        if native:
            native.stop()


if __name__ == '__main__':
    main()
