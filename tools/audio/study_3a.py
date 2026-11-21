"""Reproducible offline 3A sweep. Never opens audio devices or calls cloud APIs."""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
from scipy import signal
import webrtcvad

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'GuideBot/conversation'))
from audio import save_wav
from localvqe import LocalVQEEcho, Processor
from agc import AGC2
from compare_frontends import read

RATE = 16000
CONFIGS = {
    'agc-standard': dict(speed=3., noise_dbfs=-50., margin_db=20., ceiling_dbfs=-1.),
    'agc-slow': dict(speed=1., noise_dbfs=-50., margin_db=20., ceiling_dbfs=-1.),
    'agc-noise55': dict(speed=3., noise_dbfs=-55., margin_db=20., ceiling_dbfs=-1.),
    'agc-margin26': dict(speed=3., noise_dbfs=-50., margin_db=26., ceiling_dbfs=-1.),
    'agc-margin22': dict(speed=3., noise_dbfs=-50., margin_db=22., ceiling_dbfs=-1.),
    'agc-margin24': dict(speed=3., noise_dbfs=-50., margin_db=24., ceiling_dbfs=-1.),
    'agc-margin30': dict(speed=3., noise_dbfs=-50., margin_db=30., ceiling_dbfs=-1.),
    'agc-headroom3': dict(speed=3., noise_dbfs=-50., margin_db=20., ceiling_dbfs=-3.),
    'agc-headroom6': dict(speed=3., noise_dbfs=-50., margin_db=20., ceiling_dbfs=-6.),
    'agc-headroom9': dict(speed=3., noise_dbfs=-50., margin_db=20., ceiling_dbfs=-9.),
}


def pcm(x):
    return np.rint(np.clip(x, -1, 32767/32768)*32768).astype('<i2').tobytes()


def samples(data):
    return np.frombuffer(data, dtype='<i2').astype(float)/32768


def db(x):
    return float(20*np.log10(max(float(np.sqrt(np.mean(x*x))), 1e-12))) if len(x) else None


def vadmask(x):
    vad = webrtcvad.Vad(2)
    result = np.zeros(len(x), dtype=bool)
    for i in range(0, len(x)-319, 320):
        result[i:i+320] = vad.is_speech(pcm(x[i:i+320]), RATE)
    return result


def measurements(x, voice, background):
    voice, background = voice[:len(x)], background[:len(x)]
    blocks = [db(x[i:i+320]) for i in range(0, len(x)-319, 320) if np.all(voice[i:i+320])]
    a = np.asarray(blocks)
    return dict(seconds=len(x)/RATE, rms_dbfs=db(x), peak_dbfs=float(20*np.log10(max(np.max(np.abs(x)), 1e-12))),
        full_scale_samples=int(np.sum(np.abs(x)>=32767/32768)),
        above_minus1_samples=int(np.sum(np.abs(x)>10**(-1/20))),
        voice_candidate_rms_dbfs=db(x[voice]), background_candidate_rms_dbfs=db(x[background]),
        voiced_20ms_frames=len(a),
        recommended_frames=int(np.sum((a>=-31.7)&(a<=-23.9))),
        too_quiet_frames=int(np.sum(a < -37)), too_loud_frames=int(np.sum(a > -19.5)))


def apply_agc(data, options):
    engine = AGC2(**options)
    try:
        start = time.perf_counter()
        out = engine.process(data)
        if engine.pending:
            size = len(engine.pending)
            out += engine.process(bytes(320-size))[:size]
        return out, time.perf_counter()-start, dict(engine.stats)
    finally:
        engine.close()


def evaluate_case(root, label, raw, clean, voice, background, metadata, target=None):
    destination = root/label
    destination.mkdir(parents=True, exist_ok=True)
    result = dict(metadata=metadata, variants={})
    for name, data in [('raw', raw), ('v12-no-agc', clean)]:
        save_wav(destination/(name+'.wav'), data)
        result['variants'][name] = measurements(samples(data), voice, background)
    for name, settings in CONFIGS.items():
        out, elapsed, stats = apply_agc(clean, settings)
        save_wav(destination/(name+'.wav'), out)
        result['variants'][name] = dict(**measurements(samples(out), voice, background),
                                       agc_processing_seconds=elapsed, settings=settings,
                                       limiter_boundary_samples=stats['limiter_boundary_samples'])
    # Signal distortion/noise metric is reported only with known synthetic target.
    # Alignment uses future information FOR EVALUATION ONLY, not enhancement.
    if target is not None and np.any(target):
        for name in result['variants']:
            output = samples(read(destination/(name+'.wav')))
            corr = signal.correlate(output, target, method='fft')
            lags = signal.correlation_lags(len(output), len(target))
            allowed = np.abs(lags)<=8000
            lag = int(lags[allowed][np.argmax(np.abs(corr[allowed]))])
            if lag>=0:
                y, t = output[lag:], target[:len(output)-lag]
            else:
                y, t = output[:len(output)+lag], target[-lag:]
            alpha = float(np.dot(y,t)/max(np.dot(t,t),1e-20))
            desired = alpha*t
            score = float(10*np.log10(max(np.sum(desired**2),1e-20)/max(np.sum((y-desired)**2),1e-20)))
            result['variants'][name].update(synthetic_si_sdr_db=score, eval_alignment_ms=lag/16)
    (destination/'result.json').write_text(json.dumps(result,indent=2))
    print(label, {k: (round(v['rms_dbfs'],2), v['above_minus1_samples']) for k,v in result['variants'].items()}, flush=True)
    return result


def real_case(source):
    raw = read(source/'microphone-16k.wav')
    speaker = read(source/'speaker-16k.wav')
    timeline=[]
    for line in (source/'audio-index.jsonl').read_text().splitlines():
        r=json.loads(line)
        if r['track'] in {'microphone','speaker'}:
            timeline.append((r.get('rpc_finished_elapsed',r['elapsed']),r))
    for line in (source/'events.jsonl').read_text().splitlines():
        e=json.loads(line)
        if e['type']=='client.playback.stopped':
            timeline.append((e['elapsed'],dict(track='stop',elapsed=e['elapsed'])))
    echo=LocalVQEEcho(); frames=[]
    try:
        for _,r in sorted(timeline,key=lambda row:row[0]):
            a,b=r.get('sample_offset',0)*2,(r.get('sample_offset',0)+r.get('samples',0))*2
            if r['track']=='speaker' and r.get('code')==0: echo.add_reference(speaker[a:b],r['elapsed'])
            elif r['track']=='stop': echo.stop_reference(r['elapsed'])
            elif r['track']=='microphone': frames.append(echo.process(raw[a:b],r['elapsed']))
        return raw,b''.join(frames),dict(echo.stats)
    finally: echo.close()


def playback_mask(source, length):
    records=[json.loads(line) for line in (source/'audio-index.jsonl').read_text().splitlines()]
    events=[json.loads(line) for line in (source/'events.jsonl').read_text().splitlines()]
    timeline=[(r.get('rpc_finished_elapsed',r['elapsed']),r) for r in records if r['track']=='speaker' and r.get('code')==0]
    timeline += [(e['elapsed'],dict(track='stop',elapsed=e['elapsed'])) for e in events if e['type']=='client.playback.stopped']
    spans=[]; until=0.
    for _,r in sorted(timeline,key=lambda item:item[0]):
        if r['track']=='stop':
            spans=[(a,min(b,r['elapsed'])) for a,b in spans if a<r['elapsed']]
            until=r['elapsed']
        else:
            start=max(r['elapsed'],until); until=start+r['samples']/RATE
            spans.append((start,until))
    clock=np.zeros(length); until=None
    for r in records:
        if r['track']!='microphone': continue
        observed=r['elapsed']-r['samples']/RATE
        if until is None or abs(observed-until)>.25: until=observed
        a=r['sample_offset']; b=min(length,a+r['samples'])
        clock[a:b]=until+np.arange(b-a)/RATE
        until+=r['samples']/RATE
    result=np.zeros(length,dtype=bool)
    for a,b in spans: result |= (clock>=a)&(clock<=b+.2)
    return result


def normalize(x, level):
    return x*10**((level-db(x))/20)


def synthetic_cases(voice_source):
    speech=samples(read(voice_source)); n=12*RATE
    # Disjoint source excerpts: known TTS near speech and unrelated far speech.
    near=np.zeros(n); near[3*RATE:10*RATE]=np.resize(speech[:7*RATE],7*RATE)
    far=normalize(np.resize(speech[8*RATE:18*RATE],n),-22)
    impulse=np.zeros(RATE//2); impulse[1280]=.45; impulse[2240]=.18; impulse[3840]=-.09; impulse[6400]=.04
    echo=signal.fftconvolve(far,impulse)[:n]
    rng=np.random.default_rng(20261117)
    noise=signal.lfilter([1.], [1.,-.85],rng.standard_normal(n))
    for label,level,noiselevel,use_echo in [
        ('near-normal',-27.6,-60,False),('near-soft',-36,-60,False),
        ('near-loud',-22,-60,False),('noise-moderate',-27.6,-48,False),
        ('noise-hard',-27.6,-40,False),('doubletalk',-27.6,-52,True),
        ('doubletalk-soft',-36,-52,True),('echo-only',None,-55,True),
        ('competing-talker',-27.6,-52,False),('noise-only',None,-40,False),
        ('near-reverb',-27.6,-52,False),('doubletalk-reverb',-27.6,-52,True),
        ('impulsive-noise',-27.6,-52,False)]:
        target=near.copy()
        voice=vadmask(target)
        if level is not None: target=target*10**((level-db(target[voice]))/20)
        else: target[:]=0
        mic=target+normalize(noise,noiselevel)+(echo if use_echo else 0)
        if 'reverb' in label:
            room=np.zeros(RATE//2+1); room[0]=1.; room[800]=.3; room[1920]=.2; room[4000]=.12; room[8000]=.05
            mic=signal.fftconvolve(target,room)[:n]+normalize(noise,noiselevel)+(echo if use_echo else 0)
        if label == 'impulsive-noise':
            mic[4*RATE:4*RATE+16] += .8
        if label == 'competing-talker':
            mic += normalize(far, -32)  # Unreferenced visitor speech; no spatial cue.
        if level is None: voice[:]=False
        background=(np.arange(n)<2*RATE) | (np.arange(n)>11*RATE)
        yield label,pcm(mic),pcm(far if use_echo else np.zeros(n)),target,voice,background


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--real',type=Path,nargs='+',required=True)
    parser.add_argument('--voice-source',type=Path,required=True)
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    summary={}
    for source in args.real:
        label=source.name
        cache=args.output/label/'v12-no-agc.wav'
        if cache.exists(): raw,clean,stats=read(source/'microphone-16k.wav'),read(cache),{'cached':True}
        else: raw,clean,stats=real_case(source)
        length=min(len(raw),len(clean)); raw,clean=raw[:length],clean[:length]
        voice=vadmask(samples(raw))
        summary[label]=evaluate_case(args.output,label,raw,clean,voice,~voice,
            dict(source=str(source),vad='WebRTC mode 2 on raw; includes echo/other people, NOT target-human ground truth',localvqe=stats))
        playing=playback_mask(source,len(voice))
        for name,v in summary[label]['variants'].items():
            data=samples(read(args.output/label/(name+'.wav')))
            v['estimated_playback_rms_dbfs']=db(data[playing])
            v['idle_voice_candidate_rms_dbfs']=db(data[voice & ~playing])
            v['idle_background_candidate_rms_dbfs']=db(data[~voice & ~playing])
        (args.output/label/'result.json').write_text(json.dumps(summary[label],indent=2))
    for label,mic,far,target,voice,background in synthetic_cases(args.voice_source):
        destination=args.output/label; cache=destination/'v12-no-agc.wav'
        if cache.exists(): cleaned=read(cache)
        else:
            processor=Processor(); frames=[]
            try:
                x,r=np.frombuffer(mic,dtype='<i2'),np.frombuffer(far,dtype='<i2')
                for a in range(0,len(x),256):
                    size=min(256,len(x)-a)
                    frames.append(processor.process(np.pad(x[a:a+size],(0,256-size)),np.pad(r[a:a+size],(0,256-size)),streaming=True)[:size].tobytes())
                cleaned=b''.join(frames)
            finally: processor.close()
        summary[label]=evaluate_case(args.output,label,mic,cleaned,voice,background,
            dict(synthetic=True,seed=20261117,description='Known TTS target, colored noise, FIR echo; not real exhibition hall'),target=target)
        save_wav(destination/'target.wav',pcm(target)); save_wav(destination/'far-reference.wav',far)
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2))


if __name__=='__main__': main()
