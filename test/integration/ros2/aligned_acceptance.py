"""Offline alignment-to-ROS acceptance, optionally using the real local FP32 model."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from GuideBot.gesture.catalog import Catalog, units_for
from runtime.ipc.transport import ROSGestureService
from test.integration.ros2.offline_acceptance import until
from runtime.app.local_runtime import LocalRuntime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-aligner', action='store_true')
    args = parser.parse_args()
    model_evidence = None
    aligner = None
    runtime = LocalRuntime(offline=True,timing='aligned')
    proxy = None
    events = []
    try:
        runtime.start()
        proxy = ROSGestureService(runtime.root/'voice-session',
                    lambda kind,**details:events.append(dict(kind=kind,**details)),
                    catalog=Catalog(),execution_mode='simulation',root=runtime.root/'ipc')
        proxy.start()
        text = '欢迎参观。'
        proxy.submit('text','aligned',text=text)
        proxy.submit('done','aligned')
        until(lambda:any(e['kind']=='gesture.planned' for e in events))
        anchors = [dict(index=u['unit_id'],text=u['text'],text_offset=u['text_offset'],start=.2+i*.8)
                   for i,u in enumerate(units_for(text))]
        if args.real_aligner:
            import wave
            from GuideBot.conversation.alignment.timestamps import StreamingTimestamps, text_units
            from GuideBot.gesture.timing import BACKEND_OPTIONS, ALIGNMENT_OPTIONS
            assert BACKEND_OPTIONS['quantized'] is False
            with wave.open('recordings/long-reply/reply.wav', 'rb') as audio:
                assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000,1,2)
                pcm = audio.readframes(6*16000)
            alignment_events = []
            aligner = StreamingTimestamps(runtime.root/'session',
                lambda kind, **details: alignment_events.append(dict(kind=kind, **details)),
                alignment_options=ALIGNMENT_OPTIONS, backend_options=BACKEND_OPTIONS)
            aligner.start()
            aligner.send('text', 'aligned', text)
            aligner.send('audio', 'aligned', pcm)
            aligner.send('done', 'aligned')
            until(lambda: any(e['kind']=='alignment.final' for e in alignment_events), seconds=60)
            final = next(e for e in alignment_events if e['kind']=='alignment.final')
            assert not any(e['kind'] in {'alignment.error','alignment.warning'} for e in alignment_events)
            rows = final['timestamps']
            assert len(rows) == len(text_units(text))
            anchors = [dict(index=i,text=row['text'],text_offset=row['text_offset'],start=row['start'])
                       for i,row in enumerate(rows)]
            model_evidence = dict(backend_options=BACKEND_OPTIONS,profile=final['profile'],events=alignment_events,
                                  rows=rows, note='Control labels; verifies transport, not alignment accuracy')
        proxy.submit('alignment','aligned',version=2,anchors=anchors)
        proxy.submit('playback','aligned',origin=time.monotonic()+1)
        # Older revisions cannot replace the current anchor set.
        proxy.submit('alignment','aligned',version=1,anchors=[])
        until(lambda:any(e['kind']=='gesture.execution_result' and e.get('success') for e in events))
        commands = [e for e in events if e['kind']=='gesture.command']
        assert len(commands)==1 and commands[0]['alignment_version']==2
        proxy.close()
        proxy = None
        (runtime.root/'aligned-acceptance.json').write_text(json.dumps(dict(ok=True,events=events,model=model_evidence),
                                                            ensure_ascii=False,indent=2))
        print(json.dumps(dict(ok=True,evidence=str(runtime.root/'aligned-acceptance.json'))))
    finally:
        if aligner:
            aligner.close()
        if proxy:
            proxy.close()
        runtime.stop()


if __name__=='__main__':
    main()
