"""Real adapter/event ordering with fake audio and cloud: no microphone or robot."""
import base64
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from runtime.app.launcher import choose_service, parser, tour_command
from runtime.app.services import validate_options, build_session
from GuideBot.tour.assets import load_bundle
from GuideBot.tour.registration import prepare
from GuideBot.tour.session import TourSession
from GuideBot.configuration import read_prompt
from test.unit.tour.test_tour_registration import config, wav


class AdapterTests(unittest.TestCase):
    def session(self, tmp, **kwargs):
        cfg = config(Path(tmp)/'config'); root = Path(tmp)/'assets'
        client = MagicMock(); client.synthesize.return_value = wav()
        prepare(cfg, root, client=client)
        session = TourSession('test-only',Path(tmp)/'session',load_bundle(cfg,root),
            read_prompt('tour/prompt.md'),read_prompt('tour/context_template.md'),
            diagnose_audio=False,aec=False,agc=False,mic_gate_dbfs=None, **kwargs)
        session.ws = MagicMock()
        session.speaker = MagicMock()
        session.report = MagicMock()
        session._dispatch('start')
        return session

    def speech(self,s,turn):
        s._cloud_event(dict(type='input_audio_buffer.speech_started',item_id='u'+str(turn)))
        s._cloud_event(dict(type='input_audio_buffer.speech_interrupted',item_id='u'+str(turn)))
        s._cloud_event(dict(type='input_audio_buffer.speech_stopped',item_id='u'+str(turn)))
        s._cloud_event(dict(type='input_audio_buffer.committed',item_id='u'+str(turn)))
        s._cloud_event(dict(type='response.created',response={'id':'r'+str(turn)}))
        s._cloud_event(dict(type='response.audio.delta',response_id='r'+str(turn),
                            delta=base64.b64encode(b'\0\0'*240).decode()))

    def test_navigation_result_is_enqueued_before_tour_state_changes(self):
        from GuideBot.navigation.nav2 import Nav2Navigator
        with tempfile.TemporaryDirectory() as tmp:
            transport = MagicMock()
            s = self.session(tmp, navigator_factory=lambda notify: Nav2Navigator(
                transport, {'p1': dict(frame_id='map', x=1, y=0, yaw=0)}, notify))
            for _ in range(2):
                s._dispatch('playback_drained', response_id=s.tour.output_id)
            self.assertEqual(s.tour.phase, 'NAVIGATING')
            transport.send.call_args.args[1]('succeeded')
            self.assertEqual(s.tour.phase, 'NAVIGATING')
            kind, value = s.events.get_nowait()
            self.assertEqual(kind, 'navigation')
            s._dispatch(value['kind'], **value['fields'])
            self.assertEqual(s.tour.point['id'], 'p1')
            self.assertEqual(s.tour.phase, 'NARRATING')
            s._dispatch('stop')

    def test_candidate_keeps_narration_until_cloud_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.session(tmp)
            original = s.tour.output_id
            s._cloud_event(dict(type='input_audio_buffer.speech_started', item_id='u1'))
            s.speaker.interrupt.assert_not_called()
            self.assertEqual(s.tour.output_id, original)
            s._cloud_event(dict(type='input_audio_buffer.speech_interrupted', item_id='u1'))
            s.speaker.interrupt.assert_called_once()
            self.assertIsNone(s.tour.output_id)
            self.assertEqual(s.tour.interaction, 'INTERRUPT_PENDING')

    def test_unconfirmed_commit_reply_and_timeout_do_not_stop_narration(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.session(tmp)
            original = s.tour.output_id
            s._cloud_event(dict(type='input_audio_buffer.speech_started', item_id='u1'))
            s._cloud_event(dict(type='input_audio_buffer.committed', item_id='u1'))
            s._cloud_event(dict(type='response.created', response={'id': 'unconfirmed'}))
            s._cloud_event(dict(type='response.audio.delta', response_id='unconfirmed', delta='invalid'))
            s._dispatch('candidate_timeout', turn=1)
            s.speaker.interrupt.assert_not_called()
            self.assertEqual(s.tour.output_id, original)
            self.assertIn('unconfirmed', s.discarded)
            self.assertIsNone(s.tour.answer_id)
            s._dispatch('playback_drained', response_id=original)
            self.assertNotEqual(s.tour.output_id, original)

    def test_local_audio_and_reply_use_same_output_and_drain_controls_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.session(tmp)
            self.assertTrue(s.speaker.feed.called)
            local_id = s.tour.output_id
            self.speech(s,1)
            s.speaker.interrupt.assert_called_once()
            self.assertEqual(s.speaker.feed.call_args.args[0],'r1')
            s._cloud_event(dict(type='response.done',response={'id':'r1','status':'completed'}))
            self.assertEqual(s.tour.interaction,'ANSWERING')
            self.assertEqual(s.tour.segment_index,0)
            s._dispatch('playback_drained',response_id=local_id)
            self.assertEqual(s.tour.interaction,'ANSWERING')
            s._dispatch('playback_drained',response_id='r1')
            self.assertEqual(s.tour.interaction,'LISTENING')
            self.assertEqual(s.speaker.feed.call_args.args[0],s.tour.output_id)
            prompts = [json.loads(c.args[0])['session']['instructions'] for c in s.ws.send.call_args_list
                       if json.loads(c.args[0])['type'] == 'session.update']
            self.assertTrue(all(p.startswith(read_prompt('tour/prompt.md')) for p in prompts))
            self.assertTrue(any('欢迎来到我们的展厅' in p for p in prompts))
            self.assertIsNone(s.vector_store_id)
            self.assertIsNone(s.gestures)

    def test_late_confirmation_and_old_audio_do_not_kill_current_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.session(tmp); self.speech(s,1); self.speech(s,2)
            calls = s.speaker.feed.call_count
            interrupts = s.speaker.interrupt.call_count
            s._cloud_event(dict(type='input_audio_buffer.speech_interrupted',item_id='u1'))
            s._cloud_event(dict(type='response.audio.delta',response_id='r1',delta='not-base64'))
            self.assertEqual(s.speaker.feed.call_count,calls)
            self.assertEqual(s.speaker.interrupt.call_count,interrupts)
            self.assertEqual(s.tour.answer_id,'r2')

    def test_duplicate_cloud_turn_events_are_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.session(tmp); self.speech(s,1)
            s._cloud_event(dict(type='input_audio_buffer.speech_started',item_id='u1'))
            s._cloud_event(dict(type='response.created',response={'id':'r1'}))
            self.assertEqual(s.tour.answer_id,'r1')
            self.assertEqual(s.current_turn,1)
            self.assertNotIn('r1',s.discarded)
            before = s.tour.snapshot()
            s._cloud_event(dict(type='input_audio_buffer.committed',item_id='unknown-old'))
            s._cloud_event(dict(type='conversation.item.input_audio_transcription.completed',
                                item_id='unknown-old',transcript='暂停'))
            self.assertEqual(s.tour.snapshot(),before)

    def test_transcribed_pause_is_preserved_until_explicit_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.session(tmp); self.speech(s,1)
            s._cloud_event(dict(type='conversation.item.input_audio_transcription.completed',
                                item_id='u1',transcript='暂停讲解。'))
            s._cloud_event(dict(type='response.done',response={'id':'r1','status':'completed'}))
            s._dispatch('playback_drained',response_id='r1')
            self.assertEqual(s.tour.phase,'PAUSED')
            self.assertIsNone(s.tour.output_id)
            s._dispatch('resume')
            self.assertEqual(s.tour.phase,'NARRATING')

    def test_cloud_callback_only_enqueues_and_queue_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.session(tmp)
            with patch.object(s,'_cloud_event',side_effect=AssertionError('Receive callback blocked')):
                s.on_event(dict(type='session.created'))
                self.assertEqual(s.events.get_nowait()[0],'cloud')
            s.events = queue.Queue(maxsize=1)
            s.fail = MagicMock()
            s.on_event({'type':'a'});s.on_event({'type':'b'})
            s.fail.assert_called_once()

    def test_single_consumer_control_and_shutdown_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = self.session(tmp)
            s.directory.mkdir()
            s.tour_log = (s.directory/'tour-events.jsonl').open('w')
            s.control_ready.set()
            s.tour_thread = threading.Thread(target=s._tour_loop)
            s.tour_thread.start()
            try:
                self.assertEqual(s.control('pause')['phase'],'PAUSED')
                self.assertEqual(s.control('resume')['phase'],'NARRATING')
                with self.assertRaises(ValueError):s.control('arrived',point_id='p1')
                s.stopping.set();s.tour_thread.join(timeout=2)
                self.assertFalse(s.tour_thread.is_alive())
                self.assertEqual(s.last_snapshot['phase'],'STOPPED')
                state = json.loads((s.directory/'tour-checkpoint.json').read_text())
                self.assertEqual(state['phase'],'STOPPED')
            finally:
                s.stopping.set();s.tour_thread.join(timeout=2);s.tour_log.close()

    def test_entry_selection_options_and_factory_keep_services_separate(self):
        with patch('builtins.input',side_effect=['bad','2']):
            self.assertEqual(choose_service(),'tour')
        with patch('builtins.input',side_effect=EOFError):
            with self.assertRaises(RuntimeError):choose_service()
        args = parser().parse_args(['--service','tour','--no-diagnose-audio'])
        self.assertEqual(validate_options(vars(args)),'tour')
        for option in ('gestures','gesture_backend','timestamps','sync_knowledge_before_start'):
            with self.assertRaises(ValueError):validate_options(dict(service='tour',**{option:True}))
        self.assertEqual(tour_command('arrived p1 task'),dict(command='arrived',fields=dict(point_id='p1',task_id='task')))
        with self.assertRaises(ValueError):tour_command('walk p1')
        with patch('GuideBot.conversation.session.build_session') as factory:
            build_session(dict(service='conversation'),Path('/tmp'),{},None)
            factory.assert_called_once()
        with patch('GuideBot.tour.session.TourSession') as factory:
            data = dict(secret='test',prompt='tour-only',context_template='visible',bundle={
                'definition':{'speech':{'voice':'cixingnansheng'}}})
            build_session(dict(service='tour'),Path('/tmp'),data,MagicMock())
            self.assertEqual(factory.call_args.args[3],'tour-only')
            self.assertTrue(factory.call_args.kwargs['aec'])
            self.assertTrue(factory.call_args.kwargs['agc'])
            self.assertNotIn('gesture_service_factory',factory.call_args.kwargs)
