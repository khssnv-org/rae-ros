import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch.launch_description_sources import PythonLaunchDescriptionSource

from rae_hw.pwm_launch import guarded_camera


def launch_setup(context, *args, **kwargs):
    log_level = 'info'
    if (context.environment.get('DEPTHAI_DEBUG') == '1'):
        log_level = 'debug'
    params_file = LaunchConfiguration('params_file')
    name = LaunchConfiguration('name').perform(context)
    hw_prefix = get_package_share_directory('rae_hw')
    remappings = [
        #   ('imu', '/imu/data'),
        # ('__camera', 'rae'),
        ('camera:__node', name),
        ('odom', '/diff_controller/odom'),
        ('rgb/image', name+'/right/image_raw'),
        ('rgb/camera_info', name+'/right/camera_info'),
        ('depth/image', name+'/stereo_front/image_raw'),
        ('image', name+'/right/image_raw'),
        ('camera_info', name+'/right/camera_info'),
        ('image_rect', name+'/right/image_rect')
    ]

    perception = Node(
            package='rae_camera',
            executable='perception_ipc_rtabmap',
            output='screen',
            parameters=[params_file, {'camera.i_restart_on_diagnostics_error': False}],
            remappings=remappings
           )

    control = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(hw_prefix, 'launch', 'control.launch.py')))
    return guarded_camera(context, perception, name, on_ready=[control])


def generate_launch_description():
    camera_prefix = get_package_share_directory('rae_camera')
    declared_arguments = [
        DeclareLaunchArgument('name', default_value='rae'),
        DeclareLaunchArgument('params_file', default_value=os.path.join(
            camera_prefix, 'config', 'ipc.yaml')),
    ]

    return LaunchDescription(
        declared_arguments + [OpaqueFunction(function=launch_setup)]
    )
