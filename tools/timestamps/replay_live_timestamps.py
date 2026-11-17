"""Wall-clock replay through production process; no microphone, SDK, or cloud."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'GuideBot/conversation'))
from timestamps import StreamingTimestamps, text_units

ROOT=Path(os.environ.get('GUIDEBOT_ALIGNMENT_DATA', Path.home()/'.local/state/guidebot/conversation/phrase-alignment/f1b32726-cda0-453a-8c76-ed204c6acb0f'))
OUT=ROOT/'live-replay-validated'


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--window', type=float, default=6.)
    parser.add_argument('--step', type=float, default=2.)
    parser.add_argument('--tail', type=float, default=1.)
    parser.add_argument('--resync-every', type=float, default=10.)
    parser.add_argument('--response-id', help='Replay one completed live-session reply')
    parser.add_argument('--synthetic-text-deltas', action='store_true',
                        help='Distribute final text over logged delta times; not historical text replay')
    args=parser.parse_args()
    OUT=args.output
    OUT.mkdir(parents=True,exist_ok=True)
    provenance=(dict(source=str(ROOT), response_id=args.response_id) if args.response_id else
                json.loads((ROOT/'provenance.json').read_text()))
    response_id=provenance.get('response_id', ROOT.name)
    source=Path(provenance['source'])
    events=[json.loads(s) for s in (source/'events.jsonl').read_text().splitlines()]
    events=[e for e in events if e.get('response_id')==response_id]
    deltas=[e for e in events if e['type']=='response.audio.delta']
    origin=deltas[0]['elapsed']
    text=next(e for e in events if e['type']=='client.reply-text')
    if args.response_id:
        audio,rate=sf.read(ROOT/'speaker-16k.wav',dtype='int16')
        index=[json.loads(s) for s in (ROOT/'audio-index.jsonl').read_text().splitlines()]
        audio=np.concatenate([audio[e['sample_offset']:e['sample_offset']+e['samples']]
                              for e in index if e['track']=='speaker' and e.get('response_id')==response_id])
    else:
        audio,rate=sf.read(ROOT/'reply.wav',dtype='int16')
    stream=audio.astype('<i2').tobytes()
    records=[]
    final_ready=threading.Event()
    clock=[None]
    def receive(kind,**details):
        elapsed=time.monotonic()-clock[0] if clock[0] is not None else None
        records.append(dict(kind=kind,replay_elapsed=elapsed,**details))
        if kind in {'alignment.update','alignment.final'}:
            print(kind,'units',len(details['timestamps']),'compute',round(details['compute_seconds'],3),
                  'revisions',len(details['changes']),'ordered',details['ordered'],flush=True)
        elif kind=='alignment.starts':
            print(kind,'anchors',len(details['anchors']),flush=True)
        elif kind!='alignment.ready':
            print(kind,details,flush=True)
        if kind=='alignment.final' and details['response_id']==response_id:
            final_ready.set()
    options=dict(window=args.window, step=args.step, tail=args.tail, resync_every=args.resync_every)
    worker=StreamingTimestamps(OUT,receive,alignment_options=options)
    try:
        worker.start()
        clock[0]=time.monotonic()
        actions=[]
        for delta in deltas:
            actions.append((delta['elapsed']-origin,'audio',delta['audio_bytes']))
        transcript=text['message'].split('：',1)[1]
        if args.synthetic_text_deltas:
            text_events=[e for e in events if e['type']=='response.audio_transcript.delta']
            boundaries=np.linspace(0,len(transcript),len(text_events)+1,dtype=int)
            for i,event in enumerate(text_events):
                actions.append((max(0,event['elapsed']-origin),'text_delta',
                                transcript[boundaries[i]:boundaries[i+1]]))
        actions.append((max(0,text['elapsed']-origin),'text',transcript))
        done=next(e for e in events if e['type']=='client.cloud-done')
        if 'completed' not in done['message']:
            raise ValueError('This replay requires a completed response; do not repair interrupted audio')
        actions.append((done['elapsed']-origin,'done',None))
        offset=0
        seconds=0.
        for due,action,payload in sorted(actions,key=lambda a:a[0]):
            while time.monotonic()-clock[0]<due:
                time.sleep(min(.02,due-(time.monotonic()-clock[0])))
            if action=='audio':
                seconds+=payload/48000
                end=min(len(stream),round(seconds*rate)*2)
                worker.send('audio',response_id,stream[offset:end])
                offset=end
            else:
                worker.send(action,response_id,payload)
        if not final_ready.wait(20):
            raise RuntimeError('No complete-response repair received')
        # Exercise cancellation through the same actual child process.
        before=len(records)
        worker.send('text','cancel-test','你好世界')
        worker.send('audio','cancel-test',stream[:4*32000])
        worker.send('cancel','cancel-test')
        worker.send('done','cancel-test')
        time.sleep(1)
        assert not any(e.get('response_id')=='cancel-test' for e in records[before:])
    finally:
        worker.close()
        (OUT/'events.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in records))
    final=next(e for e in records if e['kind']=='alignment.final')
    updates=[e for e in records if e['kind']=='alignment.update']
    summary=dict(text_mode='synthetic_deltas' if args.synthetic_text_deltas else 'logged_final_text',
                 alignment_options=options,updates=len(updates),final_units=len(final['timestamps']),total_units=final['total_units'],
                 final_ready_seconds=final['replay_elapsed'],
                 compute_seconds=[e['compute_seconds'] for e in updates],
                 max_recent_window=max(e['window_seconds'] for e in updates if e['scope']=='recent_window'),
                 prefix_resyncs=sum(e['scope']=='prefix_resync' for e in updates),
                 unordered_updates=sum(not e['ordered'] for e in updates),
                 warnings=[e for e in records if e['kind'] in {'alignment.warning','alignment.error'}],
                 total_revisions=sum(len(e.get('changes',[])) for e in records if e['kind']!='alignment.starts'),
                 max_revision_ms=max((c['shift_ms'] for e in records if e['kind']!='alignment.starts' for c in e.get('changes',[])),default=0),
                 cancelled_response_suppressed=True,worker_stopped=not worker.process.is_alive())
    assert summary['final_units']==summary['total_units']==len(text_units(text['message'].split('：',1)[1]))
    assert summary['updates']>1 and summary['worker_stopped']
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
