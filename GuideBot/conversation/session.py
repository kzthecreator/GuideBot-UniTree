"""Construct the fixed acoustic frontend; lifecycle belongs to ROS, not this module."""
import os
from pathlib import Path

from .knowledge import AGENT_DIRECTORY, load_secret, load_knowledge, read_soul, sync_knowledge
from .stepfun import RealtimeSession

STANDARD_AEC_MODEL = Path(__file__).resolve().parents[2]/'drivers/localvqe/models/localvqe-v1.2-1.3M-f32.gguf'


def prepare(options):
    secret = load_secret()
    gestures = options.get('gestures', False) or options.get('gesture_backend') is not None
    if gestures and not os.environ.get('DEEPSEEK_API_KEY', '').strip():
        raise ValueError('DEEPSEEK_API_KEY is required for gesture planning')
    directory = Path(AGENT_DIRECTORY)
    knowledge = (sync_knowledge(directory/'knowledge', secret=secret).vector_store_id
                 if options.get('sync_knowledge_before_start') else load_knowledge(directory/'knowledge'))
    return dict(secret=secret, instructions=read_soul(directory), vector_store_id=knowledge)


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
