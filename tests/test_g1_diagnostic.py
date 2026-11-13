import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'GuideBot/conversation'))
from audio import AudioDiagnostic, StreamingSpeaker
from stepfun import RealtimeSession


class DiagnosticTests(unittest.TestCase):
    def test_wave_offsets_and_time_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recorder = AudioDiagnostic(root, 10)
            recorder.write('microphone', b'\x01\x00' * 160, 10.2)
            recorder.write('microphone', b'\x02\x00' * 80, 10.4)
            recorder.close()
            recorder.close()
            with wave.open(str(root / 'microphone-16k.wav')) as track:
                self.assertEqual(track.getnframes(), 240)
                self.assertEqual(track.getframerate(), 16000)
            records = [json.loads(line) for line in (root / 'audio-index.jsonl').read_text().splitlines()]
            self.assertEqual([r['sample_offset'] for r in records], [0, 160])
            self.assertAlmostEqual(records[1]['elapsed'], .4)

    def test_capture_records_unmodified_pcm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = RealtimeSession('dummy', root, diagnose_audio=True,
                                      aec=False, mic_gate_dbfs=None)
            session.audio_diagnostic = AudioDiagnostic(root, session.started_at)
            pcm = b'\x23\x01' * 2560
            with patch('stepfun.microphone_packets', return_value=iter([pcm])):
                session._capture()
            session.audio_diagnostic.close()
            with wave.open(str(root / 'microphone-16k.wav')) as track:
                self.assertEqual(track.readframes(2560), pcm)
            self.assertFalse(session.errors)

    def test_reference_matches_sdk_payload(self):
        stopping = threading.Event()
        sent, recorded, errors = [], [], []

        class Client:
            def SetTimeout(self, *_): pass
            def Init(self): pass
            def GetVolume(self): return (0, {'volume': 100})
            def PlayStop(self, *_): pass
            def PlayStream(self, app, stream, chunk):
                sent.append(chunk)
                return 0, ''

        def reference(pcm, started_at, **details):
            recorded.append((pcm, details))
            stopping.set()

        speaker = StreamingSpeaker(stopping, errors.append, chunk_ms=200,
                                   on_reference=reference)
        speaker.feed('response', b'\x01\x00' * 4800)
        speaker.finish('response')
        with patch('audio.load_audio_sdk', return_value=(lambda *_: None, Client)):
            speaker._run()
        self.assertFalse(errors)
        self.assertEqual(recorded[0][0], sent[0])
        self.assertEqual(recorded[0][1]['response_id'], 'response')
        self.assertEqual(recorded[0][1]['code'], 0)


if __name__ == '__main__':
    unittest.main()
