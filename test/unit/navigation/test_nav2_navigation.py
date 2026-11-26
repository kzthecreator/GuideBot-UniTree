"""Navigation seams only: no DDS, SDK, motion or cloud."""
import unittest
from unittest.mock import Mock
from GuideBot.navigation.nav2 import Nav2Navigator, validate_waypoints
from test.unit.tour.test_tour_controller import controller


class Nav2Tests(unittest.TestCase):
    def navigator(self):
        self.transport = Mock()
        self.transport.send.return_value = object()
        self.events = []
        return Nav2Navigator(self.transport, {'p1': dict(frame_id='map',x=1,y=2,yaw=0)},
                             lambda kind, **fields: self.events.append((kind, fields)))

    def test_arrival_requires_success_not_goal_acceptance(self):
        n = self.navigator();n.go_to('p1','task')
        self.assertEqual(self.events, [])
        self.transport.send.call_args.args[1]('succeeded')
        self.assertEqual(self.events,[('arrived',dict(point_id='p1',task_id='task'))])
        self.transport.send.call_args.args[1]('succeeded')
        self.assertEqual(len(self.events),1)

    def test_cancel_fences_old_success_and_resume_resends_same_task(self):
        n = self.navigator();n.go_to('p1','task')
        old_done = self.transport.send.call_args.args[1]
        n.go_to('p1','task');self.assertEqual(self.transport.send.call_count,1)
        n.cancel();self.transport.cancel.assert_called_once()
        n.go_to('p1','task');old_done('succeeded')
        self.assertEqual(self.events,[])
        self.transport.send.call_args.args[1]('succeeded')
        self.assertEqual(len(self.events),1)

    def test_failure_never_marks_arrival_and_close_ignores_late_results(self):
        for status in ['rejected','aborted','canceled','unknown']:
            n=self.navigator();n.go_to('p1','task')
            self.transport.send.call_args.args[1](status)
            self.assertEqual(self.events[0][0],'navigation_failed')
        n=self.navigator();n.go_to('p1','task');callback=self.transport.send.call_args.args[1]
        n.close();callback('succeeded');self.assertEqual(self.events,[])
        with self.assertRaises(RuntimeError):n.go_to('p1','task')
        with self.assertRaises(ValueError):n.arrived('p1','task')

    def test_unknown_pose_nonfinite_and_send_failure_fail_closed(self):
        n=self.navigator()
        with self.assertRaises(ValueError):n.go_to('missing','task')
        for x in [float('nan'),float('inf'),True,'1']:
            with self.assertRaises(ValueError):validate_waypoints({'p':dict(frame_id='map',x=x,y=0,yaw=0)})
        self.transport.send.side_effect=RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):n.go_to('p1','task')
        self.assertIsNone(n.pending)

    def test_tour_goal_result_reaches_next_narration_and_pause_cancels(self):
        c=controller()
        for _ in range(2):c.dispatch('playback_drained',response_id=c.output_id)
        task=c.nav_task
        effects=c.dispatch('pause')
        self.assertIn(dict(kind='cancel_navigation'),effects)
        self.assertEqual(c.dispatch('resume')[-1],dict(kind='navigate',point_id='p1',task_id=task))
        n=self.navigator();n.notify=lambda kind,**fields:c.dispatch(kind,**fields)
        n.go_to('p1',task);self.transport.send.call_args.args[1]('succeeded')
        self.assertEqual(c.point_index,1)
        self.assertEqual(c.phase,'NARRATING')

    def test_transport_is_not_replaced_while_active(self):
        n=self.navigator();n.go_to('p1','old')
        with self.assertRaises(RuntimeError):n.go_to('p1','new')

    def test_ros_transport_cancels_goal_accepted_after_cancellation(self):
        from runtime.ros2.adapters.nav2 import RosNav2Transport
        transport=RosNav2Transport.__new__(RosNav2Transport)
        handle=Mock();handle.accepted=True
        future=Mock();future.result.return_value=handle
        ticket=dict(handle=None,canceled=False,done=Mock())
        transport.cancel(ticket)
        transport._accepted(ticket,future)
        handle.cancel_goal_async.assert_called_once()
        ticket['done'].assert_not_called()
