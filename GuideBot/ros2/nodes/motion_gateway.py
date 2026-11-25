from .common import *
from .state import NodeState

class MotionNode(Node):
    def __init__(self):
        super().__init__('motion_gateway')
        self.session_state = NodeState(self, 'motion')
        self.lock = threading.Lock()
        self.goal_busy = False
        self.catalog = Catalog()
        self.states = self.create_publisher(MotionState, '/guidebot/motion/state', STATE_QOS)
        self.server = ActionServer(self, ExecuteGesture, '/guidebot/motion/execute_gesture',
                                   self.execute, callback_group=ReentrantCallbackGroup(),
                                   goal_callback=self.accept, cancel_callback=lambda _: CancelResponse.ACCEPT)

    def accept(self, goal):
        try:
            if not math.isfinite(goal.start_monotonic) or goal.start_monotonic > goal.arrival_monotonic:
                raise ValueError('Invalid motion time')
            if goal.action == 'neutral':
                if not goal.scheduler_managed or goal.has_duration:
                    raise ValueError('Base pose must be scheduler managed')
            else:
                row = dict(action=goal.action, start_unit=0, arrival_unit=0)
                if goal.has_duration:
                    row['duration_s'] = goal.duration_s
                # Recheck public ROS goals independently of model output.
                self.catalog.validate(row, [0], [], enforce_context=False)
            with self.lock:
                if self.goal_busy:
                    return GoalResponse.REJECT
                self.session_state.fence.job(goal.session_id, goal.generation, goal.job_id,
                                      goal.response_id, goal.arrival_monotonic)
                self.goal_busy = True
            return GoalResponse.ACCEPT
        except ValueError:
            return GoalResponse.REJECT

    def execute(self, handle):
        goal = handle.request
        result = ExecuteGesture.Result()
        result.estimated = True
        result.holds_end_pose = True
        try:
            self.session_state.fence.check(goal.session_id, goal.generation)
            item = self.catalog.definitions.get(goal.action)
            context = self.session_state.context if self.session_state.context_expiry > time.monotonic() else None
            if item is None or not Catalog.context_allows(item, context):
                raise ValueError('Execution context rejected')
            event = dict(action=goal.action, job_id=goal.job_id, response_id=goal.response_id,
                         start_monotonic=goal.start_monotonic,
                         arrival_monotonic=goal.arrival_monotonic,
                         scheduler_managed=goal.scheduler_managed)
            if goal.has_duration:
                event['duration_s'] = goal.duration_s
            self.session_state.host({'op':'execute', 'event':event})
            feedback = ExecuteGesture.Feedback(phase='accepted_by_native', estimated=True)
            handle.publish_feedback(feedback)
            minimum = goal.arrival_monotonic + (goal.duration_s if goal.has_duration else 0)
            deadline = minimum + 10
            saw_busy = False
            while time.monotonic() < deadline:
                cancelled = (handle.is_cancel_requested or self.session_state.fence.session != goal.session_id
                             or goal.response_id in self.session_state.fence.closed)
                if cancelled:
                    self.session_state.host({'op':'stop_motion'})
                    result.outcome = 'cancelled_stop_requested'
                    if handle.is_cancel_requested:
                        handle.canceled()
                    else:
                        handle.abort()
                    return result
                status = self.session_state.host({'op':'motion_status'})
                state = status.get('state', 'unknown')
                ownership = status.get('ownership', 'unknown')
                self.states.publish(message(MotionState, dict(session_id=goal.session_id,
                    generation=goal.generation, job_id=goal.job_id, ownership=ownership,
                    state=state, simulated=self.session_state.mode == 'simulation', estimated=True,
                    observed_monotonic=time.monotonic())))
                if ownership != 'owned':
                    raise ValueError('Ownership lost')
                if state != 'idle' and not saw_busy:
                    handle.publish_feedback(ExecuteGesture.Feedback(phase='native_running', estimated=True))
                saw_busy |= state != 'idle'
                if saw_busy and state == 'idle' and time.monotonic() >= minimum:
                    result.success = True
                    result.outcome = 'native_idle_end_pose_held'
                    handle.succeed()
                    return result
                time.sleep(.05)
            raise TimeoutError('Motion completion timed out')
        except Exception as error:
            result.reason = type(error).__name__
            result.outcome = 'failed'
            try:
                self.session_state.host({'op':'stop_motion'})
            except Exception:
                pass
            handle.abort()
        finally:
            with self.lock:
                self.goal_busy = False
        return result
