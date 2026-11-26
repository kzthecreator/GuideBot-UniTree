import unittest
from GuideBot.conversation.latency import ReplyLatency


class LatencyTests(unittest.TestCase):
    def test_turn_matching_and_duplicate_playback(self):
        tracker=ReplyLatency()
        tracker.speech_end(1,10.)
        tracker.speech_end(2,12.)
        result=tracker.playback_start('old',1,13.)
        self.assertEqual(result['latency_seconds'],3.)
        self.assertIsNone(tracker.playback_start('old',1,14.))
        self.assertEqual(tracker.playback_start('new',2,14.)['latency_seconds'],2.)
        self.assertIsNone(tracker.playback_start('unknown',3,14.))
