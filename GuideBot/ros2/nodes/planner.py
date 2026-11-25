from .common import *
from .state import NodeState

class PlanningNode(Node):
    def __init__(self):
        super().__init__('gesture_planner')
        self.session_state = NodeState(self, 'planner')
        self.catalog = Catalog()
        self.planner = Planner(self.catalog)
        self.group = ReentrantCallbackGroup()
        self.server = ActionServer(self, PlanGestures, '/guidebot/gesture/plan',
                                   self.execute, callback_group=self.group,
                                   goal_callback=self.accept,
                                   cancel_callback=lambda _: CancelResponse.ACCEPT)

    def accept(self, request):
        try:
            self.session_state.fence.check(request.input.session_id, request.input.generation)
            return GoalResponse.ACCEPT
        except ValueError:
            return GoalResponse.REJECT

    def execute(self, goal):
        result = PlanGestures.Result()
        cancellation = threading.Event()
        def feedback(plan):
            if goal.is_cancel_requested:
                cancellation.set()
                return
            value = PlanGestures.Feedback()
            value.candidate = plan_message(plan)
            goal.publish_feedback(value)
        try:
            payload = planning_payload(goal.request.input)
            if os.environ.get('GUIDEBOT_ROS_OFFLINE') == '1':
                # Fixed planner only in explicitly offline graphs; never invokes cloud.
                plan = self.catalog.validate({'action':'greet_open', 'start_unit':0,
                                              'arrival_unit':len(payload['units'])-1}, payload['eligible_anchor_ids'],
                                             payload['targets'], payload['interaction_context'])
                if not payload['existing_actions']:
                    feedback(plan)
                stats = {'valid_actions': 1, 'invalid_actions': 0}
            else:
                # Monitor cancel independently of blocking provider I/O.
                stop = threading.Event()
                def monitor():
                    while not stop.wait(.05):
                        if goal.is_cancel_requested or self.session_state.fence.session is None:
                            cancellation.set()
                thread = threading.Thread(target=monitor, daemon=True)
                thread.start()
                try:
                    stats = self.planner.plan(payload, feedback, cancellation)
                finally:
                    stop.set()
                    thread.join(timeout=1)
            result.success = not cancellation.is_set()
            result.cancelled = cancellation.is_set()
            result.valid_actions = stats.get('valid_actions', 0)
            result.invalid_actions = stats.get('invalid_actions', 0)
            result.invalid_reasons = stats.get('invalid_reasons', [])
            if goal.is_cancel_requested:
                goal.canceled()
            else:
                goal.succeed()
        except Exception as error:
            result.error = type(error).__name__
            goal.abort()
        return result
