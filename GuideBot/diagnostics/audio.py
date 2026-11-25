"""Optional persistent PCM tracks and sample/time indexes."""
import json
import threading
import wave
RATE = 16000

class AudioDiagnostic:
    """Store sample offsets and arrival/RPC times; these are not DAC timestamps."""

    def __init__(self, directory, started_at, processed=False, gated=False, uploaded=False, agc=False):
        self.lock = threading.Lock()
        self.started_at = started_at
        self.closed = False
        self.offsets = {"microphone": 0, "speaker": 0}
        if processed:
            self.offsets["microphone-aec"] = 0
        if gated:
            self.offsets["microphone-gated"] = 0
        if uploaded:
            self.offsets["microphone-uploaded"] = 0
        if agc:
            self.offsets["microphone-agc"] = 0
        self.tracks = {}
        for name in self.offsets:
            track = wave.open(str(directory / f"{name}-16k.wav"), "wb")
            track.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            self.tracks[name] = track
        self.index = (directory / "audio-index.jsonl").open("w", encoding="utf-8")

    def write(self, name, pcm, started_at, **details):
        with self.lock:
            if self.closed:
                return
            self.tracks[name].writeframesraw(pcm)
            record = {"track": name, "elapsed": started_at - self.started_at,
                      "sample_offset": self.offsets[name], "samples": len(pcm) // 2,
                      **details}
            self.index.write(json.dumps(record) + "\n")
            self.offsets[name] += len(pcm) // 2

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                for track in self.tracks.values():
                    track.close()
                self.index.close()
