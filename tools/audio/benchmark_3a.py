"""Benchmark the chosen 16 ms LocalVQE + AGC2 pipeline, with no devices."""
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'GuideBot/conversation'))
from drivers.localvqe.runtime import Processor
from drivers.agc2.runtime import AGC2
from compare_frontends import read

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('case',type=Path)
args=parser.parse_args()
x=np.frombuffer(read(args.case/'raw.wav'),dtype='<i2')
ref=np.frombuffer(read(args.case/'far-reference.wav'),dtype='<i2')
report={}
for threads in (1,2,4):
    processor=Processor(threads=threads); agc=AGC2(); hops=[]
    try:
        for i in range(0,len(x)-255,256):
            began=time.perf_counter()
            enhanced=processor.process(x[i:i+256],ref[i:i+256],streaming=True)
            agc.process(enhanced.tobytes())
            hops.append((time.perf_counter()-began)*1000)
        report[str(threads)]=dict(p50_ms=float(np.percentile(hops,50)),p99_ms=float(np.percentile(hops,99)),
            max_ms=max(hops),over_16ms=int(np.sum(np.asarray(hops)>16)),hops=len(hops),
            audio_seconds=len(x)/16000,compute_seconds=sum(hops)/1000)
    finally:
        processor.close(); agc.close()
    print(threads,report[str(threads)],flush=True)
(args.case.parent/'benchmark.json').write_text(json.dumps(report,indent=2))
