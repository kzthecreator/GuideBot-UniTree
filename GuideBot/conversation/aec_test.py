"""Manually capture G1 echo; run raw diagnostics or LocalVQE offline without cloud."""

import argparse
import audioop
import ctypes
import json
from pathlib import Path
import threading
import time
import wave

import numpy as np

from audio import (AudioDiagnostic, EchoCanceller, StreamingSpeaker, RATE,
                   microphone_packets, prepare_audio, save_wav, state_directory,
                   wait_for_enter)


def read_pcm(path):
    with wave.open(str(path), "rb") as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (RATE, 1, 2):
            raise ValueError("Expected 16 kHz mono PCM16 diagnostic WAV")
        return source.readframes(source.getnframes())


class ResidualSuppressor:
    """Experimental Speex residual echo/noise postfilter for offline validation."""

    def __init__(self, echo, noise_db=-15, attach_echo=True):
        self.lib = echo.lib
        self.lib.speex_preprocess_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
        self.lib.speex_preprocess_state_init.restype = ctypes.c_void_p
        self.lib.speex_preprocess_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        self.lib.speex_preprocess_ctl.restype = ctypes.c_int
        self.lib.speex_preprocess_run.argtypes = [ctypes.c_void_p, echo.pointer]
        self.lib.speex_preprocess_run.restype = ctypes.c_int
        self.lib.speex_preprocess_state_destroy.argtypes = [ctypes.c_void_p]
        self.lib.speex_preprocess_state_destroy.restype = None
        self.pointer = echo.pointer
        self.state = self.lib.speex_preprocess_state_init(echo.frame_samples, RATE)
        if not self.state:
            raise RuntimeError("Speex postfilter initialization failed")
        try:
            # SpeexDSP public ctl constants: denoise, AGC, VAD, suppression levels.
            for option, value in ((0, 1), (2, 0), (18, noise_db),
                                  (20, -40 if attach_echo else 0),
                                  (22, -10 if attach_echo else 0)):
                number = ctypes.c_int(value)
                if self.lib.speex_preprocess_ctl(self.state, option, ctypes.byref(number)):
                    raise RuntimeError(f"Speex postfilter rejected option {option}")
            if attach_echo and self.lib.speex_preprocess_ctl(self.state, 24, echo.state):
                raise RuntimeError("Speex postfilter rejected echo state")
        except Exception:
            self.close()
            raise

    def process_frame(self, frame):
        if len(frame) != 160:
            raise ValueError("Speex postfilter requires complete 10ms frames")
        self.lib.speex_preprocess_run(self.state, frame.ctypes.data_as(self.pointer))

    def close(self):
        if self.state:
            self.lib.speex_preprocess_state_destroy(self.state)
            self.state = None

    def process(self, pcm):
        samples = np.frombuffer(pcm, dtype='<i2').copy()
        for start in range(0, len(samples), 160):
            self.process_frame(samples[start:start+160])
        return samples.tobytes()


def analyze(directory, delays, postfilter=False, noise_db=-15, denoise_first=False):
    if postfilter and denoise_first:
        raise ValueError("Choose either postfilter or denoise-first for a controlled comparison")
    directory = Path(directory)
    records = [json.loads(line) for line in (directory / "audio-index.jsonl").read_text().splitlines()]
    pcm = {name: read_pcm(directory / f"{name}-16k.wav") for name in ("microphone", "speaker")}
    references = [r for r in records if r["track"] == "speaker" and r.get("code") == 0]
    if not references:
        raise RuntimeError("No successful speaker submissions in recording")
    # Exclude startup convergence and the playback tail from the comparison.
    begin = min(r["elapsed"] for r in references) + 2
    end = max(r["elapsed"] + r["samples"] / RATE for r in references)
    baseline_energy, baseline_samples = 0., 0
    for r in records:
        if r["track"] == "microphone" and r["elapsed"] < begin - 2.5:
            block = pcm["microphone"][r["sample_offset"]*2:(r["sample_offset"]+r["samples"])*2]
            values = np.frombuffer(block, dtype="<i2").astype(float)
            baseline_energy += float(np.sum(values*values))
            baseline_samples += len(values)
    baseline_power = baseline_energy / max(baseline_samples, 1)
    if baseline_samples:
        print(f"Room baseline: {10*np.log10(max(baseline_power, 1e-12)/32768**2):.2f} dBFS")
    results = []
    for delay in delays:
        echo = EchoCanceller(delay)
        suppression = None
        denoiser = None
        denoised, denoised_energy = bytearray(), 0.
        output, input_energy, output_energy, count = bytearray(), 0., 0., 0
        events = sorted(records, key=lambda r: r.get("rpc_finished_elapsed", r["elapsed"]))
        try:
            if postfilter:
                suppression = ResidualSuppressor(echo, noise_db)
            if denoise_first:
                denoiser = ResidualSuppressor(echo, noise_db, attach_echo=False)
            for r in events:
                name = r["track"]
                if name not in pcm:
                    continue
                block = pcm[name][r["sample_offset"] * 2:(r["sample_offset"] + r["samples"]) * 2]
                if name == "speaker":
                    if r.get("code") == 0:
                        echo.add_reference(block, r["elapsed"])
                    continue
                cleaned = denoiser.process(block) if denoiser else block
                if denoiser:
                    denoised.extend(cleaned)
                filtered = echo.process(cleaned, r["elapsed"],
                                        postprocess=suppression.process_frame if suppression else None)
                output.extend(filtered)
                if begin <= r["elapsed"] - r["samples"] / RATE and r["elapsed"] <= end:
                    x = np.frombuffer(block, dtype="<i2").astype(float)
                    y = np.frombuffer(filtered, dtype="<i2").astype(float)
                    if len(x) != len(y):
                        raise RuntimeError("Unexpected AEC frame length")
                    input_energy += float(np.sum(x*x))
                    z = np.frombuffer(cleaned, dtype='<i2').astype(float)
                    denoised_energy += float(np.sum(z*z))
                    output_energy += float(np.sum(y*y))
                    count += len(x)
        finally:
            if suppression is not None:
                suppression.close()
            if denoiser is not None:
                denoiser.close()
            echo.close()
        if not count or not input_energy:
            raise RuntimeError("Not enough nonzero microphone audio during playback")
        reduction = 10 * np.log10(input_energy / max(output_energy, 1))
        prefix = f"aec-postfilter-noise{noise_db}" if postfilter else "aec"
        if denoise_first:
            prefix = f"denoise{noise_db}-then-aec"
            save_wav(directory / f"denoise-only-noise{noise_db}.wav", denoised)
        filename = f"{prefix}-delay-{delay}ms.wav"
        save_wav(directory / filename, output)
        results.append({"delay_ms": delay, "reduction_db": round(float(reduction), 3),
                        "aec_incremental_db": round(float(10*np.log10(max(denoised_energy, 1)/max(output_energy, 1))), 3),
                        "input_dbfs": round(float(10*np.log10(input_energy/count/32768**2)), 2),
                        "output_dbfs": round(float(10*np.log10(max(output_energy, 1)/count/32768**2)), 2),
                        "output": filename})
    results.sort(key=lambda r: r["reduction_db"], reverse=True)
    (directory / f"{prefix}-comparison.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    for result in results:
        print(f"delay={result['delay_ms']:4d} ms  reduction={result['reduction_db']:7.3f} dB  "
              f"input={result['input_dbfs']:.2f}  output={result['output_dbfs']:.2f} dBFS")
        if denoise_first:
            print(f"  AEC-only additional reduction after denoising: {result['aec_incremental_db']:.3f} dB")
    print("Best energy reduction:", directory / results[0]["output"])
    if baseline_samples and input_energy/count < baseline_power * 2:
        print("WARNING: playback input is less than 3 dB above the room baseline. "
              "Total energy reduction cannot reliably measure echo cancellation here.")
    print("Energy reduction alone does not prove echo removal. Compare speech intelligibility; "
          "this ranking is valid only when nobody spoke during playback.")
    if postfilter or denoise_first:
        print("Pipeline includes noise suppression. Energy reduction is NOT echo-only reduction; "
              "human interruption preservation must be tested separately.")
    return results


def capture(source, seconds, preserve_level=False, probe_level_dbfs=None):
    directory = state_directory() / f"aec-test-{time.time_ns()}"
    directory.mkdir(parents=True, mode=0o700)
    if probe_level_dbfs is not None:
        # Seeded, nonperiodic, band-limited noise; peak bound is digital, not SPL.
        samples = np.random.default_rng(20261112).normal(size=round(seconds*RATE))
        spectrum = np.fft.rfft(samples)
        frequencies = np.fft.rfftfreq(len(samples), 1/RATE)
        spectrum[(frequencies < 150) | (frequencies > 6500)] = 0
        samples = np.fft.irfft(spectrum, n=len(samples))
        fade = min(800, len(samples)//2)
        samples[:fade] *= np.linspace(0, 1, fade)
        samples[-fade:] *= np.linspace(1, 0, fade)
        samples *= 32767 * 10**(probe_level_dbfs/20) / np.max(np.abs(samples))
        pcm = np.rint(samples).astype('<i2').tobytes()
        save_wav(directory / 'source-16k.wav', pcm)
        print(f"Nonrepeating noise probe: digital peak {probe_level_dbfs:g} dBFS; actual SPL unknown.")
    else:
        pcm = prepare_audio(source, directory / "source-16k.wav", normalize=not preserve_level)
    if len(pcm) < RATE * 2:
        raise ValueError("Use a speech recording at least one second long")
    print("Local test only: no cloud, VAD, gate, or microphone mode changes.")
    print(f"After Enter: 2s room baseline, {seconds:g}s repeated speech, then 2s tail. Stay silent.")
    print("SDK speaker volume is read only; playback gain=1. "
          + ("Source level preserved." if preserve_level or probe_level_dbfs is not None else "Source peak normalized."))
    wait_for_enter("Press Enter to start recording and playback; Ctrl+C cancels. ")
    started = time.monotonic()
    diagnostic = AudioDiagnostic(directory, started)
    stop = threading.Event()
    first_packet = threading.Event()
    errors = []
    stats = {"microphone_packets": 0, "nonzero_packets": 0}

    def fail(error):
        errors.append(str(error))
        stop.set()

    def microphone():
        try:
            for data in microphone_packets(stop, stats):
                diagnostic.write("microphone", data, time.monotonic())
                first_packet.set()
        except Exception as error:
            fail(error)

    def reference(data, submitted_at, **details):
        finished = details.pop("rpc_finished")
        diagnostic.write("speaker", data, submitted_at,
                         rpc_finished_elapsed=finished-started, **details)

    worker = threading.Thread(target=microphone, daemon=True)
    speaker = StreamingSpeaker(stop, fail, gain=1., on_reference=reference)
    worker.start()
    try:
        if not first_packet.wait(6):
            raise RuntimeError("Microphone not ready; playback was not started")
        if not speaker.start():
            raise RuntimeError("Speaker initialization failed")
        if stop.wait(2):
            raise RuntimeError("Capture failed before playback")
        playback_started = time.monotonic()
        position, state = 0, None
        total = round(seconds * RATE) * 2
        while position < total and not stop.is_set():
            size = min(3200, total-position)
            block = bytes(pcm[(position+i) % len(pcm)] for i in range(size))
            converted, state = audioop.ratecv(block, 2, 1, RATE, 24000, state)
            speaker.feed("aec-test", converted)
            position += size
            stop.wait(max(0, playback_started+position/(RATE*2)-time.monotonic()))
        speaker.finish("aec-test")
        deadline = time.monotonic() + 10
        while not stop.is_set():
            with speaker.condition:
                pending = bool(speaker.responses)
            if not pending:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Speaker did not drain within 10s")
            stop.wait(.1)
        stop.wait(2)
    finally:
        stop.set()
        try:
            speaker.close()
        finally:
            worker.join(timeout=2)
            diagnostic.close()
            (directory / "capture.json").write_text(json.dumps({"source": str(source),
                "probe_level_dbfs": probe_level_dbfs, "preserve_level": preserve_level,
                "seconds": seconds, "stats": stats, "errors": errors}, indent=2), encoding="utf-8")
            print("Saved:", directory)
    if errors:
        raise RuntimeError("; ".join(errors))
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/home/fk/GuideBot-UniTree/zero_shot_prompt.wav"))
    parser.add_argument("--seconds", type=float, default=25)
    parser.add_argument("--analyze", type=Path, help="Replay a saved diagnostic directory; no recording/playback")
    parser.add_argument("--raw-diagnostics", action="store_true",
                        help="Only cross-correlation, window/band offsets and RMS; no AEC/NS")
    parser.add_argument("--window-seconds", type=float, default=5, help="Correlation window length (default: 5s)")
    parser.add_argument("--probe-noise", action="store_true", help="Generate nonrepeating low-level band-limited noise")
    parser.add_argument("--level-dbfs", type=float, default=-30, help="Noise probe digital peak, -60..-20 (default: -30)")
    parser.add_argument("--preserve-level", action="store_true", help="Do not peak normalize a supplied source")
    parser.add_argument("--delays", type=int, nargs="+", default=[0], help="LocalVQE reference delays (default: 0)")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 60 or any(not 0 <= d <= 1000 for d in args.delays):
        parser.error("seconds must be 5..60; delays must be 0..1000 ms")
    if not 1 <= args.window_seconds <= 10 or not -60 <= args.level_dbfs <= -20:
        parser.error("window-seconds must be 1..10; level-dbfs must be -60..-20")
    directory = args.analyze if args.analyze else capture(args.source, args.seconds,
        args.preserve_level, args.level_dbfs if args.probe_noise else None)
    if args.raw_diagnostics:
        from echo_diagnostic import diagnose
        diagnose(directory, window_seconds=args.window_seconds)
    else:
        from localvqe_test import compare
        for delay in args.delays:
            compare(directory, delay)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        raise SystemExit(str(error)) from None
