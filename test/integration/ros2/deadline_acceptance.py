"""Fixed deadlines + preemption: real ROS and native offline Player, no devices/API."""
import argparse
import json
from pathlib import Path
import queue
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
    from runtime.ipc.channel import call
    from GuideBot.gesture.catalog import Catalog
    from GuideBot.gesture.scheduler import Scheduler
    from runtime.ros2.nodes.common import ROOT

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
        scheduler.text('deadline-probe', '欢迎参观。')
        scheduler.playback('deadline-probe', origin)
        def add(action, start, end):
            plan = catalog.validate(dict(action=action, start_unit=0, arrival_unit=1,
                                         start_s=start, end_s=end), [0, 1], [])
            scheduler.add('deadline-probe', plan, scheduler.replies['deadline-probe'].units)
        add('greet_wave', 0., 8.)
        scheduler.tick()
        until = origin+3
        while shared.host({'op':'motion_status'})['state'] != 'running':
            assert time.monotonic() < until, 'First action never started'
            time.sleep(.02)
        # B becomes due while A is running; use the real cancel/result/idle path.
        b_start = time.monotonic()-origin
        b_end = b_start+5.
        add('present_left', b_start, b_end)
        scheduler.tick()
        deadline = origin+b_end+1
        while time.monotonic() < deadline:
            try:
                result = results.get(timeout=.05)
            except queue.Empty:
                continue
            scheduler.execution_result(result['job_id'], result['success'])
            if result['job_id'] == 'deadline-probe:1':
                assert result['success'], result
                break
        else:
            raise AssertionError('B execution result missing')
        commands = [e for e in events if e['kind']=='gesture.command']
        assert len(commands) == 2, events
        assert commands[-1]['end_monotonic'] == origin+b_end
        assert not any(e.get('execution_error') for e in events), events
        assert any(e.get('job_id')=='deadline-probe:0' and e.get('success') is False
                   for e in events if e['kind']=='gesture.execution_result'), events
        assert time.monotonic() <= origin+b_end, 'B finished after original deadline'
        # A late plan is discarded before it can send a goal.
        add('present_right', 0., .01)
        scheduler.tick()
        assert len([e for e in events if e['kind']=='gesture.command']) == 2
        assert any(e.get('reason')=='end_deadline_passed' for e in events)
        # A live but infeasible window must retain its typed rejection through
        # the real host IPC -> Motion result, rather than becoming RuntimeError.
        now = time.monotonic()
        executor.handle('gesture.command', dict(action='please_wait', job_id='timing-feedback',
            response_id='deadline-probe', start_monotonic=now,
            arrival_monotonic=now+.5, end_monotonic=now+.5))
        until = time.monotonic()+3
        while time.monotonic() < until:
            try:
                result = results.get(timeout=.05)
            except queue.Empty:
                continue
            if result['job_id'] == 'timing-feedback':
                assert not result['success']
                assert result['reason'] == 'insufficient_remaining_time', result
                break
        else:
            raise AssertionError('Typed timing rejection result missing')
        return dict(ok=True, checks=['native_preemption', 'cancel_result_then_idle',
            'fixed_deadline_preserved', 'B_completed_before_deadline', 'expired_plan_dropped',
            'typed_timing_rejection_through_IPC'], events=events)
    finally:
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
    runtime = LocalRuntime(offline=True, timing='immediate')
    native = proxy = None
    try:
        runtime.start()
        native = OfflineNative(runtime.root).start()
        proxy = ROSGestureService(runtime.root/'voice-session', catalog=Catalog(),
            execution_mode='simulation', root=runtime.root/'ipc', native_test_request=native.call)
        proxy.start()
        result = runtime.run('-m', 'test.integration.ros2.deadline_acceptance', '--probe', proxy.session_id,
                             check=False)
        (runtime.root/'deadline-probe.stdout').write_text(result.stdout)
        (runtime.root/'deadline-probe.stderr').write_text(result.stderr)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        # Bypass the Python feasibility check to exercise the native final gate.
        native.call({'序列':dict(sequence_name='deadline_reject', steps=[dict(
            type=Catalog().actions['present_right']['asset_type'],
            name='present_right', transition_ms=2000)]),
            'job_id':'native-deadline-reject', 'end_monotonic':time.monotonic()+.1})
        until = time.monotonic()+2
        while time.monotonic() < until:
            status = native.call({'状态':True})['status']
            execution = status.get('execution') or {}
            if execution.get('job_id') == 'native-deadline-reject':
                assert execution['state'] == 'rejected', execution
                assert status['state'] == 'idle'
                report['checks'].append('native_final_deadline_rejection')
                break
            time.sleep(.02)
        else:
            raise AssertionError('Native rejection missing')
        report.update(hardware=False, cloud=False, audio=False)
        evidence = runtime.root/'deadline-acceptance.json'
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
