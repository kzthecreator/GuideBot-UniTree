"""Offline fresh-process streaming startup probe; no audio devices, API or robot."""
import argparse
import json
from pathlib import Path
import queue
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from GuideBot.conversation.alignment.timestamps import MonotonicBackend, StreamingTimestamps, text_units


def worker_probe(prefix, text, output):
    """Exercise actual spawn/start/ready/queue path with recorded PCM only."""
    from GuideBot.gesture.timing import ALIGNMENT_OPTIONS, BACKEND_OPTIONS
    events = queue.Queue()
    output.parent.mkdir(parents=True, exist_ok=True)
    directory = output.parent / (output.stem + '-worker')
    directory.mkdir(parents=True, exist_ok=True)
    worker = StreamingTimestamps(directory, lambda **event: events.put(event),
                                 alignment_options=ALIGNMENT_OPTIONS, backend_options=BACKEND_OPTIONS)
    started = time.monotonic()
    try:
        worker.start()
        ready = events.get(timeout=1)
        report = dict(ready=ready, startup_seconds=time.monotonic()-started, runs=[])
        started = time.monotonic()
        worker.send('text', 'offline-startup-probe', text)
        worker.send('audio', 'offline-startup-probe', prefix)
        until = time.monotonic()+15
        while time.monotonic() < until:
            event = events.get(timeout=15)
            if event['kind'] in {'alignment.error', 'alignment.warning'}:
                raise RuntimeError(str(event))
            if event['kind'] == 'alignment.update':
                report['runs'].append(dict(profile=event['profile'], rows=event['timestamps']))
                report['first_delivery_seconds'] = time.monotonic()-started
                return report
        raise RuntimeError('No streaming alignment update')
    finally:
        worker.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--warmup', action='store_true')
    parser.add_argument('--worker', action='store_true', help='Test production spawned worker readiness')
    parser.add_argument('--session', type=Path, required=True, help='Recorded session containing speaker-16k.wav and events.jsonl')
    parser.add_argument('--profile-predictor', action='store_true')
    parser.add_argument('--assert-first-under', type=float)
    args = parser.parse_args()
    directory = args.session
    # Use the exact first received prefix and final transcript from the incident.
    with wave.open(str(directory/'speaker-16k.wav'), 'rb') as audio:
        assert audio.getframerate() == 16000 and audio.getnchannels() == 1
        prefix = audio.readframes(9451)
    events = [json.loads(line) for line in (directory/'events.jsonl').read_text().splitlines()]
    text = next(e['transcript'] for e in events if e.get('type') == 'response.audio_transcript.done')
    if args.worker:
        report = worker_probe(prefix, text, args.output)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False))
        if args.assert_first_under is not None:
            assert report['first_delivery_seconds'] < args.assert_first_under, 'First worker delivery exceeded budget'
        return
    started = time.monotonic()
    backend = MonotonicBackend(threads=1, reuse_predictor=True)
    report = dict(device=str(backend.device), load_seconds=time.monotonic()-started, runs=[])
    if args.warmup:
        report['warmup'] = backend.warmup()
    hooks, layer_times = [], []
    if args.profile_predictor:
        def before(module, inputs):
            backend.torch.cuda.synchronize()
            module._probe_started = time.monotonic()
        def after(name):
            def record(module, inputs, output):
                backend.torch.cuda.synchronize()
                layer_times.append(dict(layer=name, seconds=time.monotonic()-module._probe_started))
            return record
        for name, module in backend.model.model.predictor.named_children():
            hooks.extend([module.register_forward_pre_hook(before), module.register_forward_hook(after(name))])
    for i in range(3):
        layer_times.clear()
        backend.torch.manual_seed(1729)
        rows, estimate = backend.align(prefix, text_units(text))
        if backend.device.type == 'cuda':
            backend.torch.cuda.synchronize()
        report['runs'].append(dict(repeat=i, profile=backend.last_profile,
                                   estimate=estimate, rows=rows, predictor_layers=list(layer_times)))
    for hook in hooks:
        hook.remove()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
    if args.assert_first_under is not None:
        assert report['runs'][0]['profile']['wall_seconds'] < args.assert_first_under, 'First real prefix exceeded budget'


if __name__ == '__main__':
    main()
