from .common import *
from .state import NodeState

class OfflinePlanner:
    """Fixed local planner, selected only by the explicit offline test runtime."""
    model = 'offline/fixed'

    def __init__(self, catalog):
        self.catalog = catalog

    def plan(self, payload, on_action, cancelled):
        if cancelled.is_set():
            return {'cancelled': True}
        row = {'action':'greet_open', 'start_unit':0, 'arrival_unit':len(payload['units'])-1}
        # The explicit offline alignment harness still exercises legacy anchors.
        if os.environ.get('GUIDEBOT_GESTURE_TIMING_MODE') != 'aligned':
            row.update(start_s=payload.get('playback_elapsed_s', 0.),
                       end_s=payload.get('playback_elapsed_s', 0.)+6.)
        plan = self.catalog.validate(row,
            payload['eligible_anchor_ids'], payload['targets'], payload['interaction_context'])
        if not payload['existing_actions'] and not cancelled.is_set():
            on_action(plan)
        return {'valid_actions':1, 'invalid_actions':0, 'cancelled':cancelled.is_set()}


class ROSMotionExecutor:
    def __init__(self, node, shared, on_result=None):
        self.session_state = shared
        self.mode = shared.mode
        self.active = None
        self.client = ActionClient(node, ExecuteGesture, '/guidebot/motion/execute_gesture',
                                   callback_group=ReentrantCallbackGroup())
        self.lock = threading.Lock()
        self.on_result = on_result

    def handle(self, kind, event):
        if kind == 'gesture.reset' or (kind == 'gesture.command' and event.get('end_monotonic')):
            with self.lock:
                goal, self.active = self.active, None
            if goal is not None:
                wait(goal.cancel_goal_async())
                # A cancel acknowledgement precedes Motion releasing its busy slot.
                # Wait for execution to stop before submitting the listening pose.
                wait(goal.get_result_async())
            # Also covers a completed static-pose goal still holding its end pose.
            self.session_state.host({'op':'stop_motion'})
            deadline = time.monotonic() + 3
            while self.session_state.host({'op':'motion_status'}).get('state') != 'idle':
                if time.monotonic() >= deadline:
                    raise ValueError('Motion did not become idle after cancellation')
                time.sleep(.01)
            if kind == 'gesture.reset':
                return {'mode': self.mode, 'cancel_requested': True}
        if kind != 'gesture.command':
            return None
        if not self.client.wait_for_server(timeout_sec=3):
            raise ValueError('ROS motion unavailable')
        if event.get('end_monotonic') and time.monotonic() >= event['end_monotonic']:
            raise ValueError('Action end deadline passed after braking')
        request = ExecuteGesture.Goal()
        fields = dict(session_id=self.session_state.fence.session, generation=self.session_state.fence.generation,
                      response_id=str(event.get('response_id', '')), job_id=event['job_id'],
                      action=event['action'], start_monotonic=event['start_monotonic'],
                      arrival_monotonic=event['arrival_monotonic'],
                      end_monotonic=event.get('end_monotonic', 0.),
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
            if self.on_result is not None:
                self.on_result('execution_result',
                    job_id=event['job_id'], success=result.success, reason=result.reason)
            self.session_state.notify('gesture.execution_result', dict(job_id=event['job_id'],
                               action=event['action'], response_id=event.get('response_id'),
                               success=result.success, outcome=result.outcome, reason=result.reason,
                               estimated=result.estimated, holds_end_pose=result.holds_end_pose))
        future.add_done_callback(completed)
        return {'mode': self.mode, 'accepted': True, 'job_id': event['job_id']}

class GestureNode(Node):
    def __init__(self):
        super().__init__('gesture')
        self.session_state, self.service = NodeState(self, 'gesture'), None
        self.group = ReentrantCallbackGroup()
        # Session control is registered by NodeState under the internal gesture endpoint.
        self.input = self.create_subscription(ConversationInput, '/guidebot/conversation/input',
                                             self.consume, QOS)
        self.contexts = self.create_publisher(InteractionContext, '/guidebot/interaction/context', STATE_QOS)
        self.context_sub = self.create_subscription(InteractionContext, '/guidebot/interaction/context_input',
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
                planner = (OfflinePlanner(catalog) if os.environ.get('GUIDEBOT_ROS_OFFLINE') == '1'
                           else Planner(catalog))
                self.service = GestureService(Path(os.environ['GUIDEBOT_SESSION_DIR']), self.emit,
                            catalog=catalog, planner=planner, execution_mode=request.mode)
                self.service.executor = ROSMotionExecutor(self, self.session_state,
                                                          on_result=self.service.submit)
                self.service.start()
            elif request.command == 'stop':
                self.session_state.fence.check(request.session_id, request.generation)
                if self.service:
                    self.service.close(wait=False)
                    self.service = None
                self.session_state.fence.close()
            elif request.command != 'health':
                raise ValueError('Unknown session command')
            result.accepted = True
            result.state = 'active' if self.session_state.fence.session else 'standby'
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
            if event.source not in {'operator','scene_config','navigation','task_manager','dialogue_manager'}:
                raise ValueError('Untrusted context source')
            if event.version <= self.session_state.context_version or event.expires_monotonic <= time.monotonic():
                raise ValueError('Stale context')
            context = context_from_wire(to_dict(event))
            if self.service is not None:
                self.service.set_interaction_context(context)
            self.session_state.context = context
            self.session_state.context_version = event.version
            self.session_state.context_expiry = event.expires_monotonic
            self.contexts.publish(event)
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
