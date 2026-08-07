import sys
import asyncio
from launch import LaunchService, LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

def main():
    ls = LaunchService()
    ld = LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource('/home/nhatkhoa1124/ros2_ws/install/smb_robot_bringup/share/smb_robot_bringup/launch/smb_robot.launch.py')
        )
    ])
    ls.include_launch_description(ld)
    try:
        ls.run()
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
