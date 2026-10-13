"""Common PWM startup gate for control, camera and IPC launch files."""

import atexit
import subprocess

from launch.actions import EmitEvent, LogInfo, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch_ros.actions import Node

from rae_hw.pwm import PwmStartup


def hardware_session(context):
    """Keep one hardware lease in the launch context until the launcher exits."""
    for flag in ('mock', 'sim', 'sim_mode', 'use_sim_time'):
        if context.launch_configurations.get(flag, 'false').lower() in ('true', '1'):
            raise RuntimeError('Use control_mock.launch.py or gazebo.launch.py for simulation')
    session = context.get_locals_as_dict().get('rae_pwm_session')
    if session is None:
        session = PwmStartup()
        context.extend_globals({'rae_pwm_session': session})
        # OnShutdown occurs before child processes exit. Keep the lease longer.
        atexit.register(session.close)
    return session


def guarded_camera(context, camera, name, on_ready=()):
    """Wait for camera pipeline setup, reset PWM, then admit follow-up actions."""
    session = hardware_session(context)
    session.begin_camera()
    waiter = Node(
        package='rae_hw', executable='wait_for_camera.py',
        arguments=['--camera', '/' + name.strip('/'), '--timeout', '60'],
        output='screen',
    )

    def failed(reason):
        session.camera_failed = True
        return [LogInfo(msg=reason), EmitEvent(event=Shutdown(reason=reason))]

    def camera_exited(event, ctx):
        if ctx.is_shutdown:
            session.camera_failed = True
            return []
        return failed('Camera process exited; stopping the hardware launch')

    def ready(event, ctx):
        if ctx.is_shutdown or session.camera_failed:
            return []
        if event.returncode != 0:
            return failed('Camera configuration failed; motors will not start')
        try:
            session.finish_camera()
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            return failed(f'PWM initialization failed: {exc}')
        return [LogInfo(msg='Camera configured; PWM readback 0x00000000.'), *on_ready]

    return [
        RegisterEventHandler(OnProcessExit(target_action=camera, on_exit=camera_exited)),
        RegisterEventHandler(OnProcessExit(target_action=waiter, on_exit=ready)),
        camera,
        waiter,
    ]
