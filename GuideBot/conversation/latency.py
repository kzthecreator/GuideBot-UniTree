"""Cloud speech-end receipt to first speaker submission (software proxy)."""
import threading


class ReplyLatency:
    def __init__(self):
        self.ends = {}
        self.recorded = set()
        self.lock = threading.Lock()

    def speech_end(self, turn, now):
        with self.lock:
            self.ends[turn] = now

    def playback_start(self, response_id, turn, now):
        with self.lock:
            if response_id in self.recorded or turn not in self.ends:
                return None
            self.recorded.add(response_id)
            seconds = now-self.ends[turn]
            if seconds < 0:
                return None
            return dict(response_id=response_id, turn=turn, latency_seconds=seconds,
                        speech_end_monotonic=self.ends[turn], reply_start_monotonic=now,
                        measurement='cloud_speech_stopped_received_to_first_speaker_submission',
                        note='Starts on receipt of cloud speech-end event; excludes preceding detection/delivery delay. Ends at software speaker event, not audible sound.')
