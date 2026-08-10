"""smb_nav2_minimal.launch.py \u2014 minimal Nav2 bringup for our trimmed package set.

Why this exists (2026-07-27)
----------------------------
Upstream `nav2_bringup`'s `bringup_launch.py` -> `navigation_launch.py` hard-codes
a `lifecycle_nodes` list including:

  - smoother_server  (nav2_smoother)
  - velocity_smoother (nav2_velocity_smoother)
  - collision_monitor (nav2_collision_monitor)
  - route_server     (nav2_route)
  - docking_server   (opennav_docking)
  - following_server (opennav_following)

None of these packages are built for our ROS2 "lyrical" distro on Ubuntu 26.04
(the `ros2_ws.repos` vendors only the core nav2 stack: controller, planner,
behaviors, bt_navigator, waypoint_follower, costmap_2d, lifecycle_manager).
The lifecycle manager therefore hangs forever at
`Waiting for service smoother_server/get_state` and `use_nav2:=true` is
unusable in our setup.

This launch file replicates upstream's ComposableNode pattern but loads only
the 5 lifecycle nodes + the lifecycle_manager itself, all from packages we
actually have on the install. It is a deliberately small variant: nothing
about smoother/dock/collision-monitor is implemented; the project roadmap
covers docking in a later phase. Adding them later means adding more
ComposableNode entries here, not changing the upstream file.

What it loads
-------------
Container (one process, holds all 6 nodes):
  controller_server     (nav2_controller)
  planner_server        (nav2_planner)
  behavior_server       (nav2_behaviors)
  bt_navigator          (nav2_bt_navigator)
  waypoint_follower     (nav2_waypoint_follower)
  lifecycle_manager_navigation  (nav2_lifecycle_manager)

Topic / TF conventions match the upstream defaults
(`/cmd_vel_nav` for controller output, `/map` for global, `/odom` for odom).
See smb_robot_bringup/params/nav2_params.yaml and docs/TOPIC_CONTRACT.md.

When to switch back to upstream
-------------------------------
When/if the missing packages get built and added to `ros2_ws.repos`,
delete this file and flip `smb_sim.launch.py`'s `nav2_launch` back to
`nav2_bringup`'s `bringup_launch.py`. The two are not designed to coexist.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode
from nav2_common.launch import RewrittenYaml


def generate_launch_description() -> LaunchDescription:
    # ---- Launch args (subset of upstream's; we don't need graph file, etc.) ----
    params_file = LaunchConfiguration('params_file')
    use_sim_time = LaunchConfiguration('use_sim_time')
    autostart = LaunchConfiguration('autostart')
    container_name = LaunchConfiguration('container_name')

    # ---- Substitutions in the params file ----
    # `$(find-pkg-share nav2_bt_navigator)` is a launch-substitution token used
    # in our `nav2_params.yaml` (bt_search_directories) — nav2_bt_navigator's
    # configure() does not resolve it itself. Upstream's
    # `nav2_bringup/navigation_launch.py` uses `ParameterFile(..., allow_substs=True)`
    # to expand this at launch time; we do the same. Without allow_substs=True,
    # bt_navigator fails to configure with
    # `directory iterator cannot open directory: No such file or directory
    # [$(find-pkg-share nav2_bt_navigator)/behavior_trees]`.
    # See https://github.com/ros-planning/navigation2/blob/main/nav2_bringup/launch/navigation_launch.py
    from launch_ros.descriptions import ParameterFile
    configured_params = ParameterFile(params_file, allow_substs=True)

    # ---- Lifecycle nodes managed by lifecycle_manager_navigation ----
    # MUST match the ComposableNode names below, in load order. This is the
    # list passed to LifecycleManager.node_names so it knows which
    # /<name>/get_state services to wait for.
    lifecycle_nodes = [
        'controller_server',
        'planner_server',
        'behavior_server',
        'bt_navigator',
        'waypoint_follower',
    ]

    # Common remappings (matches upstream remappings[0..1]):
    #   /tf -> tf, /tf_static -> tf_static
    # so node-internal tf lookups don't depend on a global /tf topic.
    remappings = [('/tf', 'tf'), ('/tf_static', 'tf_static')]

    # ---- Composable node descriptions ----
    composable_nodes = [
        ComposableNode(
            package='nav2_controller',
            plugin='nav2_controller::ControllerServer',
            name='controller_server',
            parameters=[configured_params],
            # Upstream remaps controller output cmd_vel -> cmd_vel_nav
            # because the (optional) smoother would consume that and emit
            # cmd_vel_smoothed -> velocity_smoother -> cmd_vel. We don't
            # have those, but the smb_nodes.supervisor FSM (see
            # smb_robot_bringup launch) already handles the cmd_vel_nav ->
            # cmd_vel pass-through, so we keep the upstream remap.
            remappings=remappings + [('cmd_vel', 'cmd_vel_nav_raw')],
        ),
        ComposableNode(
            package='nav2_planner',
            plugin='nav2_planner::PlannerServer',
            name='planner_server',
            parameters=[configured_params],
            remappings=remappings,
        ),
        ComposableNode(
            package='nav2_behaviors',
            plugin='behavior_server::BehaviorServer',
            name='behavior_server',
            parameters=[configured_params],
            remappings=remappings + [('cmd_vel', 'cmd_vel_nav_raw')],
        ),
        ComposableNode(
            package='nav2_bt_navigator',
            plugin='nav2_bt_navigator::BtNavigator',
            name='bt_navigator',
            parameters=[configured_params],
            remappings=remappings,
        ),
        ComposableNode(
            package='nav2_waypoint_follower',
            plugin='nav2_waypoint_follower::WaypointFollower',
            name='waypoint_follower',
            parameters=[configured_params],
            remappings=remappings,
        ),
        # Lifecycle manager is itself a composable node. autostart=true
        # makes it CONFIGURE+ACTIVATE every node in `lifecycle_nodes` in
        # order; the 5 names above resolve to 5 /<name>/get_state
        # services that the container exposes.
        ComposableNode(
            package='nav2_lifecycle_manager',
            plugin='nav2_lifecycle_manager::LifecycleManager',
            name='lifecycle_manager',
            parameters=[{
                'autostart': autostart,
                'node_names': lifecycle_nodes,
                'use_sim_time': use_sim_time,
                'bond_timeout': 120.0,
                'attempt_respawn_reconnection': True,
            }],
        ),
    ]

    # ---- The container process ----
    # ComposableNodeContainer is a Node that runs a `component_container`
    # process; ComposableNode descriptions are loaded into that process.
    # This is what gives us the speedup of composable nodes (one process
    # per stack instead of one per node) without needing to manage
    # inter-process comms by hand.
    container = ComposableNodeContainer(
        name=container_name,
        namespace='',
        package='rclcpp_components',
        executable='component_container_mt',
        composable_node_descriptions=composable_nodes,
        output='screen',
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'params_file',
            default_value=os.path.join(
                get_package_share_directory('smb_robot_bringup'),
                'params', 'nav2_params.yaml'),
            description='Full path to nav2 params YAML (smb_robot_bringup/params/nav2_params.yaml).'),
        DeclareLaunchArgument(
            'use_sim_time', default_value='True',
            description='Use /clock (Gazebo) for time. Real-robot brings this up as False.'),
        DeclareLaunchArgument(
            'autostart', default_value='True',
            description='Automatically startup the nav2 stack on launch.'),
        DeclareLaunchArgument(
            'container_name', default_value='nav2_container',
            description='Name of the composable-node container process.'),
        container,
    ])
