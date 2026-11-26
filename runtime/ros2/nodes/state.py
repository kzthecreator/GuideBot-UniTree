"""Node-local session state, configured explicitly by the ROS session manager."""
from runtime.ros2.nodes.common import *


class NodeState:
    def __init__(self, node, role):
        self.node = node
        self.fence = Fence()
        self.mode = 'simulation'
        self.context = None
        self.context_version = self.context_expiry = 0
        self.callbacks = ThreadPoolExecutor(max_workers=2, thread_name_prefix=role+'-events')
        self.callback_slots = threading.BoundedSemaphore(128)
        self.lock = threading.Lock()
        self.events = []
        self.output = node.create_publisher(GestureEvent, '/guidebot/gesture/events', QOS)
        self.control = node.create_service(SessionControl, '/guidebot/internal/'+role+'/control',
                                          self.configure, callback_group=ReentrantCallbackGroup())
        if role == 'motion':
            self.context_sub = node.create_subscription(InteractionContext, '/guidebot/interaction/context',
                                                       self.accept_context, STATE_QOS)
            self.cancel_sub = node.create_subscription(ConversationInput, '/guidebot/conversation/input',
                                                      self.accept_cancel, QOS)

    def configure(self, request, result):
        if hasattr(self.node, 'session'):
            return self.node.session(request, result)
        try:
            if request.command == 'start':
                self.fence.start(request.session_id, request.generation)
                self.mode = request.mode
                self.context = None
                self.context_version = self.context_expiry = 0
            elif request.command == 'stop':
                self.fence.check(request.session_id, request.generation)
                self.fence.close()
            elif request.command != 'health':
                raise ValueError('Unknown control')
            result.accepted = True
            result.state = 'active' if self.fence.session else 'standby'
        except Exception as error:
            result.reason = type(error).__name__
        return result

    def accept_cancel(self, event):
        try:
            self.fence.check(event.session_id, event.generation)
            if event.kind == 'cancel':
                with self.fence.lock:
                    self.fence.closed.add(event.response_id)
        except ValueError:
            pass

    def accept_context(self, event):
        try:
            self.fence.check(event.session_id, event.generation)
            if event.version <= self.context_version or event.expires_monotonic <= time.monotonic():
                return
            self.context = context_from_wire(to_dict(event))
            self.context_version, self.context_expiry = event.version, event.expires_monotonic
        except ValueError:
            pass

    def host(self, value, timeout=8):
        return call(ROOT/'host.sock', dict(value, session_id=self.fence.session or '',
                                         generation=self.fence.generation), timeout)

    def notify(self, kind, details):
        fields = dict(session_id=self.fence.session or '', generation=self.fence.generation,
                      response_id=str(details.get('response_id') or ''), kind=kind,
                      action=str(details.get('action') or ''), job_id=str(details.get('job_id') or ''),
                      reason=str(details.get('reason') or ''),
                      diagnostic_json=json.dumps(details, ensure_ascii=False, default=str))
        self.output.publish(message(GestureEvent, fields))

    def close(self):
        self.fence.close()
        self.callbacks.shutdown(wait=False, cancel_futures=True)
