"""Run the installed local ROS graph with the selected GuideBot interpreter."""
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription, LaunchService
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from pathlib import Path


def main():
    source = Path(get_package_share_directory('guidebot_ros2'))/'launch/guidebot.launch.py'
    service = LaunchService()
    service.include_launch_description(LaunchDescription([IncludeLaunchDescription(PythonLaunchDescriptionSource(str(source)))]))
    return service.run()


if __name__ == '__main__':
    raise SystemExit(main())
