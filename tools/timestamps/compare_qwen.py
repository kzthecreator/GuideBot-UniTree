"""Local completed-audio comparison, not a native streaming benchmark."""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
import soundfile as sf
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'GuideBot/conversation'))
from timestamps import MonotonicBackend, text_units


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--probes-only', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2] / 'recordings'
    cases = []
    audio, rate = sf.read(root / 'long-reply/reply.wav', dtype='float32')
    events = [json.loads(s) for s in (root / 'long-reply/events.jsonl').read_text().splitlines()]
    text = next(e['message'].split('：', 1)[1] for e in events if e['type'] == 'client.reply-text')
    cases.append(('long', audio, text))
    audio, rate = sf.read(root / 'live-session/speaker-16k.wav', dtype='float32')
    index = [json.loads(s) for s in (root / 'live-session/audio-index.jsonl').read_text().splitlines()]
    transcripts = json.loads((root / 'live-session/transcripts.json').read_text())
    for name, rid in [('short', '7cf80c7c-07c3-4acd-b453-6ef3a656318b'),
                      ('medium', 'a9525bae-4a90-4a84-acbb-6a707578492c')]:
        chunks = [audio[e['sample_offset']:e['sample_offset'] + e['samples']]
                  for e in index if e['track'] == 'speaker' and e.get('response_id') == rid]
        text = next(e['message'].split('：', 1)[1] for e in transcripts
                    if e['type'] == 'client.reply-text' and e['response_id'] == rid)
        cases.append((name, np.concatenate(chunks), text))
    from qwen_asr import Qwen3ForcedAligner
    torch.set_num_threads(4)
    started = time.monotonic()
    model = Qwen3ForcedAligner.from_pretrained(
        str(Path.home() / '.local/share/guidebot/deps/qwen3-forced-aligner'),
        device_map='cpu', dtype=torch.float32)
    print('qwen load seconds', time.monotonic() - started, flush=True)
    backend = MonotonicBackend()
    results = json.loads((args.output / 'comparison.json').read_text()) if args.probes_only else []
    for name, audio, text in ([] if args.probes_only else cases):
        started = time.monotonic()
        rows, _ = backend.align((audio * 32768).clip(-32768, 32767).astype('<i2').tobytes(), text_units(text), final=True)
        fun_seconds = time.monotonic() - started
        started = time.monotonic()
        aligned = model.align(audio=(audio, 16000), text=text, language='Chinese')[0]
        qrows = [vars(item) for item in aligned.items]
        result = dict(name=name, audio_seconds=len(audio)/16000, text=text,
                      funasr_seconds=fun_seconds, qwen_seconds=time.monotonic()-started,
                      funasr=rows, qwen=qrows)
        results.append(result)
        (args.output / 'comparison.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(name, result['audio_seconds'], 'FunASR', fun_seconds, 'Qwen', result['qwen_seconds'],
              'units', len(rows), len(qrows), flush=True)
    short = next(r for r in results if r['name'] == 'short')
    _, audio, text = next(c for c in cases if c[0] == 'short')
    probes = []
    for cut in [1.5, 3., 6.]:
        prefix = ''.join(r['text'] for r in short['qwen'] if r['end_time'] <= cut)
        for mode, supplied in [('oracle_completed_prefix', prefix), ('full_future_text', text)]:
            started = time.monotonic()
            aligned = model.align(audio=(audio[:round(cut*16000)], 16000), text=supplied, language='Chinese')[0]
            probes.append(dict(cut=cut, text_mode=mode, text=supplied,
                               compute_seconds=time.monotonic()-started,
                               rows=[vars(r) for r in aligned.items]))
            print('probe', cut, mode, probes[-1]['compute_seconds'], flush=True)
    wrong = ''.join('天' if '\u3400' <= c <= '\u9fff' else c for c in text)
    started = time.monotonic()
    aligned = model.align(audio=(audio,16000), text=wrong, language='Chinese')[0]
    rows, _ = backend.align((audio*32768).clip(-32768,32767).astype('<i2').tobytes(), text_units(wrong), final=True)
    probes.append(dict(text_mode='equal_length_wrong_text', text=wrong,
                       compute_seconds=time.monotonic()-started,
                       qwen=[vars(r) for r in aligned.items], funasr=rows))
    (args.output / 'probes.json').write_text(json.dumps(probes, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
