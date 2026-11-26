"""Explicit manual arrival adapter. This module never moves the robot."""
class ManualNavigator:
    def __init__(self):
        self.target = self.task_id = None

    def go_to(self, point_id, task_id):
        self.target, self.task_id = point_id, task_id

    def arrived(self, point_id, task_id=None):
        if not self.task_id or point_id != self.target or (task_id and task_id != self.task_id):
            raise ValueError('Arrival does not match the pending navigation task')
        event = dict(point_id=self.target, task_id=self.task_id)
        self.cancel()
        return event

    def cancel(self):
        self.target = self.task_id = None
