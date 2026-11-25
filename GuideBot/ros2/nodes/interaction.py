from .common import *
from .state import NodeState

class InteractionNode(Node):
    """Accept only explicit structured sources; do not infer facts from model speech."""
    def __init__(self):
        super().__init__('interaction_manager')
        self.session_state = NodeState(self, 'interaction')
        self.output = self.create_publisher(InteractionContext, '/guidebot/interaction/context', STATE_QOS)
        self.input = self.create_subscription(InteractionContext, '/guidebot/interaction/context_input',
                                              self.accept, STATE_QOS)

    def accept(self, value):
        try:
            self.session_state.fence.check(value.session_id, value.generation)
            if value.source not in {'operator','scene_config','navigation','task_manager','dialogue_manager'}:
                raise ValueError('Untrusted context source')
            if value.expires_monotonic <= time.monotonic():
                raise ValueError('Expired context source')
            self.output.publish(value)
        except ValueError:
            self.session_state.notify('gesture.context_rejected', {'reason':'untrusted_or_expired_context_source'})
