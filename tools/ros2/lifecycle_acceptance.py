"""Local Foxy launch/session lifecycle with fake host resources; no cloud/audio/robot DDS."""
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from GuideBot.runtime.local_runtime import LocalRuntime
from GuideBot.runtime.ipc import Server
from GuideBot.runtime.launcher import session_control
from GuideBot.runtime.transport import ROSGestureService
from GuideBot.gesture.catalog import Catalog
from tools.ros2.offline_acceptance import until


def run(mode, fail=False, kill=False):
    runtime = LocalRuntime(offline=True, managed_test=True)
    sid = uuid.uuid4().hex
    operations = []
    proxy = None
    server = None
    def resource(request):
        nonlocal proxy
        assert request['session_id'] == sid and request['generation'] == 1
        op = request['op']
        operations.append(op)
        if op == 'activate':
            if fail:
                raise RuntimeError('injected resource failure')
            proxy = ROSGestureService(runtime.root/'voice-session', catalog=Catalog(),
                    execution_mode='simulation', root=runtime.root/'ipc', managed=True, session_id=sid)
            proxy.start()
        if op == 'deactivate' and proxy is not None:
            proxy.close()
        if op == 'health':
            return dict(active=proxy.running, failed=proxy.failed.is_set())
        return True
    try:
        runtime.start()
        server = Server(runtime.root/'ipc/resources.sock', resource)
        assert session_control(runtime.root,sid,'health',mode)['state'] == 'standby'
        assert not operations
        if fail:
            try:
                session_control(runtime.root,sid,'start',mode)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Failed resource activation was accepted')
            assert session_control(runtime.root,sid,'health',mode)['state'] == 'fault'
            assert 'deactivate' in operations
        else:
            assert session_control(runtime.root,sid,'start',mode)['state'] == 'active'
            until(lambda: 'heartbeat' in operations)
            if kill:
                # Kill exactly the planner child process; launch must stop the graph.
                import signal
                runtime.signal_node('planner', signal.SIGTERM)
                until(lambda: proxy.failed.is_set(), seconds=10)
                assert proxy.error == 'ROS heartbeat expired'
            else:
                assert session_control(runtime.root,sid,'stop',mode)['state'] == 'standby'
                assert not proxy.running
        report = dict(ok=True, mode=mode, startup_failure=fail, node_exit=kill,
                      operations=operations, hardware=False, cloud=False)
        (runtime.root/'lifecycle-acceptance.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(dict(ok=True,evidence=str(runtime.root/'lifecycle-acceptance.json'))),flush=True)
    finally:
        if proxy:
            proxy.close()
        if server:
            server.close()
        runtime.stop()


if __name__ == '__main__':
    run('voice')
    run('simulation')
    run('voice', fail=True)
    run('voice', kill=True)
