#!/usr/bin/env bash
# test_robot.sh — one-command bringup for the real-robot integration.
#
# Usage:
#   ./test_robot.sh             # full bringup (agent + SLAM + Nav2 + RViz)
#   ./test_robot.sh --check     # verify deps + launch syntax only (no bringup)
#   SKIP_MICRO_ROS=true ./test_robot.sh  # skip micro-ROS agent (already running)
#
# Env vars:
#   ROS_DISTRO          (default: lyrical)
#   SKIP_MICRO_ROS      (default: false)  — set true if agent is already running
#
# What it does:
#   1. Cleans leftover robot/slam processes from a previous run.
#   2. Launches smb.launch.py mode:=robot which starts:
#        - micro-ROS agent (WiFi UDP 8888) ← bridges ESP32 ↔ ROS2
#        - robot_state_publisher
#        - joint_state_publisher (zero-pose for RViz)
#        - slam_toolbox online_async
#        - Nav2 (planner + controller + BT + behaviors + waypoint_follower)
#        - supervisor FSM (/cmd_vel gating with estop)
#        - RViz2 with smb.rviz
#   3. Cleans up on Ctrl-C / exit.
#
# Telemetry / driving:
#   Use ./test_teleop.sh in another terminal to drive via /cmd_vel.
#   Use ./test_nav2_goal.sh to send Nav2 NavigateToPose goals.
#
# Hardware prerequisite:
#   - ESP32 must be running MicroRos.h firmware
#   - ESP32 MICRO_ROS_AGENT_IP must match the host PC's IP on the shared WiFi
#     Run `ip addr show` to find the host IP, then update MicroRos.h or set
#     a matching static IP (default in firmware: 192.168.1.241).
#   - micro-ROS agent built from source (in install/micro_ros_agent/...).
#     The snap build is NOT compatible with ROS 2 lyrical (CDR format
#     mismatch causes std::bad_alloc storm). See ros2_ws.repos notes.

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_DISTRO="${ROS_DISTRO:-lyrical}"
SKIP_MICRO_ROS="${SKIP_MICRO_ROS:-false}"

# ----- Args --------------------------------------------------------------------
opt="${1:-}"

if [[ "$opt" == "--check" ]]; then
    do_check_only=1
elif [[ -n "$opt" && "$opt" != "--check" ]]; then
    echo "Usage: $0 [--check]"
    echo "       --check   verify deps + launch syntax only"
    exit 1
fi

# ----- Sanity checks -----------------------------------------------------------
if [[ ! -d "$SCRIPT_DIR/install/smb_robot_bringup" ]]; then
    echo "ERROR: install/smb_robot_bringup not found."
    echo "Build it first:"
    echo "  cd $SCRIPT_DIR"
    echo "  source /opt/ros/${ROS_DISTRO}/setup.bash"
    echo "  colcon build"
    exit 1
fi

if ! [[ -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]]; then
    echo "ERROR: /opt/ros/${ROS_DISTRO}/setup.bash not found."
    exit 1
fi

# Source ROS
set +u
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source "$SCRIPT_DIR/install/setup.bash"

# ----- --check -----------------------------------------------------------------
if [[ "${do_check_only:-0}" -eq 1 ]]; then
    echo "[test_robot] --check mode: verifying deps + launch syntax."
    printf "  %-30s ... " "micro_ros_agent (source)"
    if [[ -x "$SCRIPT_DIR/install/micro_ros_agent/lib/micro_ros_agent/micro_ros_agent" ]]; then
        echo "OK"
    else
        echo "FAIL"
        echo "    Build: cd $SCRIPT_DIR && source /opt/ros/${ROS_DISTRO}/setup.bash && \\"
        echo "      colcon build --packages-select micro_ros_agent --cmake-args \\"
        echo "        -DMICROROSAGENT_SUPERBUILD=ON -DUAGENT_USE_SYSTEM_LOGGER=OFF \\"
        echo "        -DSPDLOG_FMT_EXTERNAL=OFF -DCMAKE_BUILD_TYPE=Release"
        exit 1
    fi
    printf "  %-30s ... " "smb_robot.launch.py"
    if ros2 launch smb_robot_bringup smb_robot.launch.py --show-args >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
        ros2 launch smb_robot_bringup smb_robot.launch.py --show-args 2>&1 | tail -10
        exit 1
    fi
    printf "  %-30s ... " "smb.launch.py (dispatcher)"
    if ros2 launch smb_robot_bringup smb.launch.py --show-args >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
        exit 1
    fi
    echo "[test_robot] --check OK. Nothing was started."
    exit 0
fi

# ----- Pre-launch cleanup ------------------------------------------------------
echo "[test_robot] Cleaning leftover processes..."
pkill -INT -f "ros2 launch smb_robot_bringup"  2>/dev/null || true
pkill -INT -f "ros2 launch smb.launch.py"      2>/dev/null || true
sleep 2
# Nuke snap micro-ros-agent processes.
pkill -9 -f "snap.micro-ros-agent"  2>/dev/null || true
# Kill remaining node binaries (snap agents spawn their own process names).
pkill -9 -f "micro_ros_agent"        2>/dev/null || true
pkill -9 -f "async_slam_toolbox_node"     2>/dev/null || true
pkill -9 -f "robot_state_publisher"  2>/dev/null || true
pkill -9 -f "nav2_container"        2>/dev/null || true
pkill -9 -f "rviz2"                 2>/dev/null || true
pkill -9 -f "supervisor"             2>/dev/null || true
pkill -9 -f "ekf_node"               2>/dev/null || true
pkill -9 -f "lifecycle_manager"      2>/dev/null || true
pkill -9 -f "controller_server"      2>/dev/null || true
pkill -9 -f "planner_server"         2>/dev/null || true
pkill -9 -f "bt_navigator"           2>/dev/null || true
pkill -9 -f "behavior_server"        2>/dev/null || true
pkill -9 -f "waypoint_follower"      2>/dev/null || true
# Catch any zombie python launch wrappers left after their children died.
pkill -9 -f "ros2 launch smb.launch.py" 2>/dev/null || true
sleep 1
echo "[test_robot] Cleanup done."

# ----- Cleanup on exit ---------------------------------------------------------
cleanup() {
    echo
    echo "[test_robot] Shutting down..."
    pkill -INT -f "ros2 launch smb_robot_bringup"  2>/dev/null || true
    pkill -INT -f "ros2 launch smb.launch.py"      2>/dev/null || true
    sleep 2
    pkill -9 -f "snap.micro-ros-agent"    2>/dev/null || true
    pkill -9 -f "micro_ros_agent"        2>/dev/null || true
    pkill -9 -f "async_slam_toolbox_node"     2>/dev/null || true
    pkill -9 -f "robot_state_publisher"  2>/dev/null || true
    pkill -9 -f "nav2_container"        2>/dev/null || true
    pkill -9 -f "rviz2"                 2>/dev/null || true
    pkill -9 -f "supervisor"             2>/dev/null || true
    pkill -9 -f "ekf_node"               2>/dev/null || true
    pkill -9 -f "lifecycle_manager"      2>/dev/null || true
    pkill -9 -f "controller_server"      2>/dev/null || true
    pkill -9 -f "planner_server"         2>/dev/null || true
    pkill -9 -f "bt_navigator"           2>/dev/null || true
    pkill -9 -f "behavior_server"        2>/dev/null || true
    pkill -9 -f "waypoint_follower"      2>/dev/null || true
    pkill -9 -f "ros2 launch smb.launch.py" 2>/dev/null || true
    echo "[test_robot] Done."
}
trap cleanup INT TERM EXIT

# ----- Launch ------------------------------------------------------------------
echo
echo "[test_robot] Workspace : $SCRIPT_DIR"
echo "[test_robot] ROS distro: ${ROS_DISTRO}"
echo "[test_robot] Agent     : source-built micro_ros_agent (install/micro_ros_agent/lib/micro_ros_agent/micro_ros_agent)"
echo "[test_robot] Command   : ros2 launch smb_robot_bringup smb.launch.py mode:=robot"
echo
echo "[test_robot] Tip: in another terminal:"
echo "              ./test_teleop.sh    — drive via /cmd_vel"
echo "              ./test_nav2_goal.sh — send NavigateToPose goals"
echo
echo "[test_robot] Order of operations:"
echo "              1) Wait ~10s for ESP32 → micro-ROS handshake."
echo "                 Verify: ros2 topic hz /scan   →  ~10 Hz"
echo "                 Verify: ros2 topic hz /odom   →  ~50 Hz"
echo "              2) Activate slam_toolbox:"
echo "                 ros2 lifecycle set /slam_toolbox activate"
echo "                 Verify: ros2 topic echo /map --once"
echo "              3) Activate Nav2 (needs /map to exist):"
echo "                 ros2 lifecycle set /lifecycle_manager_navigation activate"
echo

ros2 launch smb_robot_bringup smb.launch.py mode:=robot
exit_code=$?
cleanup
exit "$exit_code"
