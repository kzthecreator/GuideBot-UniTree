"""Replay normal-speech complaints with controlled front-end alternatives."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'GuideBot/conversation'))
from audio import save_wav
from localvqe import LocalVQEEcho, installation
from agc import AGC2
from compare_frontends import read

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('source',type=Path);parser.add_argument('output',type=Path)
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
raw=read(args.source/'microphone-16k.wav');far=read(args.source/'speaker-16k.wav')
timeline=[]
for line in (args.source/'audio-index.jsonl').read_text().splitlines():
    r=json.loads(line)
    if r['track'] in {'microphone','speaker'}:timeline.append((r.get('rpc_finished_elapsed',r['elapsed']),r))
for line in (args.source/'events.jsonl').read_text().splitlines():
    e=json.loads(line)
    if e['type']=='client.playback.stopped':timeline.append((e['elapsed'],dict(track='stop',elapsed=e['elapsed'])))
results={}
for label,gain,model in [('v12-input6db',6,'localvqe-v1.2-1.3M-f32.gguf'),
                         ('v12-input12db',12,'localvqe-v1.2-1.3M-f32.gguf'),
                         ('v14-aec200',0,'localvqe-v1.4-aec-200K-f32.gguf')]:
    echo=LocalVQEEcho(model=installation()/'models'/model);agc=AGC2();frames=[];clipped=0
    try:
        for _,r in sorted(timeline,key=lambda row:row[0]):
            a,b=r.get('sample_offset',0)*2,(r.get('sample_offset',0)+r.get('samples',0))*2
            if r['track']=='speaker' and r.get('code')==0:echo.add_reference(far[a:b],r['elapsed'])
            elif r['track']=='stop':echo.stop_reference(r['elapsed'])
            elif r['track']=='microphone':
                x=np.frombuffer(raw[a:b],dtype='<i2').astype(float)*10**(gain/20)
                clipped+=int(np.sum(np.abs(x)>32767))
                frames.append(echo.process(np.clip(np.rint(x),-32768,32767).astype('<i2').tobytes(),r['elapsed']))
        output=b''.join(frames);save_wav(args.output/(label+'.wav'),output)
        final=agc.process(output)
        save_wav(args.output/(label+'-agc.wav'),final)
        results[label]=dict(input_clipped_samples=clipped,localvqe=dict(echo.stats))
        for name,data in [('model',output),('agc',final)]:
            x=np.frombuffer(data,dtype='<i2').astype(float)/32768
            results[label][name]={}
            for region,a,b in [('partial',17,20),('suppressed',26,28),('loud',32,34)]:
                y=x[a*16000:b*16000];results[label][name][region]=float(20*np.log10(max(np.sqrt(np.mean(y*y)),1e-12)))
        print(label,results[label],flush=True)
    finally:echo.close();agc.close()
    (args.output/'probe.json').write_text(json.dumps(results,indent=2))
