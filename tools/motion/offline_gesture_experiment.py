"""Experiment one: real C++ socket/player, synthetic assets, no DDS/audio/model calls.

Run from the repository root: python -m tools.motion.offline_gesture_experiment
The limits/approval below are TEST FIXTURES, not robot measurements or approvals.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

from GuideBot.gesture.catalog import Catalog, Plan, units_for
from GuideBot.gesture.scheduler import Scheduler
from GuideBot.gesture.execution import OfflineExecutor
from drivers.unitree_motion.client import request
from tools.motion.motion_library import catalog_entries, metadata_for, parse_motion

REPO = Path(__file__).resolve().parents[2]
BUILD = Path(os.environ.get('GUIDEBOT_MOTION_BUILD_DIR',
                             Path.home()/'.local/share/guidebot/deps/motion/build-reorganized'))


def wait_until(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.005)
    raise TimeoutError('Offline experiment condition timed out')


def fixture(root):
    """Write synthetic data only inside this isolated experiment directory."""
    root.mkdir(parents=True, exist_ok=True)
    metadata = root/'metadata'
    metadata.mkdir()
    catalog = REPO/'assets/motion/config/motion_catalog.json'
    entry = catalog_entries(catalog)['greet_open']
    path = root/'motions/reception/greet_open.dat'
    path.parent.mkdir(parents=True)
    path.write_text('3\n14\n' + ''.join('.3 ' + str(value) + ' ' + ' '.join(['0']*13) + '\n'
                                        for value in (.04, .06, .08)))
    points, errors, _ = parse_motion(path)
    if errors:
        raise ValueError(errors)
    meta = metadata_for(entry, path, points)
    meta.update(status='approved', verified_by='OFFLINE SYNTHETIC FIXTURE ONLY',
                verified_at='2026-11-21T00:00:00+08:00')
    meta['timing_profile'] = dict(phase_weights=dict(transition=1, core=2, hold=1),
                                  minimum_total_ms=900, frame_weights=[1, 1])
    (metadata/'greet_open.json').write_text(json.dumps(meta))
    limits = root/'OFFLINE_FIXTURE_LIMITS.json'
    limits.write_text(json.dumps(dict(schema_version=1, verified=True,
        verified_by='OFFLINE SYNTHETIC FIXTURE ONLY', verified_at=meta['verified_at'],
        joint_names=meta['joint_names'], min_rad=[-1]*14, max_rad=[1]*14)))
    return [str(BUILD/'motion_library_server'), '--offline-server',
            '--socket-name', 'guidebot_offline_' + uuid.uuid4().hex,
            '--catalog', str(catalog), '--dir', str(root/'motions'),
            '--poses', str(root/'poses'), '--metadata', str(metadata), '--limits', str(limits)]


def run_experiment(output):
    output = Path(output)
    args = fixture(output/'fixture')
    socket_name = '\0' + args[args.index('--socket-name')+1]
    events = []
    log_lock = threading.Lock()
    log = (output/'events.jsonl').open('w', encoding='utf-8')

    def emit(kind, **details):
        event = dict(kind=kind, monotonic=time.monotonic(), **details)
        with log_lock:
            events.append(event)
            log.write(json.dumps(event, ensure_ascii=False)+'\n')
            log.flush()

    server_log = (output/'server.log').open('w')
    process = subprocess.Popen(args, cwd=REPO, stdout=server_log, stderr=subprocess.STDOUT)
    executor = None
    def state():
        return request(socket_name, {'状态': True}, timeout=.25)['status']
    def ready():
        if process.poll() is not None:
            raise RuntimeError('Offline server exited; inspect server.log')
        try:
            return state()
        except OSError:
            return None
    def seen(kind, rid):
        with log_lock:
            return next((e for e in events if e['kind'] == kind and e.get('response_id') == rid), None)
    def command(rid, **overrides):
        now = time.monotonic()
        return dict(response_id=rid, job_id=rid+':0', action='wave', duration_s=1.,
                    start_monotonic=now+.05, arrival_monotonic=now+.3,
                    compressed=False, **overrides)
    checks = {}
    try:
        wait_until(ready)
        request(socket_name, {'接管': True})
        wait_until(lambda: state()['ownership'] == 'owned')
        executor = OfflineExecutor(socket_name, {'wave': dict(asset='greet_open', minimum_total_ms=900)}, emit)
        executor.start()
        scheduler = Scheduler(Catalog(), emit, executor=executor)
        text = '欢迎来到展示中心。'

        def schedule(rid):
            origin = time.monotonic()+.15
            scheduler.text(rid, text)
            scheduler.add(rid, Plan('wave', 0, 3, {'duration_s': 1.}), units_for(text))
            scheduler.alignment(rid, dict(version=1, anchors=[
                dict(index=i, start=start, text=units_for(text)[i]['text'],
                     text_offset=units_for(text)[i]['text_offset']) for i, start in [(0, .05), (3, .3)]]))
            scheduler.playback(rid, origin)
            wait_until(lambda: (scheduler.tick(), seen('gesture.command', rid))[1])

        schedule('nominal')
        running = wait_until(lambda: seen('execution.driver_running', 'nominal'))
        completed = wait_until(lambda: seen('execution.driver_completed', 'nominal'))
        receipt = completed['receipt']
        if abs(receipt['planned_seconds']-1.25) > 1e-6 or 'running_at' not in receipt:
            raise AssertionError('Missing start receipt or timing silently changed')
        scheduler.tick()
        if scheduler.active is not None:
            raise AssertionError('Driver completion did not release scheduler reservation')
        checks['scheduler_to_cpp_completed'] = True
        checks['requested_seconds'] = 1.25
        checks['observed_running_seconds'] = receipt['completed_at']-receipt['running_at']
        checks['dispatch_start_error_ms'] = (running['receipt']['running_at']-
            seen('gesture.command', 'nominal')['start_monotonic'])*1000

        schedule('interrupted')
        wait_until(lambda: seen('execution.driver_running', 'interrupted'))
        before = time.monotonic()
        scheduler.cancel('interrupted')
        wait_until(lambda: seen('execution.driver_cancelled', 'interrupted'))
        checks['cancel_to_idle_ms'] = (time.monotonic()-before)*1000
        if state()['checkpoint'] is not None:
            raise AssertionError('Interrupted reply retained a resumable checkpoint')
        executor.submit(command('interrupted'))
        wait_until(lambda: seen('execution.rejected', 'interrupted'))
        checks['late_old_reply_rejected'] = True

        for rid, changes, reason in [
            ('too_short', {'duration_s': .1}, 'below_minimum_duration'),
            ('unbound', {'action': 'point'}, 'unbound_action'),
            ('expired', {'start_monotonic': time.monotonic()-.2,
                         'arrival_monotonic': time.monotonic()+.3}, 'start_deadline_expired')]:
            job = command(rid)
            job.update(changes)
            executor.submit(job)
            event = wait_until(lambda: seen('execution.rejected', rid))
            if event['reason'] != reason:
                raise AssertionError(event)
            checks[rid] = True

        executor.submit(command('busy_source'))
        wait_until(lambda: seen('execution.driver_running', 'busy_source'))
        executor.submit(command('busy_rejected'))
        if wait_until(lambda: seen('execution.rejected', 'busy_rejected'))['reason'] != 'executor_busy':
            raise AssertionError('Busy job was queued')
        executor.cancel('busy_source')
        wait_until(lambda: seen('execution.driver_cancelled', 'busy_source'))
        checks['busy_rejected_without_queue'] = True

        schedule('cancel_before_start')
        scheduler.cancel('cancel_before_start')
        wait_until(lambda: seen('execution.cancelled', 'cancel_before_start'))
        if seen('execution.accepted', 'cancel_before_start'):
            raise AssertionError('Cancelled queued job reached server')
        checks['cancel_before_dispatch'] = True

        executor.submit(command('server_loss'))
        wait_until(lambda: seen('execution.driver_running', 'server_loss'))
        process.kill()
        process.wait(timeout=2)
        wait_until(lambda: seen('execution.fault', 'server_loss'))
        if not executor.failed or executor.submit(command('after_loss')):
            raise AssertionError('Faulted executor accepted new work')
        checks['connection_loss_fails_closed'] = True
        result = dict(experiment='offline-gesture-execution-v1', no_robot=True, no_audio=True,
                      synthetic_assets=True, checks=checks, server_args=args)
        (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result
    finally:
        try:
            if executor:
                executor.close()
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            server_log.close()
            log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
        default=Path.home()/'.local/state/guidebot/motion'/('offline-'+str(time.time_ns())))
    args = parser.parse_args()
    result = run_experiment(args.output)
    print(json.dumps(result['checks'], ensure_ascii=False, indent=2))
    print('Offline evidence:', args.output)


if __name__ == '__main__':
    main()
