"""Paired CPU checks for same-window predictor reuse; no audio device or cloud."""
import argparse
import json
from pathlib import Path
import statistics
import sys

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from GuideBot.conversation.timestamps import MonotonicBackend, text_units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('recordings/long-reply'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 10:
        parser.error('--repeats must be in [1,10]')
    args.output.mkdir(parents=True, exist_ok=True)
    audio, rate = sf.read(args.data/'reply.wav', dtype='int16')
    if rate != 16000 or audio.ndim != 1:
        parser.error('Expected mono 16kHz PCM')
    provenance = json.loads((args.data/'provenance.json').read_text())
    events = [json.loads(s) for s in (args.data/'events.jsonl').read_text().splitlines()]
    event = next(e for e in events if e['type'] == 'client.reply-text' and
                 e.get('response_id') == provenance['response_id'])
    labels = text_units(event['message'].split('：', 1)[1])
    backend = MonotonicBackend(reuse_predictor=True)
    backend.model.model.eval()
    backend.torch.manual_seed(1729)
    backend.align(audio[:16000].astype('<i2').tobytes(), labels)
    results = []
    for repeat in range(args.repeats):
        for window_id, (begin, end) in enumerate([(0, .59), (0, 3.86), (1.63, 5.71),
                                                 (3.2, 7.54), (8., 12.75)]):
            pcm = audio[round(begin*rate):round(end*rate)].astype('<i2').tobytes()
            pairs = {}
            for reuse in ((False, True) if (repeat+window_id) % 2 == 0 else (True, False)):
                # Frontend dither may be nonzero: compare identical random input.
                backend.torch.manual_seed(1729+repeat+window_id)
                backend.reuse_predictor = reuse
                rows, estimate = backend.align(pcm, labels)
                pairs[reuse] = (rows, estimate)
                results.append(dict(repeat=repeat, window_id=window_id, begin=begin, end=end,
                                    reuse_predictor=reuse, profile=dict(backend.last_profile)))
            if pairs[False] != pairs[True]:
                raise AssertionError(f'Output mismatch at repeat {repeat}, window {window_id}')
            (args.output/'results.json').write_text(json.dumps(results, indent=2))
    summary = dict(pairs=len(results)//2, exact_rows_and_estimate_equal=True,
                   hardware_mode='CPU, two torch threads, alternating paired order; unfixed server load',
                   frontend_dither=backend.model.kwargs['frontend'].dither, modes={})
    for reuse in (False, True):
        profiles = [r['profile'] for r in results if r['reuse_predictor'] == reuse]
        summary['modes'][str(reuse)] = {key: statistics.median(p.get(key, 0) for p in profiles)
            for key in ('wall_seconds', 'frontend_seconds', 'encoder_seconds', 'count_seconds',
                        'boundary_predictor_seconds', 'process_cpu_seconds')}
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
