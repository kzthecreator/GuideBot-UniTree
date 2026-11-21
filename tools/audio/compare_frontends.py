"""Offline causal replay of recorded G1 packets; never records or plays audio."""
import argparse
import json
from pathlib import Path
import sys
import time
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'GuideBot/conversation'))
from audio import save_wav
from localvqe import LocalVQEEcho, installation
from agc import AGC2


def read(path):
    with wave.open(str(path)) as source:
        assert source.getframerate() == 16000 and source.getnchannels() == 1
        return source.readframes(source.getnframes())


def metrics(pcm):
    x = np.frombuffer(pcm, dtype='<i2').astype(float)
    return dict(seconds=len(x)/16000, rms_dbfs=float(20*np.log10(max(np.sqrt(np.mean(x*x)), 1e-9)/32768)),
                peak_dbfs=float(20*np.log10(max(np.max(np.abs(x)), 1e-9)/32768)),
                clipping_samples=int(np.sum(np.abs(x) >= 32767)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--agc-only', action='store_true')
    parser.add_argument('--skip-agc', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw = read(args.source/'microphone-16k.wav')
    speaker = read(args.source/'speaker-16k.wav')
    records = [json.loads(line) for line in (args.source/'audio-index.jsonl').read_text().splitlines()]
    # A reference becomes available only after its PlayStream RPC returns.
    timeline = [(r.get('rpc_finished_elapsed', r['elapsed']), r) for r in records
                if r['track'] in {'microphone', 'speaker'}]
    for line in (args.source/'events.jsonl').read_text().splitlines():
        event = json.loads(line)
        if event['type'] == 'client.playback.stopped':
            timeline.append((event['elapsed'], dict(track='stop', elapsed=event['elapsed'])))
    timeline.sort(key=lambda row: row[0])
    report = dict(source=str(args.source), threads=2, delay_ms=0, gate=False,
                  reference='Recorded successful PlayStream PCM, RPC availability and stop events; no DAC clock',
                  raw=metrics(raw), variants={})
    if args.agc_only:
        report = json.loads((args.output/'result.json').read_text())
    save_wav(args.output/'raw.wav', raw)
    for name in ('microphone-gated', 'microphone-uploaded'):
        source = args.source/f'{name}-16k.wav'
        if source.exists():
            save_wav(args.output/f'baseline-{name}.wav', read(source))
    for version, size in [('1.2', '1.3M'), ('1.3', '4.8M')]:
        label = f'v{version}-no-gate'
        target = args.output/f'{label}.wav'
        if not args.agc_only:
            echo = LocalVQEEcho(model=installation()/f'models/localvqe-v{version}-{size}-f32.gguf')
            frames, hops = [], []
            original = echo.processor.process

            def timed(*a, **kw):
                start = time.perf_counter()
                result = original(*a, **kw)
                hops.append((time.perf_counter()-start)*1000)
                return result

            echo.processor.process = timed
            try:
                for _, r in timeline:
                    start, end = r.get('sample_offset', 0)*2, (r.get('sample_offset', 0)+r.get('samples', 0))*2
                    if r['track'] == 'speaker' and r.get('code') == 0:
                        echo.add_reference(speaker[start:end], r['elapsed'])
                    elif r['track'] == 'stop':
                        echo.stop_reference(r['elapsed'])
                    elif r['track'] == 'microphone':
                        frames.append(echo.process(raw[start:end], r['elapsed']))
                pcm = b''.join(frames)
                save_wav(target, pcm)
                report['variants'][label] = dict(**metrics(pcm), **echo.stats,
                    hop_p50_ms=float(np.percentile(hops, 50)), hop_p99_ms=float(np.percentile(hops, 99)),
                    hops_over_16ms=int(np.sum(np.array(hops)>16)), hop_count=len(hops))
            finally:
                echo.close()
        else:
            pcm = read(target)
        (args.output/'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if args.skip_agc:
            print(label, report['variants'][label], flush=True)
            continue
        # Preserve 10 ms streaming framing and flush only the final partial frame.
        agc = AGC2()
        try:
            start = time.perf_counter()
            output = agc.process(pcm)
            if agc.pending:
                remaining = len(agc.pending)
                output += agc.process(bytes(320-remaining))[:remaining]
            elapsed = time.perf_counter()-start
        finally:
            agc.close()
        save_wav(args.output/f'{label}-agc2.wav', output)
        report['variants'][label+'-agc2'] = dict(**metrics(output), processing_seconds=elapsed,
            settings=dict(fixed_gain_db=0, adaptive=True, max_gain_change_db_per_second=3,
                          max_output_noise_level_dbfs=-50, initial_saturation_margin_db=24,
                          output_ceiling_dbfs=-1, other_enhancements=False))
        (args.output/'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(label, report['variants'], flush=True)


if __name__ == '__main__':
    main()
