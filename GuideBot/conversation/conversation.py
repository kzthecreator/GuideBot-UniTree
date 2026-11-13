"""Press Enter to start full-duplex StepAudio 3 conversation; Enter again to stop."""

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
    parser.add_argument("--timestamps", action=argparse.BooleanOptionalAction, default=False,
                        help="Experimental background FunASR character timestamps; does not delay playback")
    args = parser.parse_args()
    return start_conversation(**vars(args))


def start_conversation(*, sync_knowledge_before_start=False, diagnose_audio=DEFAULT_DIAGNOSE_AUDIO,
                       vad_energy=DEFAULT_VAD_ENERGY, aec=DEFAULT_AEC,
                       aec_delay_ms=DEFAULT_AEC_DELAY_MS, mic_gate_dbfs=DEFAULT_MIC_GATE_DBFS,
                       agent_directory=AGENT_DIRECTORY, timestamps=False):
    """Prepare agent content, optionally synchronize, then wait for manual audio start."""
    instructions = read_soul(agent_directory)
    secret = load_secret()
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
    session = RealtimeSession(secret, directory, os.environ.get("STEP_VOICE"), chunk_ms, gain,
                              diagnose_audio=diagnose_audio, vad_energy=vad_energy,
                              aec=aec, aec_delay_ms=aec_delay_ms,
                              mic_gate_dbfs=mic_gate_dbfs, instructions=instructions,
                              vector_store_id=vector_store_id, timestamps=timestamps)
    print(f"Model: {MODEL}. Keep the official assistant in the working wake-up state.")
    print("G1 microphone 16 kHz -> cloud 24 kHz; cloud reply 24 kHz -> G1 speaker 16 kHz.")
    print(f"Knowledge base: {vector_store_id}. Instructions: {Path(agent_directory) / 'soul.md'}")
    if aec:
        print(f"LocalVQE enabled (AEC + NS + dereverb): 16 ms hops, reference delay {aec_delay_ms} ms; model output gate disabled.")
    if mic_gate_dbfs is not None:
        print(f"Local microphone gate: {mic_gate_dbfs:g} dBFS, 20 ms RMS, "
              "6 dB hysteresis, 200 ms hold. Active only during estimated speaker playback; "
              "bypassed while idle. Runs after AEC when enabled.")
    if diagnose_audio:
        print(f"Audio diagnostics (microphone, speaker reference, timestamps): {directory}")
    if timestamps:
        print(f"Experimental FunASR timestamps: provisional updates + complete-response repair. Log: {directory / 'alignment.jsonl'}")
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
