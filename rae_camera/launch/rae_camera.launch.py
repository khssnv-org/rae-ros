import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode

from rae_hw.pwm_launch import guarded_camera


def launch_setup(context, *args, **kwargs):
    log_level = 'info'
    if (context.environment.get('DEPTHAI_DEBUG') == '1'):
        log_level = 'debug'
    params_file = LaunchConfiguration('params_file')
    name = LaunchConfiguration('name').perform(context)

    perception = ComposableNodeContainer(
        name=name+'_container',
        namespace='',
        package='rclcpp_components',
        executable='component_container',
        composable_node_descriptions=[
            ComposableNode(
                package='depthai_ros_driver',
                plugin='depthai_ros_driver::Camera',
                name=name,
                parameters=[params_file, {'camera.i_restart_on_diagnostics_error': False}],
            ),
        ],
        arguments=['--ros-args', '--log-level', log_level],
        output='both',
    )

    control = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('rae_hw'), 'launch', 'control.launch.py')),
        condition=IfCondition(LaunchConfiguration('enable_control')),
    )
    return guarded_camera(context, perception, name, on_ready=[control])


def generate_launch_description():
    camera_prefix = get_package_share_directory('rae_camera')
    declared_arguments = [
        DeclareLaunchArgument('name', default_value='rae'),
        DeclareLaunchArgument('enable_control', default_value='false'),
        DeclareLaunchArgument('params_file', default_value=os.path.join(
            camera_prefix, 'config', 'camera.yaml')),
    ]

    return LaunchDescription(
        declared_arguments + [OpaqueFunction(function=launch_setup)]
    )
