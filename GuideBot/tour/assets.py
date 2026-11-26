"""Deterministic tour registration plans and verified, immutable audio bundles."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import wave

from GuideBot.configuration import USER_CONFIG_DIRECTORY

CONFIG = USER_CONFIG_DIRECTORY / 'tour'
SPLITTER_VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def asset_root():
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'guidebot/tours'


def read_json(path):
    from GuideBot.gesture.catalog import strict_json
    return strict_json(Path(path).read_text(encoding='utf-8'))


def plan(config=CONFIG):
    config = Path(config)
    source, speech = read_json(config/'points.json'), read_json(config/'speech.json')
    if (not isinstance(source, dict) or set(source) != {'schema_version', 'points'}
            or type(source['schema_version']) is not int or source['schema_version'] != 1
            or not isinstance(source['points'], list) or not 1 <= len(source['points']) <= 200):
        raise ValueError('Invalid tour points document')
    if (not isinstance(speech, dict) or set(speech) != {'model','voice','speed','sample_rate',
                                                       'response_format','max_segment_chars'}):
        raise ValueError('Invalid tour speech settings')
    if speech['model'] not in {'stepaudio-3-tts','stepaudio-2.5-tts','step-tts-2','step-tts-mini'}:
        raise ValueError('Unsupported StepFun TTS model')
    if not isinstance(speech['voice'], str) or not speech['voice'].strip():
        raise ValueError('TTS voice is required')
    if (type(speech['speed']) not in (int, float) or not .5 <= speech['speed'] <= 2
            or speech['sample_rate'] != 24000 or speech['response_format'] != 'wav'
            or type(speech['max_segment_chars']) is not int
            or not 10 <= speech['max_segment_chars'] <= 1000):
        raise ValueError('TTS requires WAV/24000Hz, speed .5..2, segment length 10..1000')
    settings = {k:v for k,v in speech.items() if k != 'max_segment_chars'}
    points, ids = [], set()
    for point in source['points']:
        if not isinstance(point, dict) or set(point) != {'id','name','script'}:
            raise ValueError('Each tour point requires id, name, script')
        if (not isinstance(point['id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', point['id'])
                or point['id'] in ids):
            raise ValueError('Tour point IDs must be unique ASCII identifiers')
        if any(not isinstance(point[k], str) or not point[k].strip() for k in ('name','script')):
            raise ValueError('Tour point name/script cannot be empty')
        if len(point['script']) > 100000:
            raise ValueError('Tour point script exceeds limit')
        ids.add(point['id'])
        script = point['script']
        segments, start = [], 0
        for i, char in enumerate(script):
            end = i+1
            if char in '。！？!?；;\n' or end-start >= speech['max_segment_chars'] or end == len(script):
                text = script[start:end]
                if text.strip():
                    key = digest(dict(text=text, settings=settings, splitter=SPLITTER_VERSION))
                    segments.append(dict(text=text, start=start, end=end, key=key))
                start = end
        points.append(dict(point, segments=segments))
    definition = dict(schema_version=1, splitter_version=SPLITTER_VERSION,
                      speech=speech, points=points)
    return dict(definition, bundle_id=digest(definition))


def wav_info(data):
    try:
        with wave.open(io.BytesIO(data), 'rb') as source:
            if (source.getnchannels() != 1 or source.getsampwidth() != 2
                    or source.getframerate() != 24000 or source.getcomptype() != 'NONE'):
                raise ValueError('Tour audio must be mono PCM16 WAV at 24000 Hz')
            frames = source.getnframes()
            pcm = source.readframes(frames)
            if not 0 < frames <= 24000*120 or len(pcm) != frames*2:
                raise ValueError('Invalid or oversized tour audio frames')
        return dict(frames=frames, duration_s=frames/24000, sha256=hashlib.sha256(data).hexdigest())
    except (wave.Error, EOFError):
        raise ValueError('Invalid tour WAV') from None


def load_bundle(config=CONFIG, root=None):
    expected = plan(config)
    path = Path(root or asset_root())/'bundles'/expected['bundle_id']
    if not (path/'manifest.json').is_file():
        raise RuntimeError('Tour audio is missing or stale; run python test/tools/tour/prepare.py')
    manifest = read_json(path/'manifest.json')
    if not isinstance(manifest, dict) or manifest.get('definition') != expected:
        raise ValueError('Tour bundle does not match registered configuration')
    audio = manifest.get('audio')
    keys = {s['key'] for p in expected['points'] for s in p['segments']}
    if not isinstance(audio, dict) or set(audio) != keys:
        raise ValueError('Incomplete tour audio manifest')
    for key in keys:
        data = (path/'audio'/(key+'.wav')).read_bytes()
        if len(data) > 32*1024*1024 or wav_info(data) != audio[key]:
            raise ValueError('Tour audio integrity check failed')
    return dict(definition=expected, path=path, audio=audio)


def read_pcm(bundle, key):
    path = bundle['path']/'audio'/(key+'.wav')
    data = path.read_bytes()
    if wav_info(data) != bundle['audio'][key]:
        raise ValueError('Tour audio changed after activation')
    with wave.open(io.BytesIO(data), 'rb') as source:
        return source.readframes(source.getnframes())
