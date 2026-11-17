"""Wall-clock PCM replay with FunASR and explicitly supplied cached plans."""
import json
from pathlib import Path
import threading
import time

import numpy as np
import soundfile as sf

from GuideBot.conversation.timestamps import StreamingTimestamps
from .catalog import strict_json, units_for
from .service import GestureService


class CachedPlanner:
    model = 'cached-manual-plans-NOT-live-LLM'

    def __init__(self, catalog, document):
        self.catalog, self.document = catalog, document

    def plan(self, payload, on_action, cancelled):
        count = 0
        for row in self.document['actions']:
            if cancelled.is_set():
                break
            if all(row[key] in payload['eligible_anchor_ids'] for key in ('start_unit', 'arrival_unit')):
                on_action(self.catalog.validate(row, payload['eligible_anchor_ids'], payload['targets']))
                count += 1
        return dict(model=self.model, valid_actions=count, invalid_actions=0)


def replay(args, catalog):
    source = args.data.resolve()
    if args.response_id:
        rid = args.response_id
    else:
        provenance = strict_json((source / 'provenance.json').read_text())
        rid = provenance['response_id']
    events = [json.loads(s) for s in (source / 'events.jsonl').read_text().splitlines()]
    events = [e for e in events if e.get('response_id') == rid]
    deltas = [e for e in events if e['type'] == 'response.audio.delta']
    origin = deltas[0]['elapsed']
    text_event = next(e for e in events if e['type'] == 'client.reply-text')
    text = text_event['message'].split('：', 1)[1]
    done = next(e for e in events if e['type'] == 'client.cloud-done')
    if 'completed' not in done['message']:
        raise ValueError('Replay only accepts completed replies; interrupted audio must not get final repair')
    playback = next(e['elapsed'] for e in events if e['type'] == 'client.playback.started') - origin
    if args.response_id:
        audio, rate = sf.read(source / 'speaker-16k.wav', dtype='int16')
        index = [json.loads(s) for s in (source / 'audio-index.jsonl').read_text().splitlines()]
        audio = np.concatenate([audio[e['sample_offset']:e['sample_offset']+e['samples']]
                                for e in index if e['track'] == 'speaker' and e.get('response_id') == rid])
    else:
        audio, rate = sf.read(source / 'reply.wav', dtype='int16')
    if rate != 16000:
        raise ValueError('Replay requires final 16kHz speaker PCM')
    document = strict_json(args.plans.read_text(encoding='utf-8'))
    if document['response_id'] != rid:
        raise ValueError('Cached plan response_id does not match recording')
    targets = document.get('targets', [])
    for row in document['actions']:
        catalog.validate(row, range(len(units_for(text))), targets)
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    service = GestureService(args.output, catalog=catalog,
                             planner=CachedPlanner(catalog, document), targets=targets)
    aligned = []
    final = threading.Event()
    clock = [None]
    def receive(kind, **details):
        aligned.append(dict(kind=kind, replay_elapsed=time.monotonic()-clock[0] if clock[0] else None, **details))
        if kind == 'alignment.starts':
            service.submit('alignment', **details)
        elif kind == 'alignment.final':
            final.set()
    options = dict(window=args.window, step=args.step, tail=args.tail,
                   cursor_from_starts=args.cursor_from_starts,
                   resync_every=args.resync_every, final_repair=not args.no_final_repair)
    if args.no_resync:
        options.update(resync_every=0., final_repair=False)
    backend_options = dict(reuse_predictor=args.reuse_predictor, threads=args.threads,
                           quantized=args.quantized, count_offset=args.count_offset)
    worker = StreamingTimestamps(args.output, receive, alignment_options=options, backend_options=backend_options)
    try:
        service.start()
        worker.start(timeout=300)
        clock[0] = time.monotonic()
        tasks = [(e['elapsed']-origin, 'audio', e['audio_bytes']) for e in deltas]
        tasks += [(max(0, text_event['elapsed']-origin), 'text', text),
                  (done['elapsed']-origin, 'done', None), (playback, 'playback', None)]
        pcm = audio.astype('<i2').tobytes()
        offset, seconds = 0, 0
        for due, action, payload in sorted(tasks, key=lambda t: t[0]):
            while time.monotonic()-clock[0] < due:
                time.sleep(min(.02, due-(time.monotonic()-clock[0])))
            if action == 'audio':
                seconds += payload/48000
                end = min(len(pcm), round(seconds*rate)*2)
                worker.send('audio', rid, pcm[offset:end])
                offset = end
            elif action == 'playback':
                service.submit('playback', rid, origin=clock[0]+playback)
            else:
                worker.send(action, rid, payload)
                service.submit(action, rid, **({'text': payload} if action == 'text' else {}))
        if offset != len(pcm):
            raise ValueError('Recorded PCM does not match cloud chunk sample accounting')
        if not final.wait(60):
            raise RuntimeError('No complete FunASR alignment received')
        end_at = clock[0]+playback+len(audio)/rate
        while time.monotonic() < end_at:
            time.sleep(min(.05, end_at-time.monotonic()))
        service.submit('cancel', rid, reason='estimated_playback_finished')
        time.sleep(.1)
    finally:
        worker.close()
        service.close()
        (args.output / 'alignment.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in aligned))
    gestures = [json.loads(s) for s in (args.output / 'gesture.jsonl').read_text().splitlines()]
    summary = dict(response_id=rid, text_mode='logged_final_text', planner='explicit_cached_plans_not_LLM',
                   alignment_options=options,
                   backend_options=backend_options,
                   replay_clock_monotonic=clock[0], playback_offset=playback,
                   audio_seconds=len(audio)/rate, simulated=True,
                   planned=sum(e['kind']=='gesture.planned' for e in gestures),
                   commands=sum(e['kind']=='gesture.command' for e in gestures),
                   compressed=sum(e['kind']=='gesture.command' and e['compressed'] for e in gestures),
                   skipped=[e for e in gestures if e['kind']=='gesture.skipped'],
                   errors=[e for e in gestures if e['kind']=='gesture.error' or 'error' in e])
    (args.output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
