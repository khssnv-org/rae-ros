"""Check launch events and camera readiness; requires the ROS Python packages."""

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from launch import LaunchContext, LaunchDescription, LaunchService
    from launch.actions import EmitEvent, ExecuteProcess, OpaqueFunction
    from launch.event_handlers import OnProcessExit
    from launch.events import Shutdown
    from rae_hw import pwm_launch
    HAS_ROS = True
except ImportError:
    HAS_ROS = False


def load_file(name, path):
    """Import a launch or executable module without starting its main function."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(HAS_ROS, 'ROS Python packages are unavailable')
class PwmLaunchTest(unittest.TestCase):
    """Exercise actual Humble launch actions with fake hardware operations."""

    def setUp(self):
        """Replace only the hardware lease, preserving launch event types."""
        self.context = LaunchContext()
        self.session = Mock(camera_failed=False)
        self.session.read_register.return_value = 0
        patcher = patch.object(pwm_launch, 'PwmStartup', return_value=self.session)
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(pwm_launch.atexit, 'register')
        patcher.start()
        self.addCleanup(patcher.stop)

    def gate(self):
        """Capture callbacks while constructing real launch event handlers."""
        self.camera = ExecuteProcess(cmd=['/bin/true'])
        self.marker = OpaqueFunction(function=lambda context: [])
        with patch.object(pwm_launch, 'OnProcessExit', wraps=OnProcessExit) as handlers:
            self.actions = pwm_launch.guarded_camera(
                self.context, self.camera, 'rae', on_ready=[self.marker])
        self.camera_exit = handlers.call_args_list[0].kwargs['on_exit']
        self.ready = handlers.call_args_list[1].kwargs['on_exit']

    def test_context_shares_one_lease(self):
        self.assertIs(pwm_launch.hardware_session(self.context), self.session)
        self.assertIs(pwm_launch.hardware_session(self.context), self.session)
        self.factory.assert_called_once_with()

    def test_simulation_and_mock_never_access_hardware(self):
        for flag in ('sim', 'sim_mode', 'mock', 'use_sim_time'):
            context = LaunchContext()
            context.launch_configurations[flag] = 'true'
            with self.subTest(flag=flag), self.assertRaisesRegex(RuntimeError, 'simulation'):
                pwm_launch.hardware_session(context)
        self.factory.assert_not_called()

    def test_success_requires_reset_before_control(self):
        self.gate()
        self.assertNotIn(self.marker, self.actions)
        self.assertEqual(self.actions[2], self.camera)
        result = self.ready(SimpleNamespace(returncode=0), self.context)
        self.session.finish_camera.assert_called_once_with()
        self.assertIn(self.marker, result)

    def test_readiness_failure_never_resets_or_starts_control(self):
        self.gate()
        result = self.ready(SimpleNamespace(returncode=1), self.context)
        self.session.finish_camera.assert_not_called()
        self.assertNotIn(self.marker, result)
        self.assertTrue(any(isinstance(action, EmitEvent) for action in result))

    def test_reset_error_never_starts_control(self):
        self.gate()
        self.session.finish_camera.side_effect = subprocess.CalledProcessError(1, 'busybox')
        result = self.ready(SimpleNamespace(returncode=0), self.context)
        self.assertNotIn(self.marker, result)
        self.assertTrue(self.session.camera_failed)

    def test_camera_exit_prevents_late_success(self):
        self.gate()
        self.camera_exit(SimpleNamespace(returncode=1), self.context)
        result = self.ready(SimpleNamespace(returncode=0), self.context)
        self.assertEqual(result, [])
        self.session.finish_camera.assert_not_called()

    def test_shutdown_prevents_late_success(self):
        self.gate()
        self.context._set_is_shutdown(True)
        self.assertEqual(self.ready(SimpleNamespace(returncode=0), self.context), [])
        self.session.finish_camera.assert_not_called()

    def test_launch_service_process_order(self):
        for status in (0, 1):
            with self.subTest(status=status):
                trace = []
                self.session.camera_failed = False
                self.session.finish_camera.side_effect = lambda: trace.append('reset')
                service = LaunchService()
                camera = ExecuteProcess(cmd=['/bin/sleep', '30'])
                waiter = ExecuteProcess(cmd=['/bin/sh', '-c', f'exit {status}'])

                def motors(context):
                    trace.append('motors')
                    return [EmitEvent(event=Shutdown(reason='test complete'))]

                with patch.object(pwm_launch, 'Node', return_value=waiter):
                    actions = pwm_launch.guarded_camera(
                        service.context, camera, 'rae',
                        on_ready=[OpaqueFunction(function=motors)])
                service.include_launch_description(LaunchDescription(actions))
                service.run()
                self.assertEqual(trace, ['reset', 'motors'] if status == 0 else [])

    def test_control_failure_returns_no_nodes(self):
        control = load_file('control_launch', Path(__file__).resolve().parents[1]
                            / 'launch/control.launch.py')
        with patch.object(control, 'hardware_session', return_value=self.session), \
                patch.object(control.xacro, 'process_file') as xacro:
            self.session.start_motors.side_effect = RuntimeError('reset failed')
            with self.assertRaisesRegex(RuntimeError, 'reset failed'):
                control.launch_setup(self.context)
            xacro.assert_not_called()

    def test_control_rechecks_before_controller_manager(self):
        control = load_file('control_launch', Path(__file__).resolve().parents[1]
                            / 'launch/control.launch.py')
        self.context.launch_configurations.update({
            'controller_params_file': '/unused/controller.yaml', 'namespace': ''})
        with patch.object(control, 'hardware_session', return_value=self.session), \
                patch.object(control, 'OpaqueFunction', wraps=OpaqueFunction) as opaque:
            control.launch_setup(self.context)
            callback = opaque.call_args.kwargs['function']
        self.session.initialize.side_effect = RuntimeError('PWM changed')
        with self.assertRaisesRegex(RuntimeError, 'PWM changed'):
            callback(self.context)

    def test_spawners_are_serialized_and_fail_closed(self):
        control = load_file('control_launch', Path(__file__).resolve().parents[1]
                            / 'launch/control.launch.py')
        self.context.launch_configurations.update({
            'controller_params_file': '/unused/controller.yaml', 'namespace': ''})
        with patch.object(control, 'hardware_session', return_value=self.session), \
                patch.object(control, 'OpaqueFunction', wraps=OpaqueFunction) as opaque:
            control.launch_setup(self.context)
            callback = opaque.call_args.kwargs['function']
        with patch.object(control, 'OnProcessExit', wraps=OnProcessExit) as handlers:
            actions = callback(self.context)
        start_diff = handlers.call_args_list[0].kwargs['on_exit']
        check_diff = handlers.call_args_list[1].kwargs['on_exit']
        diff = handlers.call_args_list[1].kwargs['target_action']
        self.assertNotIn(diff, actions)
        self.assertEqual(start_diff(SimpleNamespace(returncode=0), self.context), [diff])
        self.assertEqual(check_diff(SimpleNamespace(returncode=0), self.context), [])
        for handler in (start_diff, check_diff):
            failed = handler(SimpleNamespace(returncode=1), self.context)
            self.assertTrue(any(isinstance(action, EmitEvent) for action in failed))
        self.session.read_register.return_value = 0x1FFFFFFF
        failed = start_diff(SimpleNamespace(returncode=0), self.context)
        self.assertNotIn(diff, failed)
        self.assertTrue(any(isinstance(action, EmitEvent) for action in failed))


@unittest.skipUnless(HAS_ROS, 'ROS Python packages are unavailable')
class CameraReadinessTest(unittest.TestCase):
    """Require configured camera services before the checked PWM reset."""

    def setUp(self):
        """Use a fake client without DDS or a physical camera."""
        self.module = load_file('wait_for_camera', Path(__file__).resolve().parents[1]
                                / 'scripts/wait_for_camera.py')
        self.node = Mock()
        self.client = self.node.create_client.return_value

    def test_configuration_waits_for_service_and_settling(self):
        self.client.wait_for_service.return_value = True
        with patch.object(self.module.time, 'monotonic', side_effect=[0, 3]), \
                patch.object(self.module.time, 'sleep') as settle:
            self.module.wait_for_camera(self.node, '/rae', 60)
            self.client.wait_for_service.assert_called_once_with(timeout_sec=60)
            settle.assert_called_once_with(12.0)
        self.node.destroy_client.assert_called_once_with(self.client)

    def test_configuration_timeout_fails(self):
        self.client.wait_for_service.return_value = False
        with patch.object(self.module.time, 'sleep') as settle:
            with self.assertRaisesRegex(RuntimeError, 'pipeline configuration'):
                self.module.wait_for_camera(self.node, '/rae', 60)
            settle.assert_not_called()
        self.node.destroy_client.assert_called_once_with(self.client)

    def test_late_configuration_needs_no_additional_delay(self):
        self.client.wait_for_service.return_value = True
        with patch.object(self.module.time, 'monotonic', side_effect=[0, 20]), \
                patch.object(self.module.time, 'sleep') as settle:
            self.module.wait_for_camera(self.node, '/rae', 60)
            settle.assert_called_once_with(0.0)


if __name__ == '__main__':
    unittest.main()
