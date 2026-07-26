"""smb_sim.launch.py — Launch Gazebo + ros_gz_bridge + URDF + SLAM + RViz (sim).

Companion to smb_robot.launch.py, which handles the "mode:=robot" path
(no simulator; assumes micro-ROS agent is already publishing topics).

End-to-end behavior:
  1. Gazebo Sim loads worlds/smb_world.sdf
  2. robot_state_publisher publishes static TFs from URDF
     (base_link -> laser_frame, base_link -> imu_link, wheels, caster)
  3. ros_gz_bridge relays topics per config/ros_gz_bridge.yaml
  4. slam_toolbox online_async runs against /scan + /odom, publishes /map
  5. RViz2 opens with config/smb.rviz (robot + map + scan)

Args:
  world (str):       Gazebo world SDF under worlds/. Default 'smb_world.sdf'.
  use_sim_time (bool): When true, Gazebo /clock drives all node time.
                        Always true in sim; flag exposed for safety.
  rviz (bool):       Open RViz2 with saved config. Default true.
  headless (bool):    gz sim flag (true = headless -s, false = windowed -g). Default false.
"""

import os
import subprocess

from ament_index_python import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def _xacro_to_string(path):
    """Run xacro on `path` and return the resulting XML.

    The `xacro` CLI in lyrical has a Python 3.14 compatibility bug
    (missing xml.parsers attribute). Using the Python module API works fine.
    """
    out = subprocess.run(
        ['python3', '-c',
         'import sys; from xacro import process_file; '
         'sys.stdout.write(process_file(sys.argv[1]).toprettyxml(indent="  "))',
         path],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def _make_gz_sim(context, *args, **kwargs):
    """Build the Gazebo sim ExecuteProcess.

    gz sim 10 (Ionic) takes either `-g` (GUI, separate process) or `-s` (server,
    headless), not both. The user passes `headless:=true/false`; we choose.

    Windowed mode: use the LEGACY combined-mode (no `-g`, no `-s`). On
    Wayland+XWayland setups (Ubuntu 26.04 default), `gz sim -g` hangs the
    Qt6 EGL/GLX handshake and the GUI process never finishes initializing,
    which kills the sim server too under `ros2 launch` supervision.
    Combined-mode (`gz sim <world>` with no flag) runs GUI + server in one
    process tree, which uses a single Qt init path that doesn't trigger the
    bug. Help text on the binary only documents `-g`/`-s`, but combined-mode
    is still supported as the default.

    Headless mode: `-s --headless-rendering` (EGL sensor data without X).
    """
    from launch.substitutions import LaunchConfiguration as LC
    headless = LC('headless').perform(context).lower() == 'true'
    world = LC('world').perform(context)

    pkg_bringup = get_package_share_directory('smb_robot_bringup')
    world_path = f'{pkg_bringup}/worlds/{world}'

    env_overrides = {}
    if headless:
        # --headless-rendering uses EGL so lidar/camera sensors that need GPU
        # ray-tracing still publish data without an X server. Without this flag
        # gz sim -s runs physics only and sensor topics stay empty.
        # EGL_PLATFORM=surfaceless on Ubuntu 26+NVIDIA prevents gz from hanging
        # on EGL device enumeration when X is present.
        env_overrides['EGL_PLATFORM'] = 'surfaceless'
        cmd = ['gz', 'sim', '-s', '--headless-rendering', world_path]
    else:
        # Combined-mode (legacy): GUI + server in one process. Avoids the
        # `gz sim -g` Wayland hang on Ubuntu 26.04.
        cmd = ['gz', 'sim', world_path]

    gz_sim = ExecuteProcess(
        cmd=cmd,
        output='screen',
        additional_env=env_overrides or {},
    )
    return [gz_sim]  # must return a list of actions


def generate_launch_description():
    pkg_bringup = get_package_share_directory('smb_robot_bringup')
    pkg_robot = get_package_share_directory('smb_robot')

    xacro_path = os.path.join(pkg_robot, 'urdf', 'smb.urdf.xacro')
    robot_description = _xacro_to_string(xacro_path)

    world_path = PathJoinSubstitution([pkg_bringup, 'worlds', LaunchConfiguration('world')])
    bridge_config = PathJoinSubstitution([pkg_bringup, 'config/ros_gz_bridge.yaml'])
    rviz_config = PathJoinSubstitution([pkg_bringup, 'config/smb.rviz'])
    slam_config = PathJoinSubstitution([pkg_bringup, 'config/slam_toolbox.yaml'])

    declare_world_cmd = DeclareLaunchArgument(
        'world',
        default_value='smb_world.sdf',
        description='World SDF file under worlds/.')

    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use Gazebo /clock for time.')

    declare_rviz_cmd = DeclareLaunchArgument(
        'rviz',
        default_value='true',
        description='Open RViz2 with saved config.')

    declare_headless_cmd = DeclareLaunchArgument(
        'headless',
        default_value='false',
        description='If true, run gz sim with -s (server only, no GUI). Default = false (GUI).')

    # 1. Gazebo Sim.
    #    gz sim 10 (Ionic) uses positional `[file]` for the world; only one of
    #    `-g` (GUI) or `-s` (server/headless) can be passed, NOT both. To choose:
    #    we conditionally build the cmd list with the OpaqueFunction below.
    #    `cmd=[]` with `condition=` doesn't work for `ExecuteProcess` directly,
    #    so we wrap with OpaqueFunction.

    # 2. robot_state_publisher (URDF -> /tf_static)
    #    robot_description is the pre-processed XML (xacro expanded at launch-time).
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

    # 2b. No static TF remap needed: the ros_gz_bridge config
    #     (`frame_id: laser_frame`) rewrites /scan.header.frame_id from the
    #     gz-derived `smb/base_link/laser` to `laser_frame`, which the URDF
    #     already links to `base_link` via robot_state_publisher. slam_toolbox
    #     therefore performs `laser_frame -> base_link` lookup against an
    #     existing static TF — no extra node required.

    # 3. ros_gz_bridge (per config/ros_gz_bridge.yaml)
    bridge_node = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='ros_gz_bridge',
        parameters=[{
            'config_file': bridge_config,
            'use_sim_time': LaunchConfiguration('use_sim_time'),
        }],
        output='screen',
    )

    # 4. slam_toolbox online_async (skipped until package is built / Phase 1.5)
    #    autostart=true: slam_toolbox's lifecycle node needs a CONFIGURE event
    #    before it can do anything (it needs to read its params). With
    #    autostart=true, the launch file emits CONFIGURE then ACTIVATE
    #    after the configuring->inactive transition. With autostart=false
    #    the node stays unconfigured and never makes a map.
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

    # 5. RViz2 (gated by `rviz:=true` arg)
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', rviz_config],
        parameters=[{'use_sim_time': LaunchConfiguration('use_sim_time')}],
        condition=IfCondition(LaunchConfiguration('rviz')),
        output='screen',
    )

    # 6. Teleop keyboard (gated by `teleop:=true` arg).
    #    Press Ctrl-C in this terminal to stop the whole launch; the robot
    #    will respond to /cmd_vel in another terminal that runs:
    #      ros2 run teleop_twist_keyboard teleop_twist_keyboard \
    #          --ros-args -r cmd_vel:=/model/smb/cmd_vel
    #    We do NOT spawn teleop as a process here because the legacy script
    #    launched it in a new xterm window, which interferes with the
    #    unified launch cleanup. Users who want it can run it themselves
    #    in another terminal.
    # (teleop arg kept for parity with future xterm-based launch variants)
    declare_teleop_cmd = DeclareLaunchArgument(
        'teleop',
        default_value='false',
        description='Spawn teleop_twist_keyboard in this launch. Default false (run it yourself in another terminal).',
    )

    # The world starts unpaused via <start_paused>false</start_paused> in the
    # SDF (WorldControl plugin). Previously this launch had a 5s TimerAction
    # that called `gz service ... --req 'pause: false'` to unpause the world
    # at runtime — that was a workaround for the SDF defaulting to paused when
    # a GUI is present. Removing the SDF-side pause eliminates a ~5s window
    # after launch where the physics doesn't step even though /cmd_vel is
    # being forwarded. (Felt by users as "the robot doesn't move for the first
    # 10s".) The 5s wait was for the world/control service to become available,
    # which is also no longer needed.

    return LaunchDescription([
        declare_world_cmd,
        declare_use_sim_time_cmd,
        declare_rviz_cmd,
        declare_headless_cmd,
        declare_teleop_cmd,
        OpaqueFunction(function=_make_gz_sim),
        rsp_node,
        bridge_node,
        slam_launch,
        rviz_node,
    ])
