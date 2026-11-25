"""Press Enter to start a realtime conversation; Enter again to stop."""

import argparse
import json
import os
from pathlib import Path
import select
import signal
import sys
import time

from audio import state_directory, wait_for_enter
from knowledge import AGENT_DIRECTORY, load_knowledge, load_secret, read_soul, sync_knowledge
from stepfun import MODEL, RealtimeSession, DEFAULT_DIAGNOSE_AUDIO, DEFAULT_VAD_ENERGY

STANDARD_AEC_MODEL = Path(__file__).resolve().parents[2] / "drivers/localvqe/models/localvqe-v1.2-1.3M-f32.gguf"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnose-audio", action=argparse.BooleanOptionalAction, default=DEFAULT_DIAGNOSE_AUDIO,
                        help="Save microphone/reference PCM and timestamps (default: enabled)")
    parser.add_argument("--vad-energy", type=int, default=DEFAULT_VAD_ENERGY, choices=range(0, 5001),
                        metavar="0..5000", help=f"Server VAD energy threshold (default: {DEFAULT_VAD_ENERGY})")
    parser.add_argument("--sync-knowledge", dest="sync_knowledge_before_start", action="store_true",
                        help="Synchronize StepFun knowledge before starting")
    parser.add_argument("--voice", help="StepFun voice (default: STEP_VOICE or service default)")
    parser.add_argument("--timestamps", action=argparse.BooleanOptionalAction, default=False,
                        help="Experimental background FunASR character timestamps; does not delay playback")
    parser.add_argument('--gestures', action='store_true',
                        help='Enable gesture planning and the validated timestamp profile (simulated unless backend=unitree)')
    parser.add_argument('--gesture-registry', type=Path, help='Action registry JSON')
    parser.add_argument('--gesture-targets', type=Path, help='Scene target JSON; default no targets')
    parser.add_argument('--gesture-backend', choices=('simulated', 'unitree'), default=None,
                        help='Motion backend; unitree enables gestures and commands the real robot after Enter')
    args = parser.parse_args()
    return start_conversation(**vars(args))


def start_conversation(*, sync_knowledge_before_start=False, diagnose_audio=DEFAULT_DIAGNOSE_AUDIO,
                       vad_energy=DEFAULT_VAD_ENERGY, agent_directory=AGENT_DIRECTORY,
                       timestamps=False, gestures=False, gesture_registry=None,
                       gesture_targets=None, voice=None, gesture_backend=None):
    """Use the standard StepFun frontend; audio starts only after Enter."""
    if gesture_backend is None:
        mode = os.environ.get('GUIDEBOT_GESTURE_EXECUTION_MODE', 'simulation')
        if mode not in {'simulation', 'robot'}:
            raise ValueError('Invalid gesture execution mode')
        gesture_backend = 'unitree' if mode == 'robot' else 'simulated'
    gestures = gestures or gesture_backend == 'unitree'
    instructions = read_soul(agent_directory)
    secret = load_secret()
    if gesture_backend == 'unitree' and not os.environ.get('DEEPSEEK_API_KEY', '').strip():
        config = os.environ.get('GUIDEBOT_CONFIG_FILE', str(Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'guidebot/conversation.env'))
        raise ValueError(f'DEEPSEEK_API_KEY is required for real gestures. Set it in {config}; '
                         'voice and motion have not started')
    knowledge_directory = Path(agent_directory) / "knowledge"
    if sync_knowledge_before_start:
        print("Synchronizing knowledge before conversation. No audio has started.", flush=True)
        synced = sync_knowledge(knowledge_directory, secret=secret)
        vector_store_id = synced.vector_store_id
        print(f"Knowledge synchronized: added={len(synced.added)}, modified={len(synced.modified)}, "
              f"deleted={len(synced.deleted)}, repaired={len(synced.repaired)}", flush=True)
    else:
        vector_store_id = load_knowledge(knowledge_directory)
    chunk_ms = int(os.environ.get("G1_PLAY_CHUNK_MS", "1000"))
    gain = float(os.environ.get("G1_SPEAKER_GAIN", "1.5"))
    directory = state_directory() / f"realtime-{time.time_ns()}"
    session = RealtimeSession(
        secret, directory, voice or os.environ.get("STEP_VOICE"), chunk_ms, gain,
        vector_store_id=vector_store_id, diagnose_audio=diagnose_audio,
        vad_energy=vad_energy, aec=True, aec_delay_ms=0, mic_gate_dbfs=None,
        aec_model=STANDARD_AEC_MODEL, agc=True, instructions=instructions,
        timestamps=timestamps, gestures=gestures,
        gesture_registry=gesture_registry, gesture_targets=gesture_targets,
        gesture_backend=gesture_backend)
    print(f"Provider: stepfun; model: {MODEL}. Keep the official assistant in the working wake-up state.")
    print("G1 microphone 16 kHz -> cloud 24 kHz; cloud reply 24 kHz -> G1 speaker 16 kHz.")
    print(f"Knowledge base: {vector_store_id}.")
    print(f"Instructions: {Path(agent_directory) / 'soul.md'}")
    print("Standard frontend: LocalVQE v1.2 (AEC + NS + dereverb), 16 ms hops, reference delay 0 ms.")
    print("Standalone AGC2: 3 dB/s, saturation margin 24 dB, peak <= -1 dBFS; RMS gate disabled.")
    print(f"Session event/error logs: {directory}")
    print("Audio recording: " + ("enabled" if diagnose_audio else "disabled (event/error logs retained)"))
    if timestamps:
        print(f"Experimental FunASR timestamps: {directory / 'alignment.jsonl'}")
    if gestures:
        print(f"DeepSeek gestures: backend={gesture_backend}; log: {directory / 'gesture.jsonl'}")
        if gesture_backend == 'unitree':
            print("Fork motion lifecycle after Enter: start server, acquire, release on exit; URDF limits enabled.")
    wait_for_enter("Press Enter to start realtime conversation, or Ctrl+C to cancel. ")
    motion_runtime = None
    try:
        if gestures and gesture_backend == 'unitree':
            from GuideBot.gesture.motion_runtime import MotionRuntime
            motion_runtime = MotionRuntime()
            motion_runtime.log_directory = directory
            try:
                motion_runtime.start()
            except Exception as error:
                session.fail(error)
                raise
            print('Motion server acquired upper-body control.', flush=True)
        session.start()
        print("Connecting. Press Enter again at any time to stop.", flush=True)
        deadline = time.monotonic() + 20
        while not session.stopping.is_set():
            if not session.ready.is_set() and time.monotonic() >= deadline:
                session.fail(TimeoutError("Session did not become ready within 20s"))
                break
            readable, _, _ = select.select([sys.stdin], [], [], 0.2)
            if readable:
                sys.stdin.readline()
                break
    finally:
        try:
            result = session.stop()
        finally:
            if motion_runtime is not None:
                motion_runtime.stop()
                print('Motion server released upper-body control.', flush=True)
        if directory.exists():
            (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Realtime conversation stopped.")
        if result.get("aec_stats"):
            stats = result["aec_stats"]
            print(f"AEC: processed_frames={stats['frames']}, reference_frames={stats['reference_frames']}")
        if result.get("mic_gate_stats"):
            stats = result["mic_gate_stats"]
            print(f"Microphone gate: muted_frames={stats['muted_frames']}/{stats['frames']}")
        if diagnose_audio:
            print(f"Audio diagnostics saved: {directory}")
    if result["errors"]:
        raise RuntimeError("; ".join(result["errors"]))


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as error:
        sys.exit(str(error))
