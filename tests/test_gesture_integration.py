from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'GuideBot/conversation'))
from stepfun import RealtimeSession


class GestureIntegrationTests(unittest.TestCase):
    def session(self):
        value = RealtimeSession('dummy', Path('/tmp/unused-gesture-session'), gestures=True)
        self.assertEqual(value.timestamps.alignment_options,
                         dict(window=120., step=.5, tail=.1, resync_every=0., final_repair=True))
        self.assertEqual(value.timestamps.backend_options,
                         dict(threads=1, reuse_predictor=True, quantized=True, count_offset=-1))
        value.timestamps = Mock()
        value.gestures = Mock()
        value.speaker = Mock()
        value.report = Mock()
        value.active.add('r')
        return value

    def test_text_and_cloud_done_do_not_end_gestures_before_playback(self):
        session = self.session()
        session.on_event(dict(type='response.audio_transcript.delta', response_id='r', delta='请注意'))
        session.gestures.submit.assert_called_with('text_delta','r',text='请注意')
        session.on_event(dict(type='response.audio_transcript.done', response_id='r', transcript='请注意这里'))
        session.gestures.submit.assert_called_with('text','r',text='请注意这里')
        session.on_event(dict(type='response.done', response={'id':'r','status':'completed'}))
        session.gestures.submit.assert_called_with('done','r')
        self.assertFalse(any(call.args[0]=='cancel' for call in session.gestures.submit.call_args_list))

    def test_playback_clock_and_alignment_reach_gesture_adapter(self):
        session = self.session()
        session._playback_event('playback.started', response_id='r')
        session.gestures.submit.assert_called_with('playback','r',origin=session.playback_starts['r'])
        session._alignment_event('alignment.starts', response_id='r', version=1, anchors=[],
                                 changes=[], added_indices=[], total_units=4)
        self.assertEqual(session.gestures.submit.call_args.args, ('alignment',))
        self.assertEqual(session.gestures.submit.call_args.kwargs['version'], 1)
        session._playback_event('playback.drained_estimated', response_id='r')
        session.gestures.submit.assert_called_with('cancel','r',reason='playback.drained_estimated')

    def test_confirmed_interrupt_cancels_and_old_deltas_are_ignored(self):
        session = self.session()
        session.on_event(dict(type='input_audio_buffer.speech_interrupted', item_id='speech'))
        session.gestures.submit.assert_called_with('cancel','r',reason='confirmed_interrupt')
        session.gestures.submit.reset_mock()
        session.on_event(dict(type='response.audio_transcript.delta', response_id='r', delta='旧文本'))
        session.gestures.submit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
