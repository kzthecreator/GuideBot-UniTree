"""Matched offline GPU experiment: latest 5/10/15/20s vs full prefix.

Logical replay clock includes measured inference time and coalesces arrivals
while inference is busy. It does not model process/ROS IPC; validate the chosen
configuration through the real spawned worker separately. No devices or APIs.
"""
import argparse
import collections
import json
from pathlib import Path
import sys
import time
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from GuideBot.conversation.alignment.timestamps import MonotonicBackend, ResponseAlignment, text_units


def source(directory, rid=None):
    events = [json.loads(s) for s in (directory/'events.jsonl').read_text().splitlines()]
    if rid is None:
        rid = json.loads((directory/'provenance.json').read_text())['response_id']
        audio, rate = sf.read(directory/'reply.wav', dtype='int16')
    else:
        whole, rate = sf.read(directory/'speaker-16k.wav', dtype='int16')
        index = [json.loads(s) for s in (directory/'audio-index.jsonl').read_text().splitlines()]
        audio = np.concatenate([whole[e['sample_offset']:e['sample_offset']+e['samples']]
                                for e in index if e['track']=='speaker' and e.get('response_id')==rid])
    assert rate == 16000 and audio.ndim == 1
    events = [e for e in events if e.get('response_id')==rid]
    origin = next(e['elapsed'] for e in events if e['type']=='response.audio.delta')
    text_event = next(e for e in events if e['type']=='client.reply-text')
    text = text_event['message'].split('：',1)[1]
    deltas = [e for e in events if e['type']=='response.audio_transcript.delta']
    tape, end, seconds = [], 0, 0.
    pcm = audio.astype('<i2').tobytes()
    for event in events:
        if event['type']=='response.audio.delta':
            seconds += event['audio_bytes']/48000
            stop = min(len(pcm), round(seconds*rate)*2)
            tape.append((event['elapsed']-origin, 'audio', pcm[end:stop]))
            end = stop
    if deltas and all('delta' in e for e in deltas):
        tape += [(max(0,e['elapsed']-origin),'text_delta',e['delta']) for e in deltas]
        mode = 'recorded_deltas'
    else:
        mode = 'logged_full_text_only'
    tape.append((max(0,text_event['elapsed']-origin),'text',text))
    done = next(e for e in events if e['type']=='client.cloud-done')
    tape.append((done['elapsed']-origin,'done',None))
    playback = next(e['elapsed'] for e in events if e['type']=='client.playback.started')-origin
    return dict(response_id=rid, text=text, pcm=pcm, tape=sorted(tape,key=lambda x:x[0]),
                playback=playback, text_mode=mode)


def quantiles(values):
    return dict(zip(('min','p50','p95','max'),map(float,np.quantile(values,[0,.5,.95,1])))) if values else {}


def run(backend, case, window, reference):
    punctuation = window == 'punctuation'
    strict = window != 120 and not punctuation
    state = ResponseAlignment(case['response_id'], window=120. if punctuation else float(window), step=.5, tail=.1,
        resync_every=0., strict_window=strict, cursor_from_starts=strict,
        punctuation_window=punctuation)
    now, index, first, records = 0., 0, {}, []
    tape = case['tape']
    while index<len(tape) or state.due():
        if not state.due() and index<len(tape):
            now = max(now,tape[index][0])
        while index<len(tape) and tape[index][0]<=now:
            due, kind, value = tape[index]
            if kind=='audio': state.data.extend(value)
            elif kind=='text': state.set_text(value)
            elif kind=='text_delta': state.set_text(state.text+value)
            elif kind=='done': state.done=True
            index += 1
        if not state.due():
            continue
        backend.torch.manual_seed(1729)
        started = time.monotonic()
        event = state.update(backend)
        backend.torch.cuda.synchronize()
        elapsed = time.monotonic()-started
        now += elapsed
        event['replay_elapsed'] = now
        starts = event.pop('start_update',None)
        if starts:
            starts['replay_elapsed'] = now
            records.append(starts)
            for row in starts['anchors']:
                first.setdefault(row['index'],now)
        records.append(event)
        if state.done:
            break
    times = [e['profile']['update_seconds'] for e in records if e.get('profile',{}).get('inference_ran')]
    actual_windows = [e['profile']['window_seconds'] for e in records if e.get('profile',{}).get('inference_ran')]
    error = [abs(row['start']-reference[i]['start']) for i,row in state.latest_starts.items() if i in reference]
    lead = [case['playback']+row['start']-first[i] for i,row in reference.items() if i in first]
    warnings = collections.Counter(e.get('reason') for e in records if e['kind']=='alignment.warning')
    stats = dict(window_s=window, strict=strict, total_units=len(reference),
        covered=len(state.latest_starts), final_received=records[-1]['kind']=='alignment.final',
        start_difference_s=quantiles(error), compute_s=quantiles(times),
        max_actual_window_s=max(actual_windows), updates=len(times), warnings=dict(warnings),
        before_speech=sum(v>=0 for v in lead), half_second_early=sum(v>=.5 for v in lead),
        total_compute_s=sum(times), text_mode=case['text_mode'])
    stats['passes_accuracy_gate'] = (len(error)==len(reference) and stats['final_received']
        and stats['start_difference_s']['p95']<=.1 and stats['start_difference_s']['max']<=.3
        and not warnings.get('cursor_lost'))
    return stats,records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live-session', type=Path, required=True)
    parser.add_argument('--live-response', required=True)
    parser.add_argument('--long-data', type=Path, default=Path('recordings/long-reply'))
    parser.add_argument('--punctuation-only', action='store_true', help='Compare punctuation-boundary window and full prefix')
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    backend = MonotonicBackend(threads=1,reuse_predictor=True,device='cuda')
    backend.warmup()
    cases = [('long45',source(args.long_data)),('live102',source(args.live_session,args.live_response))]
    report = dict(clock='logical arrivals plus measured GPU inference; IPC excluded',
        seed=1729, reference='Same model full-utterance final alignment, not acoustic ground truth',
        gate=dict(p95_start_difference_s=.1,max_start_difference_s=.3,complete=True,no_cursor_loss=True), cases={})
    for name,case in cases:
        backend.torch.manual_seed(1729)
        rows,_ = backend.align(case['pcm'],text_units(case['text']),final=True)
        reference = {i:row for i,row in enumerate(rows)}
        (args.output/(name+'-reference.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2))
        report['cases'][name]=[]
        for window in (['punctuation',120] if args.punctuation_only else [5,10,15,20,120]):
            stats,events = run(backend,case,window,reference)
            report['cases'][name].append(stats)
            (args.output/(name+'-'+str(window)+'-events.jsonl')).write_text(
                ''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in events))
            (args.output/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print(json.dumps(dict(case=name,**stats),ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
