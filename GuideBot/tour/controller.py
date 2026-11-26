"""Pure event-driven tour state machine; no sockets, files, audio, or navigation I/O."""
import uuid


class TourController:
    def __init__(self, points, bundle_id, session_id=None):
        if not points or any(not p['segments'] for p in points):
            raise ValueError('Tour needs registered points with audio segments')
        self.points, self.bundle_id = points, bundle_id
        self.session_id = session_id or uuid.uuid4().hex
        self.phase, self.interaction = 'READY', 'LISTENING'
        self.point_index = self.segment_index = self.sequence = self.turn = 0
        self.output_id = self.answer_id = self.nav_task = None
        self.nav_target = None
        self.voice_active = self.committed = self.answer_done = self.answer_drained = False
        self.answer_audio = False
        self.resume_phase = 'NARRATING'
        self.reason = None

    @property
    def point(self):
        return self.points[self.point_index]

    def token(self, prefix):
        self.sequence += 1
        return '{}-{}-{}'.format(prefix, self.session_id, self.sequence)

    def snapshot(self):
        return dict(session_id=self.session_id, bundle_id=self.bundle_id, phase=self.phase,
                    interaction=self.interaction, point_id=self.point['id'],
                    segment_index=self.segment_index, output_id=self.output_id,
                    answer_id=self.answer_id, turn=self.turn, nav_task=self.nav_task,
                    nav_target=self.nav_target, reason=self.reason)

    def _play(self):
        self.output_id = self.token('tour')
        segment = self.point['segments'][self.segment_index]
        return [dict(kind='context'), dict(kind='narrate', response_id=self.output_id,
                                          key=segment['key'])]

    def _resume(self):
        self.interaction = 'LISTENING'
        self.output_id = self.answer_id = None
        self.voice_active = self.committed = False
        self.answer_done = self.answer_drained = self.answer_audio = False
        if self.phase == 'NARRATING':
            return self._play()
        return [dict(kind='context')]

    def _pause(self, reason):
        if self.phase != 'PAUSED': self.resume_phase = self.phase
        self.phase, self.reason = 'PAUSED', reason
        self.interaction = 'LISTENING'
        self.voice_active = self.committed = False
        self.output_id = self.answer_id = None
        return [dict(kind='interrupt'), dict(kind='context')]

    def dispatch(self, kind, **event):
        if self.phase == 'STOPPED': return []
        if kind == 'stop':
            self.phase, self.interaction = 'STOPPED', 'LISTENING'
            self.output_id = self.answer_id = self.nav_task = self.nav_target = None
            return [dict(kind='interrupt'), dict(kind='cancel_navigation')]
        if kind == 'fault':
            self.phase, self.reason = 'FAULT', event.get('reason', 'service_failure')
            self.output_id = self.answer_id = None
            return [dict(kind='interrupt'), dict(kind='cancel_navigation')]
        if self.phase == 'FAULT': return []
        if kind == 'start' and self.phase == 'READY':
            self.phase = 'NARRATING'
            return self._play()
        if self.phase == 'READY': return []
        if kind == 'speech_started':
            if event['turn'] <= self.turn: return []
            self.turn = event['turn']
            self.voice_active, self.committed = True, False
            return []
        if kind == 'speech_interrupted':
            if event['turn'] != self.turn: return []
            if self.interaction == 'INTERRUPT_PENDING': return []
            self.interaction = 'INTERRUPT_PENDING'
            self.output_id = self.answer_id = None
            self.answer_done = self.answer_drained = self.answer_audio = False
            return [dict(kind='interrupt'), dict(kind='context')]
        if kind == 'speech_stopped' and event['turn'] == self.turn:
            self.voice_active = False
            return []
        if kind == 'committed' and event['turn'] == self.turn:
            self.committed = True
            self.voice_active = False
            return []
        if kind == 'backchannel' and event['turn'] == self.turn:
            if self.interaction == 'INTERRUPT_PENDING' and not self.committed:
                return self._resume()
            return []
        if kind == 'candidate_timeout' and event['turn'] == self.turn:
            if self.interaction != 'INTERRUPT_PENDING': return []
            if self.committed or self.voice_active:
                return self._pause('input_or_answer_timeout')
            return self._resume()
        if kind == 'answer_started':
            if (event['turn'] != self.turn or self.interaction != 'INTERRUPT_PENDING'
                    or self.voice_active):
                return [dict(kind='discard_answer', response_id=event['response_id'])]
            self.answer_id = self.output_id = event['response_id']
            self.interaction = 'ANSWERING'
            self.answer_done = self.answer_drained = self.answer_audio = False
            self.committed = True
            self.voice_active = False
            return []
        if kind == 'answer_audio' and event['response_id'] == self.answer_id:
            self.answer_audio = True
            return []
        if kind == 'answer_done' and event['response_id'] == self.answer_id:
            if event['status'] != 'completed' or not self.answer_audio:
                self.answer_id = None
                self.interaction = 'LISTENING'
                return self._pause('answer_failed_or_empty')
            self.answer_done = True
            if self.answer_drained: return self._resume()
            return []
        if kind == 'answer_timeout' and self.answer_id and event.get('response_id') == self.answer_id:
            self.answer_id = None
            self.interaction = 'LISTENING'
            return self._pause('answer_timeout')
        if kind == 'playback_drained':
            rid = event['response_id']
            if rid != self.output_id: return []
            if rid == self.answer_id:
                self.answer_drained = True
                if self.answer_done: return self._resume()
                return []
            if self.phase != 'NARRATING' or self.interaction != 'LISTENING': return []
            self.output_id = None
            self.segment_index += 1
            if self.segment_index < len(self.point['segments']): return self._play()
            if self.point_index+1 == len(self.points):
                self.phase = 'COMPLETED'
                return [dict(kind='context'), dict(kind='completed')]
            self.phase = 'NAVIGATING'
            self.nav_target = self.points[self.point_index+1]['id']
            self.nav_task = self.token('nav')
            return [dict(kind='context'), dict(kind='navigate', point_id=self.nav_target,
                                              task_id=self.nav_task)]
        if kind == 'arrived':
            if (not self.nav_task or event['task_id'] != self.nav_task or event['point_id'] != self.nav_target
                    or self.phase not in {'NAVIGATING','PAUSED'}): return []
            paused = self.phase == 'PAUSED'
            self.nav_task = self.nav_target = None
            self.point_index += 1
            self.segment_index = 0
            if paused:
                self.resume_phase = 'NARRATING'
                return [dict(kind='context')]
            self.phase = 'NARRATING'
            if self.interaction == 'LISTENING': return self._play()
            return [dict(kind='context')]
        if kind == 'navigation_failed' and self.nav_task and event['task_id'] == self.nav_task:
            return self._pause('navigation_failed')
        if kind == 'pause':
            # During an answer keep the answer, but suppress subsequent narration.
            if self.phase != 'PAUSED': self.resume_phase = self.phase
            self.phase, self.reason = 'PAUSED', 'user_pause'
            navigation = [dict(kind='cancel_navigation')] if self.resume_phase == 'NAVIGATING' else []
            if self.interaction == 'LISTENING':
                self.output_id = None
                return navigation + [dict(kind='interrupt'), dict(kind='context')]
            return navigation + [dict(kind='context')]
        if kind == 'resume' and self.phase == 'PAUSED':
            self.phase, self.reason = self.resume_phase, None
            if self.phase == 'NAVIGATING' and self.nav_task:
                return [dict(kind='navigate', point_id=self.nav_target, task_id=self.nav_task)]
            if self.interaction == 'LISTENING' and self.phase == 'NARRATING': return self._play()
            return [dict(kind='context')]
        return []
