from .common import *
from .state import NodeState

class RemotePlanner:
    model = 'ROS2/DeepSeek'
    def __init__(self, node, shared):
        self.node, self.session_state = node, shared
        self.client = ActionClient(node, PlanGestures, '/guidebot/gesture/plan',
                                   callback_group=ReentrantCallbackGroup())

    def plan(self, payload, on_action, cancelled):
        shared = self.session_state
        if not self.client.wait_for_server(timeout_sec=5):
            raise RuntimeError('ROS planner unavailable')
        request = PlanGestures.Goal()
        request.input = planning_message(payload, shared.fence.session, shared.fence.generation,
                                         shared.context_version, shared.context_expiry)
        def feedback(value):
            if not cancelled.is_set():
                on_action(plan_from_message(value.feedback.candidate))
        goal = wait(self.client.send_goal_async(request, feedback_callback=feedback))
        if not goal.accepted:
            raise RuntimeError('ROS planner rejected goal')
        future = goal.get_result_async()
        deadline = time.monotonic() + 50
        while not future.done():
            if cancelled.wait(.03) or time.monotonic() >= deadline:
                wait(goal.cancel_goal_async())
                return {'cancelled': True}
        result = future.result().result
        if result.error:
            raise RuntimeError('ROS planning failed: ' + result.error)
        return dict(valid_actions=result.valid_actions, invalid_actions=result.invalid_actions,
                    invalid_reasons=list(result.invalid_reasons), cancelled=result.cancelled)

class ROSMotionExecutor:
    def __init__(self, node, shared):
        self.session_state = shared
        self.mode = shared.mode
        self.active = None
        self.client = ActionClient(node, ExecuteGesture, '/guidebot/motion/execute_gesture',
                                   callback_group=ReentrantCallbackGroup())
        self.lock = threading.Lock()

    def handle(self, kind, event):
        if kind == 'gesture.reset':
            with self.lock:
                goal, self.active = self.active, None
            if goal is not None:
                wait(goal.cancel_goal_async())
            # Also covers a completed static-pose goal still holding its end pose.
            self.session_state.host({'op':'stop_motion'})
            return {'mode': self.mode, 'cancel_requested': True}
        if kind != 'gesture.command':
            return None
        if not self.client.wait_for_server(timeout_sec=3):
            raise ValueError('ROS motion unavailable')
        request = ExecuteGesture.Goal()
        fields = dict(session_id=self.session_state.fence.session, generation=self.session_state.fence.generation,
                      response_id=str(event.get('response_id', '')), job_id=event['job_id'],
                      action=event['action'], start_monotonic=event['start_monotonic'],
                      arrival_monotonic=event['arrival_monotonic'],
                      has_duration='duration_s' in event, duration_s=float(event.get('duration_s', 0)),
                      scheduler_managed=event.get('scheduler_managed', False))
        request = message(ExecuteGesture.Goal, fields)
        goal = wait(self.client.send_goal_async(request))
        if not goal.accepted:
            raise ValueError('ROS motion goal rejected')
        with self.lock:
            self.active = goal
        future = goal.get_result_async()
        def completed(value):
            result = value.result().result
            self.session_state.notify('gesture.execution_result', dict(job_id=event['job_id'],
                               action=event['action'], response_id=event.get('response_id'),
                               success=result.success, outcome=result.outcome, reason=result.reason,
                               estimated=result.estimated, holds_end_pose=result.holds_end_pose))
        future.add_done_callback(completed)
        return {'mode': self.mode, 'accepted': True, 'job_id': event['job_id']}

class SchedulerNode(Node):
    def __init__(self):
        super().__init__('gesture_scheduler')
        self.session_state, self.service = NodeState(self, 'scheduler'), None
        self.group = ReentrantCallbackGroup()
        # Session control is registered by NodeState under the internal scheduler endpoint.
        self.input = self.create_subscription(ConversationInput, '/guidebot/conversation/input',
                                             self.consume, QOS)
        self.context_sub = self.create_subscription(InteractionContext, '/guidebot/interaction/context',
                                                   self.accept_context, STATE_QOS)
        self.events = self.create_publisher(GestureEvent, '/guidebot/gesture/events', QOS)
        self.context_timer = self.create_timer(.1, self.expire)
        self.last_heartbeat = 0

    def emit(self, kind, **details):
        self.session_state.notify(kind, details)

    def session(self, request, result):
        try:
            if request.command == 'start':
                if request.mode not in {'simulation','robot','voice'}:
                    raise ValueError('Invalid mode')
                if os.environ.get('GUIDEBOT_ROS_OFFLINE') == '1' and request.mode == 'robot':
                    raise ValueError('Offline graph cannot command robot')
                if request.mode != 'voice' and os.environ.get('GUIDEBOT_ROS_OFFLINE') != '1' and not os.environ.get('DEEPSEEK_API_KEY'):
                    raise ValueError('Planner key missing')
                self.session_state.fence.start(request.session_id, request.generation)
                self.session_state.mode = request.mode
                self.session_state.context_version = 0
                self.session_state.context_expiry = 0
                self.session_state.context = None
                if request.mode == 'voice':
                    result.accepted, result.state = True, 'active'
                    return result
                catalog = Catalog()
                planner = RemotePlanner(self, self.session_state)
                self.service = GestureService(Path(os.environ['GUIDEBOT_SESSION_DIR']), self.emit,
                            catalog=catalog, planner=planner, execution_mode=request.mode)
                # Keep timing profiles and policy unchanged; only transport differs.
                self.service.executor = ROSMotionExecutor(self, self.session_state)
                self.service.start()
            elif request.command == 'stop':
                self.session_state.fence.check(request.session_id, request.generation)
                if self.service:
                    self.service.close()
                    self.service = None
                self.session_state.fence.close()
            elif request.command != 'health':
                raise ValueError('Unknown session command')
            result.accepted = True
            result.state = 'active' if self.service else 'standby'
        except Exception as error:
            result.reason = type(error).__name__
            if request.command == 'start':
                self.session_state.fence.close()
        return result

    def consume(self, event):
        try:
            self.session_state.fence.input(event.session_id, event.generation, event.sequence,
                                    event.kind, event.response_id)
            details = {}
            if event.kind in {'text', 'text_delta'}:
                details['text'] = event.text
            elif event.kind == 'alignment':
                details = dict(version=event.alignment_version,
                               anchors=[to_dict(a) for a in event.anchors])
            elif event.kind == 'playback':
                details['origin'] = event.origin
            elif event.kind in {'cancel','base_pose'}:
                details['reason'] = event.reason
            elif event.kind == 'release_pose':
                details['condition'] = event.reason
            if self.service is not None:
                self.service.submit(event.kind, event.response_id or None, **details)
            self.emit('gesture.transport_received', response_id=event.response_id,
                      sequence=event.sequence, latency_ms=max(0., (time.monotonic()-event.queued_monotonic)*1000))
        except Exception as error:
            self.emit('gesture.input_rejected', response_id=event.response_id,
                      reason=type(error).__name__)

    def accept_context(self, event):
        try:
            self.session_state.fence.check(event.session_id, event.generation)
            if event.version <= self.session_state.context_version or event.expires_monotonic <= time.monotonic():
                raise ValueError('Stale context')
            context = context_from_wire(to_dict(event))
            if self.service is not None:
                self.service.set_interaction_context(context)
            self.session_state.context = context
            self.session_state.context_version = event.version
            self.session_state.context_expiry = event.expires_monotonic
        except Exception as error:
            self.emit('gesture.context_rejected', reason=type(error).__name__)

    def expire(self):
        if self.service and self.session_state.context_expiry and time.monotonic() >= self.session_state.context_expiry:
            self.session_state.context = None
            self.session_state.context_expiry = 0
            self.service.set_interaction_context(None)
            self.emit('gesture.context_expired')
        if self.service and time.monotonic() - self.last_heartbeat > .3:
            self.last_heartbeat = time.monotonic()
            # Host watchdog does not depend on this executor remaining alive.
            self.session_state.callbacks.submit(self.session_state.host, {'op':'heartbeat'})
