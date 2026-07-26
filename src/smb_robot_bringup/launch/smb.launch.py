"""smb.launch.py — Top-level dispatcher for sim vs robot.

Usage:
    # Sim (Gazebo + bridge + URDF + SLAM + RViz):
    ros2 launch smb_robot_bringup smb.launch.py mode:=sim
    # with options:
    ros2 launch smb_robot_bringup smb.launch.py mode:=sim world:=custom_world.sdf headless:=-1

    # Real robot (assumes micro-ROS agent already running):
    ros2 launch smb_robot_bringup smb.launch.py mode:=robot

Both sub-launches share URDF, SLAM config, and RViz config — sim parity with
real hardware means "same topics, same frame_ids".

Implementation note: launch files are evaluated once per `ros2 launch ...`,
not at runtime. We can't switch source file based on `mode` arg directly.
The standard idiom is to include both sub-launches and gate each with
`IfCondition(EqualsSubstitution(...))`. Then only one runs.
"""

from ament_index_python import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EqualsSubstitution, LaunchConfiguration


def generate_launch_description():
    pkg_bringup = get_package_share_directory('smb_robot_bringup')

    declare_mode_cmd = DeclareLaunchArgument(
        'mode',
        default_value='sim',
        choices=['sim', 'robot'],
        description='sim = Gazebo+bridge pipeline; robot = ESP32 micro-ROS topics.')

    # Conditionally include sim vs robot sub-launch. Only the matching one
    # actually starts its nodes.
    sim_include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([pkg_bringup, '/launch/smb_sim.launch.py']),
        condition=IfCondition(
            EqualsSubstitution(LaunchConfiguration('mode'), 'sim')),
    )

    robot_include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([pkg_bringup, '/launch/smb_robot.launch.py']),
        condition=IfCondition(
            EqualsSubstitution(LaunchConfiguration('mode'), 'robot')),
    )

    return LaunchDescription([
        declare_mode_cmd,
        sim_include,
        robot_include,
    ])

# Launch args forwarded from smb.launch.py → smb_sim.launch.py:
#   world, use_sim_time, rviz, headless, teleop
# All sub-args are declared inside smb_sim.launch.py; smb.launch.py
# doesn't need to redeclare them — ros2 launch forwards unknown args
# via the IncludeLaunchDescription call chain.
