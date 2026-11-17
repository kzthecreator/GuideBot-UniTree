"""Measured wall-clock replay sweep, offline reference and causal audio preview.

The single-thread harness drains recorded arrivals after each inference, matching
latest-wins scheduling. It excludes process IPC; verify finalists in production.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from GuideBot.conversation.timestamps import MonotonicBackend, ResponseAlignment, text_units


def load_cases(root):
    cases = []
    for folder in ('live-session', 'long-reply'):
        source = root / folder
        events = [json.loads(s) for s in (source/'events.jsonl').read_text().splitlines()]
        audio, rate = sf.read(source/('speaker-16k.wav' if folder == 'live-session' else 'reply.wav'), dtype='int16')
        assert rate == 16000 and audio.ndim == 1
        for done in events:
            if done['type'] != 'client.cloud-done' or 'completed' not in done['message']:
                continue
            rid = done['response_id']
            rows = [e for e in events if e.get('response_id') == rid]
            deltas = [e for e in rows if e['type'] == 'response.audio.delta']
            if not deltas:
                continue
            origin = deltas[0]['elapsed']
            text_event = next(e for e in rows if e['type'] == 'client.reply-text')
            text = text_event['message'].split('：', 1)[1]
            playback = next(e['elapsed'] for e in rows if e['type'] == 'client.playback.started')-origin
            if folder == 'live-session':
                index = [json.loads(s) for s in (source/'audio-index.jsonl').read_text().splitlines()]
                pcm = np.concatenate([audio[e['sample_offset']:e['sample_offset']+e['samples']]
                                      for e in index if e['track'] == 'speaker' and e.get('response_id') == rid])
            else:
                pcm = audio
            tasks = [(e['elapsed']-origin, 'audio', e['audio_bytes']) for e in deltas]
            tasks += [(max(0., text_event['elapsed']-origin), 'text', text),
                      (done['elapsed']-origin, 'done', None)]
            cases.append(dict(name=f'{folder}-{len(text_units(text))}', rid=rid, audio=pcm,
                              text=text, playback=playback, tasks=sorted(tasks, key=lambda t:t[0])))
    return cases


def evaluate(case, events, reference):
    first = {}
    before_deadline = {}
    for event in events:
        for row in (event.get('start_update') or {}).get('anchors', []):
            first.setdefault(row['index'], dict(row, published=event['elapsed']-case['playback']))
            if event['elapsed']-case['playback'] <= reference[row['index']]['start']:
                before_deadline[row['index']] = row
    details = []
    arrivals, cumulative = [], 0.
    text_at = next(t for t, kind, _ in case['tasks'] if kind=='text')-case['playback']
    for at, kind, payload in case['tasks']:
        if kind == 'audio':
            cumulative += payload/48000
            arrivals.append((cumulative, at-case['playback']))
    for i, ref in enumerate(reference):
        row = first.get(i)
        duration = ref['end']-ref['start']
        error = abs(row['start']-ref['start']) if row else None
        ready = row is not None and row['published'] <= ref['start']
        accurate = row is not None and error <= duration+1e-6
        deadline_row = before_deadline.get(i)
        acoustic_at = next((at for length, at in arrivals if length >= ref['end']), float('inf'))
        details.append(dict(index=i, text=ref['text'], ref_start=ref['start'], ref_end=ref['end'],
                            duration=duration, predicted=row['start'] if row else None,
                            published=row['published'] if row else None, error=error,
                            accurate=accurate, ready=ready, passed=ready and accurate,
                            deadline_passed=deadline_row is not None and
                            abs(deadline_row['start']-ref['start']) <= duration+1e-6,
                            full_character_audio_margin=ref['start']-acoustic_at,
                            text_margin=ref['start']-text_at))
    profiles = [e['profile'] for e in events if e.get('profile', {}).get('inference_ran')]
    return dict(total=len(details), present=len(first), accurate=sum(r['accurate'] for r in details),
                ready=sum(r['ready'] for r in details), passed=sum(r['passed'] for r in details),
                deadline_passed=sum(r['deadline_passed'] for r in details),
                complete_character_available_before_start=sum(r['full_character_audio_margin']>=0 for r in details),
                after_opening_total=sum(r['ref_start'] >= 2 for r in details),
                after_opening_passed=sum(r['passed'] and r['ref_start'] >= 2 for r in details),
                median_compute=statistics.median(p['update_seconds'] for p in profiles) if profiles else None,
                max_error=max((r['error'] for r in details if r['error'] is not None), default=None),
                warnings=[e.get('reason') for e in events if e['kind']=='alignment.warning'], details=details)


def run(case, backend, options):
    state = ResponseAlignment(case['rid'], **options)
    pcm = case['audio'].astype('<i2').tobytes()
    events, position, offset, seconds = [], 0, 0, 0.
    started = time.monotonic()
    tasks = case['tasks']
    while True:
        elapsed = time.monotonic()-started
        while position < len(tasks) and tasks[position][0] <= elapsed:
            due, action, payload = tasks[position]
            position += 1
            if action == 'audio':
                seconds += payload/48000
                end = min(len(pcm), round(seconds*16000)*2)
                state.data.extend(pcm[offset:end])
                state.newest_audio_sent_at = started+due
                offset = end
            elif action == 'text':
                state.set_text(payload)
            else:
                state.done = True
        if state.due():
            event = state.update(backend)
            event['elapsed'] = time.monotonic()-started
            events.append(event)
            if state.done:
                break
        elif position < len(tasks):
            time.sleep(max(0., min(.01, tasks[position][0]-(time.monotonic()-started))))
        else:
            raise RuntimeError('Replay ended without terminal result')
    assert offset == len(pcm)
    return events


def preview(case, metrics, out, events=None):
    # Markers only occur when a boundary is actually known; speech is never held.
    audio = case['audio'].astype(np.float32)/32768
    marked = audio.copy()
    ideal = audio.copy()
    markers, pending, committed = [], {}, set()
    for event in events or []:
        now = event['elapsed']-case['playback']
        for index, row in list(pending.items()):
            if row['start'] <= now:
                markers.append(dict(index=index, text=row['text'], at=max(0.,row['start']), late=False))
                committed.add(index)
                del pending[index]
        update = event.get('start_update')
        if update is None:
            continue
        pending = {r['index']:r for r in update['anchors'] if r['index'] not in committed}
        for index, row in list(pending.items()):
            if row['start'] <= now:
                markers.append(dict(index=index, text=row['text'], at=max(0.,now), late=True))
                committed.add(index)
                del pending[index]
    markers += [dict(index=i, text=r['text'], at=max(0.,r['start']), late=False) for i,r in pending.items()]
    for marker in markers:
        at = marker['at']
        start = round(at*16000)
        size = min(480, len(audio)-start)
        if size > 0:
            t = np.arange(size)/16000
            tone = .12*np.sin(2*np.pi*1200*t)*np.sin(np.pi*np.arange(size)/size)**2
            marked[start:start+size] += tone
    sf.write(out/'realtime-markers.wav', np.clip(marked, -1, 1), 16000, subtype='PCM_16')
    for row in metrics.get('details', []):
        start = round(row['ref_start']*16000)
        size = min(480, len(audio)-start)
        if size > 0:
            t = np.arange(size)/16000
            ideal[start:start+size] += .12*np.sin(2*np.pi*1200*t)*np.sin(np.pi*np.arange(size)/size)**2
    sf.write(out/'reference-markers.wav', np.clip(ideal, -1, 1), 16000, subtype='PCM_16')
    sf.write(out/'original.wav', audio, 16000, subtype='PCM_16')
    (out/'markers.json').write_text(json.dumps(markers, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('recordings'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--configs', nargs='+', default=['baseline', 'reuse', 'tail100', 'window2', 'startcursor'])
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--count-offset', type=int, choices=(-2,-1,0,1), default=-1)
    parser.add_argument('--quantized', action='store_true')
    parser.add_argument('--onnx-encoder', type=Path)
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--rescore-only', action='store_true')
    parser.add_argument('--cases', nargs='*')
    args = parser.parse_args()
    if args.onnx_encoder and (args.quantized or not args.reference_root):
        parser.error('ONNX requires --reference-root and cannot be combined with --quantized')
    args.output.mkdir(parents=True, exist_ok=True)
    cases = load_cases(args.data)
    if args.cases:
        cases = [c for c in cases if c['name'] in args.cases]
    if args.rescore_only:
        summary = []
        for case in cases:
            reference = json.loads(((args.reference_root or args.output)/(case['name']+'-reference.json')).read_text())
            for path in sorted(args.output.glob(case['name']+'-*/events.json')):
                events = json.loads(path.read_text())
                metrics = evaluate(case, events, reference)
                (path.parent/'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
                preview(case, metrics, path.parent, events)
                summary.append(dict(run=path.parent.name, **{k:v for k,v in metrics.items() if k!='details'}))
        (args.output/'rescored.json').write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        return
    backend = MonotonicBackend(threads=args.threads, count_offset=args.count_offset)
    original_model = backend.model.model
    if args.onnx_encoder:
        if any(not (args.reference_root/(c['name']+'-reference.json')).is_file() for c in cases):
            parser.error('All offline references must exist before an ONNX replay')
        from tools.timestamps.onnx_encoder import attach
        attach(backend, args.onnx_encoder, args.threads)
    manifest = [dict(name=c['name'], response_id=c['rid'], playback_offset=c['playback'],
                     audio_seconds=len(c['audio'])/16000,
                     pcm_sha256=hashlib.sha256(c['audio'].astype('<i2').tobytes()).hexdigest(),
                     units=len(text_units(c['text'])), input_mode='recorded final text arrival; no delta bodies',
                     load_average=os.getloadavg()) for c in cases]
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2))
    configs = dict(baseline={}, reuse=dict(reuse=True), tail100=dict(reuse=True, tail=.1),
                   window2=dict(reuse=True, tail=.1, window=2.),
                   startcursor=dict(reuse=True, tail=.1, cursor_from_starts=True),
                   window2start=dict(reuse=True, tail=.1, window=2., cursor_from_starts=True),
                   window6=dict(reuse=True, tail=.1, window=6.),
                   prefix=dict(reuse=True, tail=.1, window=120.),
                   prefixfinal=dict(reuse=True, tail=.1, window=120., final_repair=True),
                   prefixsafe=dict(reuse=True, tail=.5, window=120., final_repair=True),
                   prefixbalanced=dict(reuse=True, tail=.25, window=120., final_repair=True),
                   prefixstable=dict(reuse=True, tail=1., window=120., final_repair=True),
                   tail0=dict(reuse=True, tail=0.))
    summary = []
    for case in cases:
        refpath = (args.reference_root or args.output)/(case['name']+'-reference.json')
        if refpath.exists():
            reference = json.loads(refpath.read_text())
        else:
            backend.model.model = original_model
            backend.torch.manual_seed(1729)
            reference, _ = backend.align(case['audio'].astype('<i2').tobytes(), text_units(case['text']), final=True)
            refpath.write_text(json.dumps(reference, ensure_ascii=False, indent=2))
        if args.quantized:
            if backend.model.model is original_model:
                backend.model.model = backend.torch.ao.quantization.quantize_dynamic(
                    original_model, {backend.torch.nn.Linear, backend.torch.nn.LSTM},
                    dtype=backend.torch.qint8, inplace=False)
        for name in args.configs:
            out = args.output/f'{case["name"]}-{name}'
            out.mkdir(exist_ok=True)
            options = dict(window=4., step=.5, tail=.25, resync_every=0., final_repair=False)
            changes = dict(configs[name])
            backend.reuse_predictor = changes.pop('reuse', False)
            options.update(changes)
            backend.torch.manual_seed(1729)
            events = run(case, backend, options)
            (out/'events.json').write_text(json.dumps(events, ensure_ascii=False))
            metrics = evaluate(case, events, reference)
            (out/'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
            preview(case, metrics, out, events)
            row = dict(case=case['name'], config=name, threads=args.threads, count_offset=args.count_offset, quantized=args.quantized,
                       onnx_encoder=str(args.onnx_encoder) if args.onnx_encoder else None, options=options,
                       **{k:v for k,v in metrics.items() if k!='details'})
            summary.append(row)
            (args.output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
            print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
