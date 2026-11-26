"""Deterministic tour transitions, interruption races and manual arrival fencing."""
import unittest
from GuideBot.tour.controller import TourController
from GuideBot.tour.context import render, spoken_command
from GuideBot.tour.navigation import ManualNavigator


def controller():
    points = [dict(id='p0', name='第一点',script='甲。乙。',segments=[
        dict(key='a',text='甲。'),dict(key='b',text='乙。')]),
        dict(id='p1',name='第二点',script='丙。',segments=[dict(key='c',text='丙。')])]
    c = TourController(points, 'bundle', 'test'); c.dispatch('start')
    return c


def interrupt(c, turn=1):
    c.dispatch('speech_started', turn=turn)
    c.dispatch('speech_interrupted', turn=turn)
    c.dispatch('speech_stopped', turn=turn)
    c.dispatch('committed', turn=turn)
    c.dispatch('answer_started', response_id='answer'+str(turn),turn=turn)
    c.dispatch('answer_audio', response_id='answer'+str(turn))


class ControllerTests(unittest.TestCase):
    def test_point_playback_manual_arrival_and_final_completion(self):
        c = controller()
        first = c.output_id
        c.dispatch('playback_drained', response_id=first)
        self.assertEqual(c.segment_index, 1)
        c.dispatch('playback_drained', response_id=first)  # stale duplicate
        self.assertEqual(c.segment_index, 1)
        c.dispatch('playback_drained', response_id=c.output_id)
        self.assertEqual(c.phase, 'NAVIGATING')
        task = c.nav_task
        c.dispatch('arrived',point_id='p1',task_id='old-task')
        self.assertEqual(c.phase, 'NAVIGATING')
        c.dispatch('arrived',point_id='p1',task_id=task)
        self.assertEqual(c.point_index, 1)
        c.dispatch('playback_drained', response_id=c.output_id)
        self.assertEqual(c.phase,'COMPLETED')
        c.dispatch('arrived',point_id='p1',task_id=task)
        self.assertEqual(c.point_index, 1)

    def test_answer_done_is_not_playback_done_and_resume_restarts_only_current_sentence(self):
        c = controller(); c.dispatch('playback_drained',response_id=c.output_id)
        interrupted = c.output_id
        interrupt(c)
        c.dispatch('playback_drained',response_id=interrupted)
        self.assertEqual(c.segment_index,1)
        c.dispatch('answer_done',response_id='answer1',status='completed')
        self.assertEqual(c.interaction,'ANSWERING')
        c.dispatch('playback_drained',response_id='answer1')
        self.assertEqual(c.interaction,'LISTENING')
        self.assertEqual(c.segment_index,1)
        self.assertTrue(c.output_id.startswith('tour-'))

    def test_audio_drain_can_precede_cloud_done(self):
        c = controller(); interrupt(c)
        c.dispatch('playback_drained',response_id='answer1')
        self.assertEqual(c.interaction,'ANSWERING')
        c.dispatch('answer_done',response_id='answer1',status='completed')
        self.assertEqual(c.interaction,'LISTENING')

    def test_repeated_interruption_ignores_old_answers(self):
        c = controller(); interrupt(c,1); interrupt(c,2)
        c.dispatch('answer_done',response_id='answer1',status='completed')
        c.dispatch('playback_drained',response_id='answer1')
        self.assertEqual(c.answer_id,'answer2')
        c.dispatch('answer_done',response_id='answer2',status='completed')
        c.dispatch('playback_drained',response_id='answer2')
        self.assertEqual(c.segment_index,0)
        self.assertEqual(c.interaction,'LISTENING')

    def test_pause_command_during_answer_survives_answer_completion(self):
        c = controller(); interrupt(c)
        c.dispatch('pause')
        c.dispatch('answer_done',response_id='answer1',status='completed')
        c.dispatch('playback_drained',response_id='answer1')
        self.assertEqual(c.phase,'PAUSED'); self.assertIsNone(c.output_id)
        c.dispatch('resume')
        self.assertEqual(c.phase,'NARRATING'); self.assertTrue(c.output_id)

    def test_arrival_while_answering_is_deferred_until_answer_drain(self):
        c = controller()
        for _ in range(2): c.dispatch('playback_drained',response_id=c.output_id)
        task = c.nav_task; interrupt(c)
        c.dispatch('arrived',point_id='p1',task_id=task)
        self.assertEqual(c.phase,'NARRATING'); self.assertEqual(c.output_id,'answer1')
        c.dispatch('answer_done',response_id='answer1',status='completed')
        actions = c.dispatch('playback_drained',response_id='answer1')
        self.assertEqual(actions[-1]['key'],'c')

    def test_false_candidate_recovers_but_unanswered_commit_pauses(self):
        c = controller(); c.dispatch('speech_started',turn=1)
        c.dispatch('speech_stopped',turn=1)
        c.dispatch('candidate_timeout',turn=1)
        self.assertEqual(c.phase,'NARRATING'); self.assertTrue(c.output_id)
        c.dispatch('speech_started',turn=2); c.dispatch('speech_interrupted',turn=2); c.dispatch('committed',turn=2)
        c.dispatch('candidate_timeout',turn=2)
        self.assertEqual(c.phase,'PAUSED')
        c.dispatch('resume')
        self.assertTrue(c.output_id)

    def test_empty_or_failed_answer_never_automatically_resumes(self):
        c = controller(); c.dispatch('speech_started',turn=1); c.dispatch('speech_interrupted',turn=1); c.dispatch('committed',turn=1)
        c.dispatch('answer_started',response_id='empty',turn=1)
        c.dispatch('answer_done',response_id='empty',status='completed')
        self.assertEqual(c.phase,'PAUSED')
        self.assertIsNone(c.output_id)

    def test_no_unsolicited_answer_and_stopped_ignores_events(self):
        c = controller()
        effects = c.dispatch('answer_started',response_id='unsolicited',turn=0)
        self.assertEqual(effects,[dict(kind='discard_answer',response_id='unsolicited')])
        c.dispatch('stop'); state = c.snapshot()
        c.dispatch('speech_started',turn=2); c.dispatch('resume')
        self.assertEqual(c.snapshot(),state)

    def test_manual_arrival_and_visible_context_rules(self):
        nav = ManualNavigator(); nav.go_to('p1','task')
        with self.assertRaises(ValueError): nav.arrived('p0')
        with self.assertRaises(ValueError): nav.arrived('p1','stale')
        self.assertEqual(nav.arrived('p1'),dict(point_id='p1',task_id='task'))
        with self.assertRaises(ValueError): nav.arrived('p1')
        c = controller()
        self.assertEqual(render('{point_name}: {current_text}',c),'第一点: 甲。')
        with self.assertRaises(ValueError): render('{point_name.__class__}',c)
        self.assertIsNone(spoken_command('不要暂停讲解'))
        self.assertEqual(spoken_command('暂停讲解。'),'pause')
