"""Semantic text -> local timestamps -> real ROS/native offline; no cloud/devices."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def probe(session):
    import rclpy
    from rclpy.node import Node
    from rclpy.executors import MultiThreadedExecutor
    from runtime.ros2.nodes.gesture_node import ROSMotionExecutor
    from runtime.ros2.nodes.common import ROOT
    from runtime.ipc.channel import call
    from GuideBot.gesture.catalog import units_for
    from GuideBot.gesture.service import GestureService

    class SemanticFixture:
        semantic = True
        def analyze(self, text, cancelled):
            assert text == '欢迎各位来到我们的机器人展厅。'
            return dict(actions=[dict(action='greet_open', begin=dict(text='欢迎', occurrence=1),
                                      finish_by=dict(text='展厅', occurrence=1))])

    rclpy.init()
    node = Node('guidebot_semantic_probe')
    shared = SimpleNamespace(node=node, mode='simulation',
        fence=SimpleNamespace(session=session, generation=1),
        host=lambda value: call(ROOT/'host.sock', dict(value, session_id=session, generation=1)),
        notify=lambda *args: None)
    motion = ROSMotionExecutor(node, shared, on_result=lambda kind, **kw: node.service.submit(kind, **kw))
    events = []
    node.service = GestureService(ROOT/'semantic-probe', planner=SemanticFixture(), executor=motion,
        on_event=lambda kind, **kw: events.append(dict(kind=kind, **kw)))
    spinning = MultiThreadedExecutor(num_threads=3)
    spinning.add_node(node)
    thread = threading.Thread(target=spinning.spin, daemon=True)
    thread.start()
    node.service.start()
    try:
        text = '欢迎各位来到我们的机器人展厅。'
        origin = time.monotonic()+1
        node.service.submit('text', 'semantic-probe', text=text)
        units = units_for(text)
        node.service.submit('alignment', 'semantic-probe', version=1, anchors=[
            dict(index=i, text=u['text'], text_offset=u['text_offset'], start=i*.3)
            for i,u in enumerate(units)])
        node.service.submit('playback', 'semantic-probe', origin=origin)
        # Revise both anchors before dispatch: recover the intent, retain the
        # original end even though the new acoustic estimate moves it later.
        bound_until = time.monotonic()+2
        while not any(e['kind']=='gesture.window_bound' for e in events):
            assert time.monotonic() < bound_until, events
            time.sleep(.01)
        finish = next(u['unit_id'] for u in units if u['text']=='展')
        revised = [dict(index=i, text=u['text'], text_offset=u['text_offset'],
                        start=i*.3+(.1 if i==0 else .15 if i==finish else 0))
                   for i,u in enumerate(units)]
        node.service.submit('alignment', 'semantic-probe', version=2, anchors=revised)
        until = time.monotonic()+12
        while time.monotonic() < until:
            result = next((e for e in events if e['kind']=='gesture.completed'), None)
            if result:
                break
            assert not any(e['kind']=='gesture.error' for e in events), events
            time.sleep(.03)
        else:
            raise AssertionError('Semantic motion did not complete: '+json.dumps(events))
        bound = next(e for e in events if e['kind']=='gesture.window_bound')
        command = next(e for e in events if e['kind']=='gesture.command')
        assert bound['start_s'] == 0
        assert command['end_monotonic'] == origin+bound['end_s']
        assert any(e['kind']=='gesture.semantic_bound' for e in events)
        assert any(e['kind']=='gesture.replanning' for e in events)
        return dict(ok=True, hardware=False, audio=False, cloud=False,
                    checks=['plain_text_fixture', 'exact_quote_binding', 'local_timestamp_join',
                            'alignment_revision_recovered', 'deadline_not_extended',
                            'fixed_deadline_through_ROS', 'native_offline_completion'], events=events)
    finally:
        node.service.close()
        spinning.shutdown()
        thread.join(3)
        node.destroy_node()
        rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe')
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe(args.probe), ensure_ascii=False))
        return
    from runtime.app.local_runtime import LocalRuntime
    from runtime.ipc.transport import ROSGestureService
    from GuideBot.gesture.catalog import Catalog
    from test.integration.ros2.offline_native import OfflineNative
    runtime = LocalRuntime(offline=True)
    native = proxy = None
    try:
        runtime.start()
        native = OfflineNative(runtime.root).start()
        proxy = ROSGestureService(runtime.root/'voice-session', catalog=Catalog(),
            execution_mode='simulation', root=runtime.root/'ipc', native_test_request=native.call)
        proxy.start()
        result = runtime.run('-m', 'test.integration.ros2.semantic_acceptance', '--probe', proxy.session_id, check=False)
        (runtime.root/'semantic-probe.stdout').write_text(result.stdout)
        (runtime.root/'semantic-probe.stderr').write_text(result.stderr)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        evidence = runtime.root/'semantic-acceptance.json'
        evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(dict(ok=True, evidence=str(evidence))))
    finally:
        if proxy:
            proxy.close()
        runtime.stop()
        if native:
            native.stop()


if __name__ == '__main__':
    main()
