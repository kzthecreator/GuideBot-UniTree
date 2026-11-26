#!/usr/bin/env python3
"""Prepare editable narration, synthesized speech and offline timestamp assets."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import wave

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthesize(text, destination, args):
    from dotenv import load_dotenv
    from openai import OpenAI
    config = args.config or Path(os.environ.get('GUIDEBOT_CONFIG_FILE', Path.home()/'.config/guidebot/conversation.env'))
    load_dotenv(config, override=False, interpolate=False)
    key = os.environ.get('STEPFUN_API_KEY') or os.environ.get('STEP_API_KEY')
    if not key:
        raise ValueError('Configure STEPFUN_API_KEY (or STEP_API_KEY), or use --config')
    voice = args.voice or os.environ.get('STEP_VOICE') or 'cixingnansheng'
    client = OpenAI(api_key=key, base_url=os.environ.get('STEPFUN_BASE_URL', 'https://api.stepfun.com/v1'), timeout=120, max_retries=0)
    try:
        with client.audio.speech.with_streaming_response.create(
                model=args.model, voice=voice, input=text, speed=args.speed,
                response_format='mp3') as response:
            response.stream_to_file(destination)
    finally:
        client.close()
    return dict(provider='stepfun', model=args.model, voice=voice, speed=args.speed)


def prepare(args):
    from drivers.timestamps.runtime import MonotonicBackend, text_units
    text = args.text.expanduser().read_text(encoding='utf-8-sig').strip()
    units = text_units(text)
    if not units:
        raise ValueError('Text has no supported speech units')
    if not math.isfinite(args.silence_prefix_s) or args.silence_prefix_s < 0:
        raise ValueError('--silence-prefix-s must be finite and nonnegative')
    if args.command == 'synthesize' and (not math.isfinite(args.speed) or not .5 <= args.speed <= 2):
        raise ValueError('--speed must be between 0.5 and 2')
    source = args.audio.expanduser().resolve() if args.command == 'align' else None
    if source and not source.is_file():
        raise FileNotFoundError(source)
    out = args.output.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('Choose a new or empty output directory; existing assets are never overwritten')
    (out/'text.txt').write_text(text + '\n', encoding='utf-8')
    try:
        settings = None
        if source is None:
            source = out/'source.mp3'
            settings = synthesize(text, source, args)
        else:
            target = out/('source' + source.suffix.lower())
            shutil.copy2(source, target)
            source = target
        # Align unpadded audio, then shift boundaries by the exact inserted PCM duration.
        import numpy as np
        import soundfile as sf
        from scipy.signal import resample_poly
        signal, rate = sf.read(str(source), dtype='float32', always_2d=True)
        signal = signal.mean(axis=1)
        if rate != 16000:
            divisor = math.gcd(rate, 16000)
            signal = resample_poly(signal, 16000 // divisor, rate // divisor)
        if not np.isfinite(signal).all():
            raise ValueError('Audio contains nonfinite samples')
        pcm = np.rint(np.clip(signal, -1, 32767/32768) * 32768).astype('<i2').tobytes()
        if not pcm or len(pcm) % 2:
            raise ValueError('Decoded audio is empty or invalid PCM16')
        backend = MonotonicBackend(threads=args.threads)
        rows, _ = backend.align(pcm, units, final=True)
        prefix_samples = round(args.silence_prefix_s * 16000)
        prefix = prefix_samples / 16000
        pcm = bytes(prefix_samples * 2) + pcm
        duration = len(pcm) / 32000
        for row in rows:
            row['start'] += prefix
            row['end'] += prefix
        with wave.open(str(out/'audio.wav'), 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000); audio.writeframes(pcm)
        dump(out/'timestamps.json', dict(text=text, duration_seconds=duration, timestamps=rows))
        dump(out/'scenario.json', dict(name=out.name, audio='audio.wav', timestamps='timestamps.json',
                                      prompt_variant='minimal', stream_step_s=4, text_lookahead_s=6))
        # Reuse the actual example input contract and its monotonic interval validation.
        from examples.gesture_from_audio.run import inputs
        _, _, _, validation = inputs(out/'scenario.json')
        dump(out/'manifest.json', dict(status='complete', mode=args.command, synthesis=settings,
             silence_prefix_s=prefix, source_audio_sha256=sha(source), text_sha256=sha(out/'text.txt'),
             validation=validation, alignment_backend='FunASR MonotonicBackend FP32 final',
             note='Boundaries are estimated from supplied text unit count; no transcript verification. Listen and check before planning.'))
        print('Prepared:', out, '\nUnits:', len(rows), 'Duration:', round(duration, 3), 'seconds')
    except Exception:
        dump(out/'failure.json', dict(status='failed', note='Incomplete assets; use a fresh output directory to retry.'))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for mode in ('synthesize', 'align'):
        cmd = sub.add_parser(mode)
        cmd.add_argument('--text', type=Path, required=True)
        cmd.add_argument('--output', type=Path, required=True)
        cmd.add_argument('--silence-prefix-s', type=float, default=0, help='Optional leading silence; shifts timestamps equally')
        cmd.add_argument('--threads', type=int, default=2)
        if mode == 'align':
            cmd.add_argument('--audio', type=Path, required=True)
        else:
            cmd.add_argument('--config', type=Path)
            cmd.add_argument('--model', default='step-tts-2')
            cmd.add_argument('--voice')
            cmd.add_argument('--speed', type=float, default=1)
    args = parser.parse_args()
    if args.threads < 1:
        parser.error('--threads must be positive')
    try:
        prepare(args)
    except Exception as error:
        # Provider error bodies may contain request details; do not print them.
        print('Preparation failed (' + type(error).__name__ + '). Check configuration, inputs and output directory.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
