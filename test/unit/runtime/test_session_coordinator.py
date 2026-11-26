"""Lifecycle policy remains usable without importing ROS or robot modules."""
from types import SimpleNamespace
import unittest

from runtime.orchestrator.session import SessionCoordinator, ROLES


class Coordinator(SessionCoordinator):
    def __init__(self):
        self.initialize_session(offline=True, managed_resources=True)
        self.operations = []
        self.fail_worker = False

    def node_control(self, role, command):
        self.operations.append((role, command))

    def worker(self, op, timeout=60):
        self.operations.append(('worker', op))
        if self.fail_worker and op == 'activate':
            raise RuntimeError('fixture activation failure')
        return dict(active=True, failed=False)

    def host_heartbeat(self):
        self.operations.append(('host', 'heartbeat'))

    def log_health_error(self, message):
        self.operations.append(('error', message))

    def control(self, command, session='session', generation=1, mode='voice'):
        request = SimpleNamespace(command=command, session_id=session,
                                  generation=generation, mode=mode)
        result = SimpleNamespace(accepted=False, state='', reason='')
        return self.control_session(request, result)


class SessionCoordinatorTests(unittest.TestCase):
    def test_start_health_stop_and_duplicate_stop(self):
        value = Coordinator()
        self.assertTrue(value.control('start').accepted)
        self.assertEqual(value.operations, [(role, 'start') for role in ROLES] + [('worker', 'activate')])
        value.check_health()
        self.assertIn(('host', 'heartbeat'), value.operations)
        self.assertTrue(value.control('stop').accepted)
        self.assertEqual(value.state, 'standby')
        before = list(value.operations)
        self.assertTrue(value.control('stop').accepted)
        self.assertEqual(value.operations, before)
        self.assertFalse(value.control('start').accepted)

    def test_activation_failure_unwinds_all_nodes(self):
        value = Coordinator()
        value.fail_worker = True
        self.assertFalse(value.control('start').accepted)
        self.assertEqual(value.state, 'fault')
        self.assertEqual(value.operations[-4:], [('worker', 'deactivate')] +
                         [(role, 'stop') for role in reversed(ROLES)])
        self.assertIsNone(value.session_id)

    def test_wrong_session_cannot_stop_active_resources(self):
        value = Coordinator()
        value.control('start')
        before = list(value.operations)
        self.assertFalse(value.control('stop', session='stale').accepted)
        self.assertEqual(value.state, 'active')
        self.assertEqual(value.operations, before)

    def test_offline_mode_cannot_activate_robot(self):
        value = Coordinator()
        self.assertFalse(value.control('start', mode='robot').accepted)
        self.assertEqual(value.operations, [])
