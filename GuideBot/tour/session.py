"""Managed tour session: single event consumer, shared listening/AEC/speaker."""
from pathlib import Path
import queue
import threading
import time

from GuideBot.conversation.realtime import ServiceRealtimeSession
from GuideBot.conversation.output import play_segment
from GuideBot.tour.context import render, spoken_command
from GuideBot.tour.controller import TourController
from GuideBot.tour.navigation import ManualNavigator
from GuideBot.tour.registration import atomic_json


class TourSession(ServiceRealtimeSession):
    def __init__(self, secret, directory, bundle, prompt, context_template, navigator_factory=None, **kwargs):
        self.events = queue.Queue(maxsize=512)
        self.tour_thread = None
        self.bundle = bundle
        self.tour = TourController(bundle['definition']['points'], bundle['definition']['bundle_id'])
        self.context_template = context_template
        self.base_prompt = prompt
        self.navigator = (navigator_factory(lambda kind, **fields: self._enqueue(
            'navigation', dict(kind=kind, fields=fields))) if navigator_factory else ManualNavigator())
        self.candidate_deadline = self.answer_deadline = None
        self.last_context = None
        self.transcribed_items = set()
        self.last_snapshot = self.tour.snapshot()
        self.tour_log = None
        self.control_ready = threading.Event()
        # Verify editable context before opening any device.
        render(context_template, self.tour)
        initial = prompt+'\n\n'+render(context_template, self.tour)
        self.last_context = initial
        super().__init__(secret, Path(directory), instructions=initial, vector_store_id=None, **kwargs)

    def start(self):
        if self.tour_thread is not None:
            raise RuntimeError('Create a new TourSession for each activation')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.tour_log = (self.directory/'tour-events.jsonl').open('w', encoding='utf-8')
        self.tour_thread = threading.Thread(target=self._tour_loop, name='tour-controller', daemon=True)
        self.tour_thread.start()
        super().start()

    def on_event(self, event):
        self._enqueue('cloud', event)

    def _enqueue(self, kind, value):
        if self.stopping.is_set(): return
        try:
            self.events.put_nowait((kind, value))
        except queue.Full:
            self.fail(RuntimeError('Tour event queue exceeded limit'))

    def _playback_event(self, kind, **details):
        super()._playback_event(kind, **details)
        if kind == 'playback.drained_estimated':
            self._enqueue('drained', details)

    def control(self, command, **fields):
        if not self.control_ready.is_set() or self.stopping.is_set():
            raise RuntimeError('Tour is not active')
        reply = queue.Queue(maxsize=1)
        self._enqueue('control', dict(command=command, fields=fields, reply=reply))
        try:
            success, result = reply.get(timeout=3)
        except queue.Empty:
            raise RuntimeError('Tour control timed out') from None
        if not success: raise ValueError(result)
        return result

    def _dispatch(self, kind, **fields):
        before = self.tour.snapshot()
        effects = self.tour.dispatch(kind, **fields)
        for effect in effects:
            action = effect['kind']
            if action == 'interrupt':
                active = self.active-self.discarded
                self.discarded.update(self.active)
                self.speaker.interrupt(reason="tour_"+kind)
                if active:
                    self._send('response.cancel')
            elif action == 'context':
                context = self.base_prompt+'\n\n'+render(self.context_template, self.tour)
                if context != self.last_context:
                    self._send('session.update', session={'instructions': context})
                    self.last_context = context
            elif action == 'narrate':
                play_segment(self.speaker, self.bundle, effect['key'], effect['response_id'])
                self.report('tour.narrating', self.tour.point['name'],
                            point_id=self.tour.point['id'], segment_index=self.tour.segment_index)
            elif action == 'navigate':
                self.navigator.go_to(effect['point_id'], effect['task_id'])
                self.report('tour.awaiting_arrival',
                            '请移动到下一讲解点；到达后输入 arrived '+effect['point_id'],
                            point_id=effect['point_id'], task_id=effect['task_id'])
            elif action == 'cancel_navigation':
                self.navigator.cancel()
            elif action == 'discard_answer':
                self.discarded.add(effect['response_id'])
            elif action == 'completed':
                self.report('tour.completed', '全部讲解点已完成；仍可提问，按 Enter 退出。')
        after = self.tour.snapshot()
        self.last_snapshot = after
        if not self.tour.answer_id:
            self.answer_deadline = None
        if before != after and self.tour_log is not None:
            import json
            self.tour_log.write(json.dumps(dict(event=kind, elapsed=time.monotonic()-self.started_at,
                                               **after), ensure_ascii=False)+'\n')
            self.tour_log.flush()
            atomic_json(self.directory/'tour-checkpoint.json', after)
        if after['phase'] == 'PAUSED' and before['phase'] != 'PAUSED':
            self.report('tour.paused', '导览已暂停；输入 resume 继续。', reason=after['reason'])

    def _cloud_event(self, event):
        kind = event['type']
        if (kind == 'input_audio_buffer.speech_started' and event.get('item_id')
                and event['item_id'] in self.user_turns):
            return
        if kind == 'response.created' and event['response']['id'] in self.response_numbers:
            return
        if (kind in {'input_audio_buffer.speech_stopped', 'input_audio_buffer.committed',
                     'input_audio_buffer.speech_backchannel',
                     'conversation.item.input_audio_transcription.completed'}
                and event.get('item_id') and event['item_id'] not in self.user_turns):
            return
        if kind == 'input_audio_buffer.speech_interrupted':
            item = event.get('item_id')
            turn = self.user_turns.get(item)
            if turn != self.tour.turn or item in self.confirmed_interruptions:
                return
            self.confirmed_interruptions.add(item)
            self.report('VAD-interrupt', '云端确认打断，停止输出；麦克风继续上传', turn=turn)
            self._dispatch('speech_interrupted', turn=turn)
            self.answer_deadline = None
            return
        if kind == 'response.created':
            rid = event['response']['id']
            super().on_event(event)
            turn = self.response_turns.get(rid, 0)
            self._dispatch('answer_started', response_id=rid, turn=turn)
            if self.tour.answer_id == rid:
                self.candidate_deadline = None
                self.answer_deadline = time.monotonic()+120
            return
        if kind.startswith('response.audio'):
            rid = event.get('response_id')
            if rid != self.tour.answer_id: return
            if kind == 'response.audio.delta':
                self._dispatch('answer_audio', response_id=rid)
                self.answer_deadline = time.monotonic()+120
        if kind == 'response.done':
            rid = event['response']['id']
            current = rid == self.tour.answer_id
            super().on_event(event)
            if current:
                self._dispatch('answer_done', response_id=rid, status=event['response'].get('status'))
            return
        if kind == 'error':
            code = event.get('error', {}).get('code')
            if code in {'response_cancel_not_active', 'response_cancel_not_found'}:
                self.report('tour.cancel_already_done', '旧回答已结束，无需再次取消。')
                return
        super().on_event(event)
        if self.stopping.is_set(): return
        if kind == 'session.updated' and self.ready.is_set() and not self.control_ready.is_set():
            self.control_ready.set()
            self._dispatch('start')
        elif kind == 'input_audio_buffer.speech_started':
            self._dispatch('speech_started', turn=self.current_turn)
            self.candidate_deadline = time.monotonic()+120
        elif kind in {'input_audio_buffer.speech_stopped', 'input_audio_buffer.committed'}:
            turn = self.user_turns.get(event.get('item_id'), self.current_turn)
            self._dispatch('speech_stopped' if kind.endswith('speech_stopped') else 'committed', turn=turn)
            if turn == self.tour.turn and self.tour.interaction == 'INTERRUPT_PENDING':
                self.candidate_deadline = time.monotonic()+(45 if self.tour.committed else 6)
        elif kind == 'input_audio_buffer.speech_backchannel':
            turn = self.user_turns.get(event.get('item_id'), self.current_turn)
            self._dispatch('backchannel', turn=turn)
        elif kind == 'conversation.item.input_audio_transcription.completed':
            turn = self.user_turns.get(event.get('item_id'), self.current_turn)
            item = event.get('item_id')
            if item in self.transcribed_items: return
            if item: self.transcribed_items.add(item)
            if turn == self.tour.turn:
                command = spoken_command(event.get('transcript', ''))
                if command: self._dispatch(command)

    def _handle_control(self, value):
        try:
            command, fields = value['command'], value['fields']
            if command == 'arrived':
                self._dispatch('arrived', **self.navigator.arrived(fields['point_id'], fields.get('task_id')))
            elif command in {'pause','resume'}:
                self._dispatch(command)
            elif command != 'status':
                raise ValueError('Unknown tour command')
            value['reply'].put((True, self.tour.snapshot()))
        except (ValueError, KeyError) as error:
            value['reply'].put((False, str(error)))

    def _tour_loop(self):
        try:
            while not self.stopping.is_set():
                try:
                    kind, value = self.events.get(timeout=.1)
                except queue.Empty:
                    kind, value = None, None
                if kind == 'cloud': self._cloud_event(value)
                elif kind == 'drained': self._dispatch('playback_drained', **{
                    'response_id': value['response_id']})
                elif kind == 'control': self._handle_control(value)
                elif kind == 'navigation': self._dispatch(value['kind'], **value['fields'])
                now = time.monotonic()
                if self.candidate_deadline and now >= self.candidate_deadline:
                    self.candidate_deadline = None
                    self._dispatch('candidate_timeout', turn=self.tour.turn)
                if self.answer_deadline and now >= self.answer_deadline:
                    self.answer_deadline = None
                    self._dispatch('answer_timeout', response_id=self.tour.answer_id)
        except Exception as error:
            self.fail(error)
        finally:
            self._dispatch('stop')

    def stop(self):
        self.control_ready.clear()
        self.stopping.set()
        if self.tour_thread and self.tour_thread is not threading.current_thread():
            self.tour_thread.join(timeout=5)
        result = super().stop()
        if self.tour_thread and self.tour_thread.is_alive():
            self.errors.append('Tour controller did not stop within 5s')
            result['errors'] = list(self.errors)
        elif self.tour_log:
            self.tour_log.close()
            self.tour_log = None
        result['service'] = 'tour'
        result['tour'] = self.last_snapshot
        return result
