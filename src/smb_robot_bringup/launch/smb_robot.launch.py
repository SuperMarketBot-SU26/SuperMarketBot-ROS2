"""smb_robot.launch.py — Real-robot bringup (no simulator).

Usage:
    ros2 launch smb_robot_bringup smb.launch.py mode:=robot

This file assumes the ESP32 firmware (SuperMarketBot-IOT MicroRos.h) is
ALREADY running and publishing topics via the micro-ROS agent. Verify with:

    ros2 topic list              # /scan, /odom, /imu/data must be present
    ros2 topic info /scan --verbose

Hardware prerequisite:
  The ESP32 MicroRos.h must have MICRO_ROS_AGENT_IP set to your host PC's
  IP on the shared WiFi network. Default in firmware: 192.168.1.106.
  Run `ip addr show` on the host to find its IP, then update the ESP32
  firmware or set a matching static IP.

What this launch starts:
  - micro-ROS agent (WiFi UDP, port 8888) — bridges ESP32 ↔ ROS2
  - robot_state_publisher (URDF -> static TFs)
  - joint_state_publisher (zero-pose fallback for RViz)
  - slam_toolbox online_async against /scan + /odom
  - Nav2 (planner + controller + BT + behaviors + waypoint_follower)
  - supervisor FSM (gates /cmd_vel with estop + state machine)
  - RViz2 with config/common/smb.rviz

Args:
  use_sim_time (bool):  Always false in robot mode. Exposed for testing.
  rviz (bool):           Open RViz2 with saved config. Default true.
  use_nav2 (bool):       Bring up Nav2 stack. Default true.
  use_supervisor (bool): Start supervisor FSM. Default true.
  use_micro_ros (bool):  Start micro-ROS agent. Default true.
  slam_params_file (str): Override SLAM Toolbox config. Default is
                          config/robot/slam_toolbox.yaml (loop closing enabled).
  nav2_params_file (str): Override Nav2 params. Default is nav2_params.yaml.
"""

import os
import subprocess

from ament_index_python import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription
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

    rviz_config = PathJoinSubstitution([pkg_bringup, 'config/common/smb.rviz'])
    slam_config_default = os.path.join(pkg_bringup, 'config', 'robot', 'slam_toolbox.yaml')
    nav2_config_default = os.path.join(pkg_bringup, 'params', 'nav2_params_robot.yaml')

    # ---- Launch arguments ----
    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='false',
        description='Must be false in robot mode (no Gazebo).')

    declare_rviz_cmd = DeclareLaunchArgument(
        'rviz',
        default_value='false',
        description='Open RViz2 with saved config.')

    declare_use_nav2_cmd = DeclareLaunchArgument(
        'use_nav2',
        default_value='true',
        description='Bring up Nav2 stack (planner + controller + BT). Default true.')

    declare_use_supervisor_cmd = DeclareLaunchArgument(
        'use_supervisor',
        default_value='true',
        description='Start supervisor FSM (gates /cmd_vel with estop + state machine). Default true.')

    declare_use_micro_ros_cmd = DeclareLaunchArgument(
        'use_micro_ros',
        default_value='true',
        description='Start micro-ROS agent (WiFi UDP port 8888). Default true.')

    declare_use_ekf_cmd = DeclareLaunchArgument(
        'use_ekf',
        default_value='true',
        description='Start robot_localization EKF to convert /odom topic into '
                    'odom→base_link TF. slam_toolbox needs this TF to produce '
                    'map→odom. Default true.')

    declare_use_slam_cmd = DeclareLaunchArgument(
        'use_slam',
        default_value='true',
        description='Start slam_toolbox for online SLAM. Set false during '
                    'teleop-only testing — SLAM scan-matching fails when the '
                    'robot moves outside the scanned area, causing map→odom '
                    'drift and erratic motion. Default true.')

    declare_slam_params_cmd = DeclareLaunchArgument(
        'slam_params_file',
        default_value=slam_config_default,
        description='SLAM Toolbox params YAML. Default config/robot/slam_toolbox.yaml.')

    declare_nav2_params_cmd = DeclareLaunchArgument(
        'nav2_params_file',
        default_value=nav2_config_default,
        description='Nav2 params YAML.')

    declare_serial_port_cmd = DeclareLaunchArgument(
        'serial_port',
        default_value='/dev/ttyUSB0',
        description='USB serial device connected to ESP32 for micro-ROS.')

    declare_serial_baud_cmd = DeclareLaunchArgument(
        'serial_baud',
        default_value='921600',
        description='Baudrate for USB serial micro-ROS connection.')

    # MQTT Bridge args
    declare_use_mqtt_bridge_cmd = DeclareLaunchArgument(
        'use_mqtt_bridge',
        default_value='false',
        description='Enable MQTT navigation bridge (backend → Nav2). Default false.')

    declare_mqtt_host_cmd = DeclareLaunchArgument(
        'mqtt_host',
        default_value='',
        description='HiveMQ Cloud broker hostname.')

    declare_mqtt_port_cmd = DeclareLaunchArgument(
        'mqtt_port',
        default_value='8883',
        description='MQTT broker port (8883 = TLS).')

    declare_mqtt_username_cmd = DeclareLaunchArgument(
        'mqtt_username',
        default_value='',
        description='MQTT broker username.')

    declare_mqtt_password_cmd = DeclareLaunchArgument(
        'mqtt_password',
        default_value='',
        description='MQTT broker password.')

    declare_mqtt_use_tls_cmd = DeclareLaunchArgument(
        'mqtt_use_tls',
        default_value='true',
        description='Enable TLS for MQTT connection (required for HiveMQ Cloud).')

    declare_robot_code_cmd = DeclareLaunchArgument(
        'robot_code',
        default_value='RB001',
        description='Robot identifier for MQTT topic routing.')

    ekf_config_default = os.path.join(pkg_bringup, 'config', 'robot', 'ekf_minimal.yaml')

    # ---- Nodes ----

    # 1. micro-ROS agent — bridges ESP32 USB Serial ↔ ROS2 topics directly on Pi 5.
    default_agent_paths = [
        '/ros2_ws/install/micro_ros_agent/lib/micro_ros_agent/micro_ros_agent',
        os.path.expanduser('~/ros2_ws/install/micro_ros_agent/lib/micro_ros_agent/micro_ros_agent'),
        '/opt/ros/lyrical/bin/micro_ros_agent'
    ]
    agent_bin_found = 'micro_ros_agent'
    for p in default_agent_paths:
        if os.path.exists(p):
            agent_bin_found = p
            break
    micro_ros_agent_bin = os.environ.get('SMB_MICRO_ROS_AGENT', agent_bin_found)
    micro_ros_agent_node = ExecuteProcess(
        cmd=[micro_ros_agent_bin, 'serial', '--dev', LaunchConfiguration('serial_port'), '-b', LaunchConfiguration('serial_baud')],
        condition=IfCondition(LaunchConfiguration('use_micro_ros')),
        output='screen',
        shell=False,
    )

    # 2. robot_state_publisher (URDF -> /tf_static)
    rsp_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        parameters=[{
            'robot_description': robot_description,
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'publish_frequency': 30.0,
        }],
        output='screen',
    )

    # 3. joint_state_publisher — zero-pose fallback for RViz (ESP32 doesn't
    #    publish joint states; without this, wheels appear at origin in RViz).
    jsp_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'rate': 30,
        }],
        output='screen',
    )

    # 4. slam_toolbox online_async — assumes /scan and /odom from micro-ROS agent.
    #    autostart=false on purpose: the ESP32 takes ~10-30s after the agent
    #    starts to complete its XRCE handshake. If slam auto-activates
    #    before /scan is flowing, message_filters rejects every scan with
    #    "timestamp earlier than transform cache" and slam never produces
    #    /map. Activate it manually once `ros2 topic hz /scan` reports ~10 Hz.
    slam_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            get_package_share_directory('slam_toolbox'),
            '/launch/online_async_launch.py',
        ]),
        condition=IfCondition(LaunchConfiguration('use_slam')),
        launch_arguments={
            'slam_params_file': LaunchConfiguration('slam_params_file'),
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'autostart': 'true',
        }.items(),
    )

    # 5. Nav2 — minimal bringup (same as smb_sim.launch.py uses).
    #    Loaded into a single component_container process for efficiency.
    #    use_sim_time=false because robot uses wall-clock.
    #    Controller output /cmd_vel_nav → supervisor → /cmd_vel (contract topic).
    #
    #    autostart=false: Nav2 lifecycle waits for `base_link → map` TF which
    #    only exists once slam_toolbox has produced /map. Wait until
    #    `ros2 topic echo /map --once` returns before activating.
    nav2_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            get_package_share_directory('smb_robot_bringup'),
            '/launch/smb_nav2_minimal.launch.py',
        ]),
        condition=IfCondition(LaunchConfiguration('use_nav2')),
        launch_arguments={
            'use_sim_time': 'false',
            'params_file': LaunchConfiguration('nav2_params_file'),
            'autostart': 'false',
        }.items(),
    )

    # 6. Supervisor FSM — gates /cmd_vel between Nav2 (/cmd_vel_nav) and
    #    the contract topic /cmd_vel consumed by ESP32 via micro-ROS.
    #    See smb_nodes/supervisor.py for FSM semantics (idle/nav/estop states).
    supervisor_node = Node(
        package='smb_nodes',
        executable='supervisor',
        name='supervisor',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }],
        condition=IfCondition(LaunchConfiguration('use_supervisor')),
        output='screen',
    )

    # 6b. Unified relay — replaces the old scan_relay + odom_imu_relay pair.
    #     Single node handles QoS bridge (RELIABLE→BEST_EFFORT for /scan),
    #     stamp rewriting (ESP32 millis() → host wall-clock), AND timestamp
    #     coordination (scan stamp = latest odom stamp so SLAM's TF lookup
    #     finds an exact match instead of extrapolating). This eliminates
    #     the inter-node scheduling skew that caused map drag.
    #     See smb_nodes/unified_relay.py for details.
    unified_relay_node = Node(
        package='smb_nodes',
        executable='unified_relay',
        name='unified_relay',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'scan_in': '/scan',
            'scan_out': '/scan_relay',
            'odom_in': '/odom',
            'odom_out': '/odom_relay',
            'imu_in': '/imu/data',
            'imu_out': '/imu_relay',
            'publish_tf': False,  # EKF handles odom→base_link TF
        }],
        output='screen',
    )

    # 7. RViz2
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', rviz_config],
        parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}],
        condition=IfCondition(LaunchConfiguration('rviz')),
        output='screen',
    )

    # 9. MQTT Bridge — connects Backend (HiveMQ Cloud) to Nav2 waypoint
    #    navigation. Receives NAVIGATE_WAYPOINTS commands via MQTT, drives
    #    Nav2 FollowWaypoints, and reports status back to the backend.
    #    Gated behind use_mqtt_bridge (default false).
    mqtt_bridge_node = Node(
        package='smb_nodes',
        executable='smb_mqtt_bridge',
        name='smb_mqtt_bridge',
        parameters=[{
            'use_sim_time': LaunchConfiguration('use_sim_time'),
            'mqtt_host': LaunchConfiguration('mqtt_host'),
            'mqtt_port': LaunchConfiguration('mqtt_port'),
            'mqtt_username': LaunchConfiguration('mqtt_username'),
            'mqtt_password': LaunchConfiguration('mqtt_password'),
            'mqtt_use_tls': LaunchConfiguration('mqtt_use_tls'),
            'robot_code': LaunchConfiguration('robot_code'),
        }],
        condition=IfCondition(LaunchConfiguration('use_mqtt_bridge')),
        output='screen',
    )

    # 8. robot_localization EKF — single-source (odom only) to publish
    #    odom → base_link TF. slam_toolbox needs this TF to produce map → odom.
    #    Phase 2 will replace this with full sensor fusion (wheel + IMU + AMCL).
    ekf_node = Node(
        package='robot_localization',
        executable='ekf_node',
        name='ekf_filter_node',
        output='screen',
        parameters=[
            os.path.join(pkg_bringup, 'config', 'robot', 'ekf_minimal.yaml'),
            {'use_sim_time': LaunchConfiguration('use_sim_time')},
        ],
        condition=IfCondition(LaunchConfiguration('use_ekf')),
    )

    return LaunchDescription([
        declare_use_sim_time_cmd,
        declare_rviz_cmd,
        declare_use_nav2_cmd,
        declare_use_supervisor_cmd,
        declare_use_micro_ros_cmd,
        declare_use_ekf_cmd,
        declare_use_slam_cmd,
        declare_slam_params_cmd,
        declare_nav2_params_cmd,
        declare_serial_port_cmd,
        declare_serial_baud_cmd,
        declare_use_mqtt_bridge_cmd,
        declare_mqtt_host_cmd,
        declare_mqtt_port_cmd,
        declare_mqtt_username_cmd,
        declare_mqtt_password_cmd,
        declare_mqtt_use_tls_cmd,
        declare_robot_code_cmd,
        micro_ros_agent_node,
        rsp_node,
        jsp_node,
        ekf_node,
        slam_launch,
        unified_relay_node,
        supervisor_node,
        nav2_launch,
        mqtt_bridge_node,
        rviz_node,
    ])
