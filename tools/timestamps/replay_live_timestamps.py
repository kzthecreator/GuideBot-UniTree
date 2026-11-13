"""Wall-clock replay through production process; no microphone, SDK, or cloud."""
import json
import os
from pathlib import Path
import sys
import threading
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'GuideBot/conversation'))
from timestamps import StreamingTimestamps

ROOT=Path(os.environ.get('GUIDEBOT_ALIGNMENT_DATA', Path.home()/'.local/state/guidebot/conversation/phrase-alignment/f1b32726-cda0-453a-8c76-ed204c6acb0f'))
OUT=ROOT/'live-replay-validated'


def main():
    OUT.mkdir(exist_ok=True)
    source=Path(json.loads((ROOT/'provenance.json').read_text())['source'])
    events=[json.loads(s) for s in (source/'events.jsonl').read_text().splitlines()]
    events=[e for e in events if e.get('response_id')==ROOT.name]
    deltas=[e for e in events if e['type']=='response.audio.delta']
    origin=deltas[0]['elapsed']
    text=next(e for e in events if e['type']=='client.reply-text')
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
        elif kind!='alignment.ready':
            print(kind,details,flush=True)
        if kind=='alignment.final' and details['response_id']==ROOT.name:
            final_ready.set()
    worker=StreamingTimestamps(OUT,receive)
    try:
        worker.start()
        clock[0]=time.monotonic()
        actions=[]
        for delta in deltas:
            actions.append((delta['elapsed']-origin,'audio',delta['audio_bytes']))
        actions.append((max(0,text['elapsed']-origin),'text',text['message'].split('：',1)[1]))
        done=next(e for e in events if e['type']=='client.cloud-done')
        actions.append((done['elapsed']-origin,'done',None))
        offset=0
        seconds=0.
        for due,action,payload in sorted(actions,key=lambda a:a[0]):
            while time.monotonic()-clock[0]<due:
                time.sleep(min(.02,due-(time.monotonic()-clock[0])))
            if action=='audio':
                seconds+=payload/48000
                end=min(len(stream),round(seconds*rate)*2)
                worker.send('audio',ROOT.name,stream[offset:end])
                offset=end
            else:
                worker.send(action,ROOT.name,payload)
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
    summary=dict(updates=len(updates),final_units=len(final['timestamps']),total_units=final['total_units'],
                 final_ready_seconds=final['replay_elapsed'],
                 compute_seconds=[e['compute_seconds'] for e in updates],
                 max_recent_window=max(e['window_seconds'] for e in updates if e['scope']=='recent_window'),
                 prefix_resyncs=sum(e['scope']=='prefix_resync' for e in updates),
                 unordered_updates=sum(not e['ordered'] for e in updates),
                 warnings=[e for e in records if e['kind'] in {'alignment.warning','alignment.error'}],
                 total_revisions=sum(len(e.get('changes',[])) for e in records),
                 max_revision_ms=max((c['shift_ms'] for e in records for c in e.get('changes',[])),default=0),
                 cancelled_response_suppressed=True,worker_stopped=not worker.process.is_alive())
    assert summary['final_units']==summary['total_units']==197
    assert summary['updates']>1 and summary['worker_stopped']
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
