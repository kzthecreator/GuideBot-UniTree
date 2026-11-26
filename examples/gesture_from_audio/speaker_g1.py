#!/usr/bin/env python3
"""Isolated SDK speaker process; started only after rehearsal Enter authorization."""
import argparse
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))


def play_file(path):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from GuideBot.conversation.playback import StreamingSpeaker
    audio,rate=sf.read(str(path),dtype='float32',always_2d=True)
    audio=audio.mean(axis=1)
    if rate!=24000:
        factor=math.gcd(rate,24000)
        audio=resample_poly(audio,24000//factor,rate//factor)
    pcm=(np.clip(audio,-1,1)*32767).astype('<i2').tobytes()
    stopping=threading.Event();drained=threading.Event();errors=[]
    def event(kind,**details):
        print(json.dumps(dict(event=kind,monotonic=time.monotonic(),**details),ensure_ascii=False),flush=True)
        if kind=='playback.drained_estimated':drained.set()
    def error(exc):
        errors.append(str(exc));event('playback.error',message=str(exc));stopping.set()
    def stop(signum,frame):stopping.set()
    previous={s:signal.signal(s,stop) for s in (signal.SIGINT,signal.SIGTERM)}
    speaker=StreamingSpeaker(stopping,error,gain=1.,on_event=event)
    try:
        if not speaker.start():raise RuntimeError('G1扬声器初始化失败')
        if stopping.is_set():return 130
        speaker.feed('rehearsal',pcm);speaker.finish('rehearsal')
        deadline=time.monotonic()+len(pcm)/48000+15
        while not drained.wait(.05):
            if errors:raise RuntimeError(errors[-1])
            if stopping.is_set():return 130
            if time.monotonic()>deadline:raise TimeoutError('G1音频发送超时')
        # No DAC completion callback exists. Preserve a short tail before PlayStop.
        stopping.wait(1.)
        if errors:raise RuntimeError(errors[-1])
        return 0
    finally:
        speaker.close()  # Production worker calls AudioClient.PlayStop.
        for s,handler in previous.items():signal.signal(s,handler)


class G1Speaker:
    def __init__(self):
        self.process=None;self.origin=None;self.started=threading.Event();self.error=None
        self.thread=None;self.error_log=None
    def start(self,audio,logdir):
        from GuideBot.runtime.environment import sdk_environment
        self.error_log=(logdir/'audio-stderr.log').open('w',encoding='utf-8')
        self.process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--audio',str(audio)],
            env=sdk_environment(),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=self.error_log,text=True,bufsize=1)
        self.thread=threading.Thread(target=self.read,args=(logdir/'audio-events.jsonl',),daemon=True)
        self.thread.start()
        deadline=time.monotonic()+15
        while not self.started.wait(.05):
            if self.process.poll() is not None or self.error:
                raise RuntimeError(self.error or 'G1扬声器子进程退出，检查audio-stderr.log')
            if time.monotonic()>deadline:raise TimeoutError('等待G1首次音频提交超时')
        return self.origin
    def read(self,path):
        with path.open('w',encoding='utf-8') as log:
            for line in self.process.stdout:
                log.write(line);log.flush()
                try:record=json.loads(line)
                except ValueError:continue
                if record.get('event')=='playback.started':
                    self.origin=record['monotonic'];self.started.set()
                if record.get('event')=='playback.error':self.error=record.get('message','SDK播放失败')
    def poll(self):return self.process.poll()
    @property
    def returncode(self):return self.process.returncode
    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill();self.process.wait(timeout=3)
        if self.thread is not None:self.thread.join(timeout=2)
        if self.error_log is not None:self.error_log.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio',type=Path,required=True)
    args=parser.parse_args()
    sys.exit(play_file(args.audio))
