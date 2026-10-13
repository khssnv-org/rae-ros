import os
from ament_index_python.packages import get_package_share_path
import launch
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    camera_prefix = get_package_share_path('rae_camera')
    return launch.LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(camera_prefix, 'launch', 'rae_camera.launch.py')),
            launch_arguments={'enable_control': 'true',
                              'run_container': 'false',
                              'enable_battery_status': 'true',
                              'enable_localization': 'true'}.items())
    ])
