from .common import *
from .state import NodeState

class BridgeNode(Node):
    def __init__(self):
        super().__init__('voice_gateway')
        self.session_state = NodeState(self, 'bridge')
        self.inputs = self.create_publisher(ConversationInput, '/guidebot/conversation/input', QOS)
        self.contexts = self.create_publisher(InteractionContext, '/guidebot/interaction/context_input', STATE_QOS)
        self.transcripts = self.create_publisher(Transcript, '/guidebot/voice/transcript', QOS)
        self.control = self.create_client(SessionControl, '/guidebot/session/control',
                                          callback_group=ReentrantCallbackGroup())
        self.event_sub = self.create_subscription(GestureEvent, '/guidebot/gesture/events', self.receive_event, QOS)
        self.server = Server(ROOT/'ros.sock', self.rpc)

    def receive_event(self, event):
        if (event.session_id, event.generation) != (self.session_state.fence.session, self.session_state.fence.generation):
            return
        details = json.loads(event.diagnostic_json)
        with self.session_state.lock:
            self.session_state.events.append(dict(kind=event.kind, **details))
            self.session_state.events = self.session_state.events[-256:]
        if self.session_state.callback_slots.acquire(blocking=False):
            future = self.session_state.callbacks.submit(self.session_state.host,
                        dict(op='event', kind=event.kind, details=details))
            future.add_done_callback(lambda _: self.session_state.callback_slots.release())

    def rpc(self, request):
        op = request['op']
        if op == 'session' and request.get('command') == 'attach':
            self.session_state.fence.check(request['session_id'], request['generation'])
            return dict(accepted=True, state='active', reason='')
        if op == 'session':
            if not self.control.wait_for_service(timeout_sec=3):
                raise RuntimeError('Session service unavailable')
            fields = {k: request[k] for k in ('session_id','generation','command','mode')}
            result = wait(self.control.call_async(message(SessionControl.Request, fields)), 120)
            return to_dict(result)
        if op == 'input':
            self.inputs.publish(message(ConversationInput, request['event']))
            return {'published': True}
        if op == 'context':
            self.contexts.publish(message(InteractionContext, request['context']))
            return {'published': True}
        if op == 'transcript':
            self.transcripts.publish(message(Transcript, request['event']))
            return {'published': True}
        if op == 'events':
            with self.session_state.lock:
                return list(self.session_state.events)
        if op == 'health':
            return {'ready': self.inputs.get_subscription_count() > 0 and self.control.service_is_ready(),
                    'session': self.session_state.fence.session}
        raise ValueError('Unknown operation')
