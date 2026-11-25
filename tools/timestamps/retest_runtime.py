"""Matched offline timestamp regression; never opens cloud, audio devices or DDS."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from drivers.timestamps.runtime import MonotonicBackend, text_units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--audio', type=Path, default=Path('recordings/long-reply/reply.wav'))
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--six-only', action='store_true', help='Use 6 s from the first call; isolate prefix-history effects')
    parser.add_argument('--float32', action='store_true', help='Experimental control without dynamic INT8')
    args = parser.parse_args()
    with wave.open(str(args.audio), 'rb') as source:
        assert (source.getframerate(), source.getnchannels(), source.getsampwidth()) == (16000, 1, 2)
        pcm = source.readframes(16000*6)
    assert len(pcm) == 16000*6*2
    started = time.monotonic()
    backend = MonotonicBackend(threads=args.threads, reuse_predictor=True, quantized=not args.float32)
    torch = backend.torch
    training_before = backend.model.model.training
    report = dict(python=sys.version, executable=sys.executable,
        versions={name: importlib.metadata.version(name) for name in ('torch','torchaudio','funasr','numpy','scipy')},
        quantized=not args.float32, training_before=training_before, training_during=backend.model.model.training, 
        requested_threads=args.threads, effective_threads=torch.get_num_threads(),
        interop_threads=torch.get_num_interop_threads(), quantized_engine=torch.backends.quantized.engine,
        thread_environment={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')},
        model_load_seconds=time.monotonic()-started, audio_sha256=hashlib.sha256(pcm).hexdigest(),
        note='Fixed length-control labels; no evidence of text matching accuracy. No devices/cloud.', runs=[])
    labels = text_units('你好欢迎来到香洲创港中心请问有什么可以帮你')
    cases = [(6,False),(6,True)] if args.six_only else [(1,False),(4,False),(6,False),(6,True)]
    for duration, final in cases:
        for repeat in range(3):
            torch.manual_seed(1729)
            rows, estimate = backend.align(pcm[:duration*16000*2], labels, final=final)
            report['runs'].append(dict(duration=duration,final=final,repeat=repeat,rows=rows,
                estimate=estimate,profile=dict(backend.last_profile)))
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print(json.dumps(dict(duration=duration,final=final,repeat=repeat,
                seconds=backend.last_profile['wall_seconds'], units=len(rows))),flush=True)
    print('Evidence: '+str(args.output),flush=True)


if __name__ == '__main__':
    main()
