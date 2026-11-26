"""Cache each synthesized sentence and publish a complete bundle atomically."""
import fcntl
import json
from pathlib import Path
import os
import shutil
import tempfile

from GuideBot.tour.assets import CONFIG, asset_root, load_bundle, plan, wav_info


def atomic_json(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False, indent=2, allow_nan=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def prepare(config=CONFIG, root=None, *, dry_run=False, client=None):
    definition = plan(config)
    root = Path(root or asset_root())
    segments = {s['key']:s for p in definition['points'] for s in p['segments']}
    cached = {}
    for key in segments:
        path = root/'cache'/(key+'.wav')
        if path.is_file():
            try:
                cached[key] = wav_info(path.read_bytes())
            except ValueError:
                pass
    summary = dict(bundle_id=definition['bundle_id'], points=len(definition['points']),
                   segments=sum(len(p['segments']) for p in definition['points']),
                   unique_segments=len(segments), cached=len(cached),
                   to_generate=len(segments)-len(cached), dry_run=dry_run)
    if dry_run:
        return summary
    if client is None and summary['to_generate']:
        raise ValueError('A StepFun TTS client is required to build missing audio')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    (root/'cache').mkdir(exist_ok=True)
    (root/'bundles').mkdir(exist_ok=True)
    with (root/'prepare.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Tour registration is already running') from None
        target = root/'bundles'/definition['bundle_id']
        if target.exists():
            load_bundle(config, root)
            return dict(summary, to_generate=0, reused_bundle=True)
        settings = {k:v for k,v in definition['speech'].items() if k != 'max_segment_chars'}
        staging = Path(tempfile.mkdtemp(prefix='.building-', dir=root/'bundles'))
        try:
            (staging/'audio').mkdir()
            audio = {}
            for key, segment in segments.items():
                cache = root/'cache'/(key+'.wav')
                if key not in cached:
                    data = client.synthesize(segment['text'], settings)
                    info = wav_info(data)
                    fd, name = tempfile.mkstemp(dir=root/'cache', prefix='.wav-')
                    try:
                        with os.fdopen(fd, 'wb') as out:
                            out.write(data)
                        os.replace(name, str(cache))
                    finally:
                        if os.path.exists(name): os.unlink(name)
                else:
                    info = wav_info(cache.read_bytes())
                shutil.copyfile(str(cache), str(staging/'audio'/(key+'.wav')))
                audio[key] = info
            atomic_json(staging/'manifest.json', dict(definition=definition, audio=audio))
            # Configuration may have changed during slow network synthesis.
            if plan(config) != definition:
                raise RuntimeError('Tour configuration changed during preparation; rerun prepare')
            os.replace(str(staging), str(target))
        finally:
            if staging.exists(): shutil.rmtree(str(staging))
    return summary
