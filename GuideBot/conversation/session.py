"""Construct the fixed acoustic frontend; lifecycle belongs to ROS, not this module."""
import os
from pathlib import Path

from GuideBot.conversation.knowledge import USER_CONFIG_DIRECTORY, load_secret, load_knowledge, read_conversation_prompt, sync_knowledge
from GuideBot.conversation.stepfun import RealtimeSession

STANDARD_AEC_MODEL = Path(os.environ.get('LOCALVQE_MODEL', Path.home()/'.local/share/guidebot/deps/LocalVQE/models/localvqe-v1.2-1.3M-f32.gguf'))


def prepare(options):
    secret = load_secret()
    gestures = options.get('gestures', False) or options.get('gesture_backend') is not None
    if gestures:
        from GuideBot.gesture.provider import validate_configuration
        validate_configuration()
    directory = Path(USER_CONFIG_DIRECTORY)
    knowledge = (sync_knowledge(directory/'conversation'/'knowledge', secret=secret).vector_store_id
                 if options.get('sync_knowledge_before_start') else load_knowledge(directory/'conversation'/'knowledge'))
    return dict(secret=secret, instructions=read_conversation_prompt(directory), vector_store_id=knowledge)


def build_session(options, directory, prepared, gesture_service_factory):
    return RealtimeSession(prepared['secret'], directory,
        options.get('voice') or os.environ.get('STEP_VOICE'),
        int(os.environ.get('G1_PLAY_CHUNK_MS', '1000')), float(os.environ.get('G1_SPEAKER_GAIN', '1.5')),
        vector_store_id=prepared['vector_store_id'], instructions=prepared['instructions'],
        diagnose_audio=options.get('diagnose_audio', True), vad_energy=options.get('vad_energy', 4999),
        aec=True, aec_model=STANDARD_AEC_MODEL, aec_delay_ms=0, mic_gate_dbfs=None, agc=True,
        timestamps=options.get('timestamps', False),
        gestures=options.get('gestures', False) or options.get('gesture_backend') is not None,
        gesture_backend=options.get('gesture_backend') or 'simulated', gesture_service_factory=gesture_service_factory)
