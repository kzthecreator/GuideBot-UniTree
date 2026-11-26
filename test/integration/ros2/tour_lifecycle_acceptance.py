"""Real localhost ROS lifecycle with fake tour audio/cloud; no robot DDS or devices."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from runtime.app.local_runtime import LocalRuntime
from runtime.ipc.channel import Server, call
from runtime.app.launcher import session_control
from runtime.app.workers.voice import VoiceWorker


class FakeTourSession:
    def __init__(self):
        self.ready, self.stopping = threading.Event(), threading.Event()
        self.started = False
    def start(self):
        self.started = True
        self.ready.set()
    def stop(self):
        self.stopping.set()
        return dict(errors=[])
    def control(self, command, **fields):
        return dict(phase='NARRATING', interaction='LISTENING')


def run(fail_host=False):
    runtime = LocalRuntime(offline=True, managed_test=True)
    sid = uuid.uuid4().hex
    worker = server = None
    operations = []
    fake = FakeTourSession()
    try:
        with patch.dict(os.environ, {'GUIDEBOT_ROS_DOMAIN_ID': str(140+os.getpid()%50)}):
            runtime.start()
        (runtime.root/'session').mkdir(exist_ok=True)
        worker = VoiceWorker(dict(service='tour'), runtime.root, sid, {})
        def resource(request):
            operations.append(request['op'])
            return worker.rpc(request)
        server = Server(runtime.root/'ipc/resources.sock', resource)
        with patch('runtime.app.workers.voice.build_session', return_value=fake), \
                patch('runtime.app.workers.voice.MotionRuntime', side_effect=AssertionError('Tour acquired motion')):
            # Production authorization path, but every audio/cloud operation is fake.
            call(runtime.root/'ipc/resources.sock',dict(op='authorize',session_id=sid,generation=1))
            session_control(runtime.root,sid,'start','voice')
            deadline = time.monotonic()+8
            while operations.count('heartbeat') < 6:
                if worker.state != 'active':
                    state = session_control(runtime.root,sid,'health','voice')['state']
                    raise AssertionError('Tour stopped during ROS health checks: worker={}, ROS={}'.format(worker.state,state))
                if time.monotonic() >= deadline:
                    raise AssertionError('No sustained tour heartbeat')
                time.sleep(.05)
            status = call(runtime.root/'ipc/resources.sock',dict(op='tour',command='status',session_id=sid,generation=1))
            assert status['phase'] == 'NARRATING'
            if fail_host:
                worker.host_lifecycle.close()
                deadline = time.monotonic()+8
                while session_control(runtime.root,sid,'health','voice')['state'] != 'fault':
                    if time.monotonic() >= deadline:
                        raise AssertionError('Missing host heartbeat did not fail the session')
                    time.sleep(.05)
                assert 'host_heartbeat' in (runtime.root/'ros.log').read_text()
            else:
                session_control(runtime.root,sid,'stop','voice')
                # Retrying cleanup must not reject an already retired session.
                session_control(runtime.root,sid,'stop','voice')
            assert fake.stopping.is_set()
            report = dict(ok=True,host_loss=fail_host,heartbeats=operations.count('heartbeat'),hardware=False,cloud=False,
                          operations=operations)
            path = runtime.root/'tour-lifecycle-acceptance.json'
            path.write_text(json.dumps(report,indent=2))
            print(json.dumps(dict(ok=True,heartbeats=report['heartbeats'],evidence=str(path))))
    finally:
        if worker: worker.close()
        if server: server.close()
        runtime.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fail-host', action='store_true')
    run(parser.parse_args().fail_host)
