"""Manual G1 capture or offline LocalVQE comparison; no cloud or hard gate."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from aec_test import capture, read_pcm
from audio import RATE, save_wav
from localvqe import LocalVQEEcho, Processor


def compare(directory, delay_ms=0, model=None):
    directory = Path(directory)
    records = [json.loads(line) for line in (directory/'audio-index.jsonl').read_text().splitlines()]
    microphone = np.frombuffer(read_pcm(directory/'microphone-16k.wav'), dtype='<i2')
    reference = np.frombuffer(read_pcm(directory/'speaker-16k.wav'), dtype='<i2')
    mic_records = [r for r in records if r['track'] == 'microphone']
    if not mic_records:
        raise ValueError('No microphone records')
    anchor = mic_records[0]['elapsed']-mic_records[0]['samples']/RATE
    aligned = np.zeros_like(microphone)
    until = -float('inf')
    for r in records:
        if r['track'] != 'speaker' or r.get('code') != 0:
            continue
        start = max(r['elapsed']+delay_ms/1000, until)
        offset = round((start-anchor)*RATE)
        data = reference[r['sample_offset']:r['sample_offset']+r['samples']]
        left, right = max(0, offset), min(len(aligned), offset+len(data))
        if left < right:
            aligned[left:right] = data[left-offset:right-offset]
        until = start+len(data)/RATE
    outputs = {}
    processor = Processor(model=model)
    output_directory = directory/'localvqe'/processor.model.stem/f'delay{delay_ms}ms'
    output_directory.mkdir(parents=True, exist_ok=True)
    save_wav(output_directory/'aligned-reference.wav', aligned.tobytes())
    try:
        began = time.monotonic()
        outputs['batch'] = processor.process(microphone, aligned)
        batch_seconds = time.monotonic()-began
    finally:
        processor.close()
    echo = LocalVQEEcho(delay_ms, model=model)
    frames = []
    try:
        for r in sorted(records, key=lambda r: r.get('rpc_finished_elapsed', r['elapsed'])):
            start, end = r['sample_offset'], r['sample_offset']+r['samples']
            if r['track'] == 'speaker' and r.get('code') == 0:
                echo.add_reference(reference[start:end].tobytes(), r['elapsed'])
            elif r['track'] == 'microphone':
                frames.append(echo.process(microphone[start:end].tobytes(), r['elapsed']))
        outputs['streaming'] = np.frombuffer(b''.join(frames), dtype='<i2')
        stats = dict(echo.stats)
    finally:
        echo.close()
    stats['batch_seconds'] = batch_seconds
    stats['audio_seconds'] = len(microphone)/RATE
    stats['gate_enabled'] = False
    stats['delay_ms'] = delay_ms
    for mode, values in outputs.items():
        filename = f'{mode}.wav'
        save_wav(output_directory/filename, values.tobytes())
        count = min(len(microphone), len(values))
        power = float(np.sum(values[:count].astype(float)**2))
        reduction = 10*np.log10(max(float(np.sum(microphone[:count].astype(float)**2)), 1)/max(power, 1))
        stats[f'{mode}_total_reduction_db'] = float(reduction)
        print(f'{mode}: total energy reduction={reduction:.3f} dB; {output_directory/filename}')
    # One common gain for all listening copies; never normalize outputs separately.
    stop = min(len(v) for v in outputs.values())
    a, b = min(12*RATE, stop//3), min(20*RATE, stop)
    clips = {'raw': microphone[a:b], **{mode: data[a:b] for mode,data in outputs.items()}}
    peak = max(float(np.max(np.abs(data.astype(float)))) for data in clips.values())
    gain = min(100., 23197/max(peak, 1))
    for mode, data in clips.items():
        save_wav(output_directory/f'listen-{mode}.wav',
                 np.rint(data.astype(float)*gain).clip(-32768,32767).astype('<i2').tobytes())
    stats['listening_gain'] = gain
    (output_directory/'result.json').write_text(json.dumps(stats, indent=2), encoding='utf-8')
    print(f'Processing: batch={batch_seconds:.3f}s; streaming={stats["processing_seconds"]:.3f}s; '
          f'max 16ms hop={stats["max_hop_ms"]:.3f}ms')
    print('No gate. Batch may prime delay from the whole clip; streaming uses only references received so far.')
    print('Total energy reduction includes background changes; listen and test human double-talk separately.')
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analyze', type=Path, help='Existing raw diagnostic directory; no recording/playback')
    parser.add_argument('--source', type=Path, default=Path('/home/fk/GuideBot-UniTree/zero_shot_prompt.wav'))
    parser.add_argument('--seconds', type=float, default=25)
    parser.add_argument('--delay-ms', type=int, default=0, choices=range(1001), metavar='0..1000')
    parser.add_argument('--model', type=Path)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 60:
        parser.error('seconds must be 5..60')
    # Check assets before asking the user to record.
    processor = Processor(model=args.model)
    processor.close()
    directory = args.analyze or capture(args.source, args.seconds)
    compare(directory, args.delay_ms, args.model)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        raise SystemExit(str(error)) from None
