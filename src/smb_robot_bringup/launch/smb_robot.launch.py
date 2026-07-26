"""smb_robot.launch.py — Real-robot bringup (no simulator).

This file assumes the ESP32 firmware (SuperMarketBot-IOT MicroRos.h) is
ALREADY running and publishing topics via the micro-ROS agent. Verify with:

  ros2 topic list              # /scan, /odom, /imu/data, /tf must be present
  ros2 topic info /scan --verbose

If those topics don't exist, the SLAM node will sit idle.

This launch file does NOT start:
  - Gazebo
  - ros_gz_bridge
  - any micro-ROS agent

It DOES start:
  - robot_state_publisher (URDF -> static TFs base_link -> laser_frame / imu_link)
  - joint_state_publisher (zero-position JointState so wheels/caster appear in RViz)
  - slam_toolbox online_async against /scan + /odom
  - RViz2 with config/smb.rviz

Args:
  use_sim_time (bool): Should ALWAYS be false in robot mode. Flag exposed for testing.
  rviz (bool):         Open RViz2 with saved config. Default true.
"""

import os
import subprocess

from ament_index_python import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def _xacro_to_string(path):
    """Run xacro on `path` and return the resulting XML.

    The `xacro` CLI in lyrical has a Python 3.14 compatibility bug. Using the
    Python module API directly bypasses the broken CLI shim.
    """
    out = subprocess.run(
        ['python3', '-c',
         'import sys; from xacro import process_file; '
         'sys.stdout.write(process_file(sys.argv[1]).toprettyxml(indent="  "))',
         path],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def generate_launch_description():
    pkg_bringup = get_package_share_directory('smb_robot_bringup')
    pkg_robot = get_package_share_directory('smb_robot')

    xacro_path = os.path.join(pkg_robot, 'urdf', 'smb.urdf.xacro')
    robot_description = _xacro_to_string(xacro_path)

    rviz_config = PathJoinSubstitution([pkg_bringup, 'config/smb.rviz'])
    slam_config = PathJoinSubstitution([pkg_bringup, 'config/slam_toolbox.yaml'])

    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Must be false in robot mode (no Gazebo).')

    declare_rviz_cmd = DeclareLaunchArgument(
        'rviz',
        default_value='true',
        description='Open RViz2 with saved config.')

    # 1. robot_state_publisher (URDF -> /tf_static)
    rsp_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        parameters=[{
            'robot_description': robot_description,
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }],
        output='screen',
    )

    # 2. joint_state_publisher — publishes JointState at zero positions for
    #    the wheels/caster so RViz RobotModel can place them. In sim mode
    #    this node is NOT needed (gz-sim-joint-state-publisher-system +
    #    ros_gz_bridge already feed /joint_states from the actual sim wheel
    #    rotations). In real-robot mode the ESP32 does not publish joint
    #    state, so this gives robot_state_publisher something to consume.
    jsp_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}],
        output='screen',
    )

    # 3. slam_toolbox online_async — assumes /scan and /odom topics exist
    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            get_package_share_directory('slam_toolbox'),
            '/launch/online_async_launch.py',
        ]),
        launch_arguments={
            'slam_params_file': slam_config,
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }.items(),
    )

    # 4. RViz2 (gated by `rviz:=true` arg)
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', rviz_config],
        parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}],
        condition=IfCondition(LaunchConfiguration('rviz')),
        output='screen',
    )

    return LaunchDescription([
        declare_use_sim_time_cmd,
        declare_rviz_cmd,
        rsp_node,
        jsp_node,
        slam_launch,
        rviz_node,
    ])