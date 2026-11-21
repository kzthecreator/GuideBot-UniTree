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
from stepfun import (MODEL, RealtimeSession, DEFAULT_DIAGNOSE_AUDIO, DEFAULT_VAD_ENERGY,
                     DEFAULT_AEC, DEFAULT_AEC_DELAY_MS, DEFAULT_MIC_GATE_DBFS)
from doubao import DoubaoSession, load_doubao_api_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnose-audio", action=argparse.BooleanOptionalAction, default=DEFAULT_DIAGNOSE_AUDIO,
                        help="Save microphone/reference PCM and timestamps (default: enabled)")
    parser.add_argument("--vad-energy", type=int, default=DEFAULT_VAD_ENERGY, choices=range(0, 5001),
                        metavar="0..5000", help=f"Server VAD energy threshold (default: {DEFAULT_VAD_ENERGY})")
    parser.add_argument("--aec", action=argparse.BooleanOptionalAction, default=DEFAULT_AEC,
                        help="LocalVQE echo/noise/reverb enhancement (default: enabled)")
    parser.add_argument("--aec-delay-ms", type=int, default=DEFAULT_AEC_DELAY_MS, metavar="0..1000",
                        help="Additional estimated speaker delay for AEC (default: 0 ms)")
    parser.add_argument("--mic-gate-dbfs", type=float, default=DEFAULT_MIC_GATE_DBFS, metavar="DBFS",
                        help=f"Playback-only local RMS gate -96..0 dBFS (default: {DEFAULT_MIC_GATE_DBFS:g})")
    parser.add_argument("--no-mic-gate", dest="mic_gate_dbfs", action="store_const", const=None,
                        default=argparse.SUPPRESS, help="Disable the local microphone gate")
    parser.add_argument("--sync-knowledge", dest="sync_knowledge_before_start", action="store_true",
                        help="Synchronize knowledge before starting the realtime session")
    parser.add_argument("--provider", choices=("stepfun", "doubao"), default="stepfun",
                        help="Realtime speech provider (default: stepfun)")
    parser.add_argument('--agc', action=argparse.BooleanOptionalAction, default=None,
                        help='Standalone AGC2 (enabled by default for all providers; --no-agc restores the RMS gate)')
    parser.add_argument("--timestamps", action=argparse.BooleanOptionalAction, default=False,
                        help="Experimental background FunASR character timestamps; does not delay playback")
    parser.add_argument('--gestures', action='store_true',
                        help='DeepSeek gesture planning with simulated execution; enables 4/.5/.25 timestamps')
    parser.add_argument('--gesture-registry', type=Path, help='Action registry JSON')
    parser.add_argument('--gesture-targets', type=Path, help='Scene target JSON; default no targets')
    args = parser.parse_args()
    return start_conversation(**vars(args))


def start_conversation(*, sync_knowledge_before_start=False, diagnose_audio=DEFAULT_DIAGNOSE_AUDIO,
                       vad_energy=DEFAULT_VAD_ENERGY, aec=DEFAULT_AEC,
                       aec_delay_ms=DEFAULT_AEC_DELAY_MS, mic_gate_dbfs=DEFAULT_MIC_GATE_DBFS,
                       agent_directory=AGENT_DIRECTORY, timestamps=False,
                       gestures=False, gesture_registry=None, gesture_targets=None,
                       provider="stepfun", agc=None):
    """Prepare agent content, optionally synchronize, then wait for manual audio start."""
    instructions = read_soul(agent_directory)
    agc = True if agc is None else agc
    if agc:
        mic_gate_dbfs = None
    knowledge_directory = Path(agent_directory) / "knowledge"
    if provider == "stepfun":
        secret = load_secret()
        if sync_knowledge_before_start:
            print("Synchronizing knowledge before conversation. No audio has started.", flush=True)
            synced = sync_knowledge(knowledge_directory, secret=secret)
            vector_store_id = synced.vector_store_id
            print(f"Knowledge synchronized: added={len(synced.added)}, modified={len(synced.modified)}, "
                  f"deleted={len(synced.deleted)}, repaired={len(synced.repaired)}", flush=True)
        else:
            vector_store_id = load_knowledge(knowledge_directory)
    elif provider == "doubao":
        if sync_knowledge_before_start:
            raise ValueError("--sync-knowledge currently synchronizes the StepFun retrieval service only")
        secret = load_doubao_api_key()
        vector_store_id = None
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    chunk_ms = int(os.environ.get("G1_PLAY_CHUNK_MS", "1000"))
    gain = float(os.environ.get("G1_SPEAKER_GAIN", "1.5"))
    directory = state_directory() / f"realtime-{time.time_ns()}"
    common = dict(diagnose_audio=diagnose_audio, vad_energy=vad_energy,
                  aec=aec, aec_delay_ms=aec_delay_ms, mic_gate_dbfs=mic_gate_dbfs,
                  instructions=instructions, timestamps=timestamps, gestures=gestures,
                  gesture_registry=gesture_registry, gesture_targets=gesture_targets)
    if provider == "stepfun":
        session = RealtimeSession(secret, directory, os.environ.get("STEP_VOICE"), chunk_ms, gain,
                                  vector_store_id=vector_store_id, agc=agc, **common)
        model_name = MODEL
    else:
        session = DoubaoSession(secret, directory, os.environ.get("DOUBAO_VOICE"), chunk_ms, gain,
                                agc=agc, **common)
        model_name = session.model
    print(f"Provider: {provider}; model: {model_name}. Keep the official assistant in the working wake-up state.")
    if provider == "stepfun":
        print("G1 microphone 16 kHz -> cloud 24 kHz; cloud reply 24 kHz -> G1 speaker 16 kHz.")
    else:
        print("G1 microphone 16 kHz -> Doubao 16 kHz; Doubao reply 24 kHz -> G1 speaker 16 kHz.")
    if provider == "stepfun":
        print(f"Knowledge base: {vector_store_id}.")
    else:
        print("StepFun cloud retrieval is not enabled for the Doubao provider.")
    print(f"Instructions: {Path(agent_directory) / 'soul.md'}")
    if aec:
        from localvqe import installation
        frontend_model = Path(os.environ.get('LOCALVQE_MODEL', installation() / 'models/localvqe-v1.2-1.3M-f32.gguf'))
        print(f"LocalVQE enabled: {frontend_model.name}; 16 ms hops, reference delay {aec_delay_ms} ms; model output gate disabled.")
        print('Enhancement capabilities depend on the selected model (v1.2: AEC + NS + dereverb).')
    if mic_gate_dbfs is not None:
        print(f"Local microphone gate: {mic_gate_dbfs:g} dBFS, 20 ms RMS, "
              "6 dB hysteresis, 200 ms hold. Active only during estimated speaker playback; "
              "bypassed while idle. Runs after AEC when enabled.")
    if agc:
        print('Standalone WebRTC AGC2 after LocalVQE: 3 dB/s, initial saturation margin 24 dB, '
              'output peak <= -1 dBFS; RMS gate disabled. No additional AEC/NS/dereverb.')
    if diagnose_audio:
        print(f"Audio diagnostics (microphone, speaker reference, timestamps): {directory}")
    if timestamps:
        print(f"Experimental FunASR timestamps: provisional updates + complete-response repair. Log: {directory / 'alignment.jsonl'}")
    if gestures:
        print(f"DeepSeek gestures: simulation only; does not delay speech. Log: {directory / 'gesture.jsonl'}")
    wait_for_enter("Press Enter to start realtime conversation, or Ctrl+C to cancel. ")
    try:
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
        result = session.stop()
        if directory.exists():
            (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Realtime conversation stopped.")
        if aec and result.get("aec_stats"):
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
