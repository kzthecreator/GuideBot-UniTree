"""Offline CPU/CUDA timestamp comparison; never opens audio or robot devices."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from drivers.timestamps.runtime import MonotonicBackend, text_units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', choices=('cpu', 'cuda'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data', type=Path, default=Path('recordings/long-reply'))
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    audio, rate = sf.read(args.data / 'reply.wav', dtype='int16')
    if rate != 16000 or audio.ndim != 1:
        parser.error('Expected mono 16kHz audio')
    provenance = json.loads((args.data / 'provenance.json').read_text())
    events = [json.loads(line) for line in (args.data / 'events.jsonl').read_text().splitlines()]
    event = next(e for e in events if e['type'] == 'client.reply-text'
                 and e.get('response_id') == provenance['response_id'])
    labels = text_units(event['message'].split('：', 1)[1])
    started = time.monotonic()
    backend = MonotonicBackend(threads=1, reuse_predictor=True, device=args.device)
    backend.model.model.eval()
    torch = backend.torch

    def sync():
        if args.device == 'cuda':
            torch.cuda.synchronize()

    sync()
    report = dict(device=args.device, torch=torch.__version__, cuda=torch.version.cuda,
                  model_load_seconds=time.monotonic() - started,
                  audio_sha256=hashlib.sha256((args.data / 'reply.wav').read_bytes()).hexdigest(),
                  frontend_dither=backend.model.kwargs['frontend'].dither, results=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for duration, final in ((1., False), (4., False), (8., False),
                            (16., False), (len(audio)/rate, True)):
        pcm = audio[:round(duration*rate)].astype('<i2').tobytes()
        times = []
        for repeat in range(args.repeats + 1):
            torch.manual_seed(1729)
            sync()
            started = time.monotonic()
            rows, estimate = backend.align(pcm, labels, final=final)
            sync()
            elapsed = time.monotonic() - started
            if repeat:
                times.append(elapsed)
            report['results'].append(dict(duration=duration, final=final, repeat=repeat,
                                          warmup=repeat == 0, seconds=elapsed,
                                          estimate=estimate, rows=rows))
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(dict(duration=duration, final=final,
                              median_seconds=statistics.median(times))), flush=True)
    if args.device == 'cuda':
        report['peak_cuda_allocated_bytes'] = torch.cuda.max_memory_allocated()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
