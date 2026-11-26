"""Choose a business service without changing ROS resource mode or authorization."""
from pathlib import Path
import os

from GuideBot.configuration import read_prompt


def validate_options(options):
    service = options.get('service') or 'conversation'
    if service not in {'conversation','tour'}:
        raise ValueError('Unknown business service')
    if service == 'tour' and (options.get('gestures') or options.get('gesture_backend')
            or options.get('sync_knowledge_before_start') or options.get('timestamps')):
        raise ValueError('Tour is voice-only; remove gesture, timestamp and knowledge-sync options')
    return service


def prepare(options):
    if validate_options(options) == 'conversation':
        from GuideBot.conversation.session import prepare as prepare_conversation
        return prepare_conversation(options)
    from GuideBot.conversation.knowledge import load_secret
    from GuideBot.tour.assets import load_bundle
    from GuideBot.tour.context import render
    from GuideBot.tour.controller import TourController
    bundle = load_bundle()
    prompt = read_prompt('tour/prompt.md')
    template = read_prompt('tour/context_template.md')
    render(template, TourController(bundle['definition']['points'], bundle['definition']['bundle_id']))
    return dict(secret=load_secret(), bundle=bundle, prompt=prompt, context_template=template)


def build_session(options, directory, prepared, gesture_service_factory):
    if validate_options(options) == 'conversation':
        from GuideBot.conversation.session import build_session as build_conversation
        return build_conversation(options, directory, prepared, gesture_service_factory)
    from GuideBot.conversation.session import STANDARD_AEC_MODEL
    from GuideBot.tour.session import TourSession
    return TourSession(prepared['secret'], Path(directory), prepared['bundle'], prepared['prompt'],
        prepared['context_template'], voice=options.get('voice') or prepared['bundle']['definition']['speech']['voice'],
        chunk_ms=200, gain=float(os.environ.get('G1_SPEAKER_GAIN','1.5')),
        diagnose_audio=options.get('diagnose_audio', True), vad_energy=options.get('vad_energy',4999),
        aec=True, aec_model=STANDARD_AEC_MODEL, mic_gate_dbfs=None, agc=True)
