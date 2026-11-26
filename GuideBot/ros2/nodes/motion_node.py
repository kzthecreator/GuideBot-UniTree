from .common import *
from .state import NodeState

class MotionNode(Node):
    def __init__(self):
        super().__init__('motion')
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
            row = dict(action=goal.action, start_unit=0, arrival_unit=0)
            if goal.end_monotonic:
                if (not math.isfinite(goal.end_monotonic) or
                    goal.end_monotonic <= max(time.monotonic(), goal.start_monotonic)):
                    raise ValueError('Action end deadline passed')
                row.update(start_s=0., end_s=goal.end_monotonic-goal.start_monotonic)
            if goal.has_duration:
                row['duration_s'] = goal.duration_s
            self.catalog.validate(row, [0], [], enforce_context=False)
            if goal.timing_mode == 'semantic_keyframes':
                from GuideBot.gesture.timing import phases
                _, minimum, hold = phases(self.catalog.assets[goal.action])
                if (not goal.end_monotonic or not math.isfinite(goal.core_s) or not math.isfinite(goal.hold_s)
                        or not minimum <= goal.core_s <= 600 or not hold <= goal.hold_s <= 300):
                    raise ValueError('Invalid semantic phases')
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
            if goal.timing_mode == 'semantic_keyframes':
                event.update(timing_mode=goal.timing_mode, core_s=goal.core_s, hold_s=goal.hold_s)
            if goal.end_monotonic:
                event['end_monotonic'] = goal.end_monotonic
            if goal.has_duration:
                event['duration_s'] = goal.duration_s
            execution = self.session_state.host({'op':'execute', 'event':event})
            if execution.get('accepted') is False:
                result.reason = execution['reason']
                result.outcome = 'timing_rejected'
                self.session_state.notify('gesture.timing_rejected', dict(
                    job_id=goal.job_id, action=goal.action, response_id=goal.response_id,
                    **{key:execution[key] for key in ('reason', 'remaining_s', 'minimum_required_s')}))
                handle.abort()
                return result
            feedback = ExecuteGesture.Feedback(phase='accepted_by_native', estimated=True)
            handle.publish_feedback(feedback)
            minimum = (0. if goal.end_monotonic else
                       goal.arrival_monotonic + (goal.duration_s if goal.has_duration else 0))
            deadline = goal.end_monotonic + 1 if goal.end_monotonic else minimum + 10
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
                execution = status.get('execution') or {}
                if execution.get('job_id') == goal.job_id:
                    if execution.get('state') == 'rejected':
                        result.reason = execution.get('reason', 'native_rejected')
                        result.outcome = 'native_rejected'
                        handle.abort()
                        return result
                    saw_busy |= execution.get('state') in {'running', 'completed'}
                if state != 'idle' and not saw_busy:
                    handle.publish_feedback(ExecuteGesture.Feedback(phase='native_running', estimated=True))
                saw_busy |= state != 'idle'
                if saw_busy and state == 'idle' and time.monotonic() >= minimum:
                    result.success = True
                    result.outcome = 'native_idle_end_pose_held'
                    handle.succeed()
                    return result
                if goal.end_monotonic and time.monotonic() >= goal.end_monotonic and state != 'idle':
                    raise TimeoutError('Action end deadline exceeded')
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
