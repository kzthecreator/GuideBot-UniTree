"""Screen CPU threading and dynamic quantization on matched audio windows."""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from GuideBot.conversation.timestamps import MonotonicBackend, text_units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    audio, rate = sf.read('recordings/long-reply/reply.wav', dtype='int16')
    assert rate == 16000
    labels = text_units('测'*240)
    backend = MonotonicBackend(reuse_predictor=True)
    torch = backend.torch
    original = backend.model.model
    results = []
    for quantized in (False, True):
        if quantized:
            started = time.monotonic()
            backend.model.model = torch.ao.quantization.quantize_dynamic(
                original, {torch.nn.Linear, torch.nn.LSTM}, dtype=torch.qint8, inplace=False)
            print('quantization_seconds', time.monotonic()-started, flush=True)
        for threads in (1, 2, 4):
            torch.set_num_threads(threads)
            for repeat in range(3):
                for end in (1., 4., 8.):
                    torch.manual_seed(1729)
                    rows, estimate = backend.align(audio[:round(end*rate)].astype('<i2').tobytes(), labels)
                    results.append(dict(quantized=quantized, threads=threads, repeat=repeat,
                                        duration=end, rows=rows, estimate=estimate,
                                        profile=dict(backend.last_profile)))
            selected = [r for r in results if r['quantized']==quantized and r['threads']==threads]
            print(json.dumps(dict(quantized=quantized, threads=threads,
                                  median=statistics.median(r['profile']['wall_seconds'] for r in selected))), flush=True)
            (args.output/'results.json').write_text(json.dumps(results))


if __name__ == '__main__':
    main()
