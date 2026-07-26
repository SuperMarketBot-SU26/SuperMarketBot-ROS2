#!/usr/bin/env bash
# test_robot.sh — one-command test for the real-robot bringup.
#
# Usage:
#   ./test_robot.sh                 # start micro-ROS agent + robot bringup (with RViz)
#   ./test_robot.sh false           # robot bringup only (no RViz)
#   ./test_robot.sh --check         # verify deps + launch syntax, do not start anything
#
# Env vars:
#   ROS_DISTRO           (default: lyrical)
#   AGENT_TRANSPORT      (default: udp4)         — micro-ROS agent transport
#   AGENT_PORT           (default: 8888)          — micro-ROS agent port
#   ESP32_AGENT_IP       (default: empty)         — if set, agent binds to this interface
#                                                    instead of 0.0.0.0 (use to match ESP32's
#                                                    MICRO_ROS_AGENT_IP)
#   SKIP_AGENT           (default: false)         — if true, don't start the agent;
#                                                    useful when it's already running
#                                                    in another terminal.
#
# What it does:
#   1. Cleans leftover sim/slam/agent processes from a previous run.
#   2. Starts micro-ROS agent in background on UDP 8888 (unless SKIP_AGENT=true).
#   3. Launches robot bringup via smb.launch.py mode:=robot (URDF + SLAM + RViz).
#   4. Cleans up agent + launch on Ctrl-C / exit.
#
# Telemetry input (teleop) is NOT included here. To drive the robot, run
# ./test_teleop.sh in another terminal. This separation lets you Ctrl-C
# teleop without killing the bringup.
#
# Requires:
#   - micro_ros_agent (apt: ros-${ROS_DISTRO}-micro-ros-agent; or source build
#     via the entry in ros2_ws.repos). On lyrical this is NOT on apt — vendor
#     from source per the rule in .cursor/rules/30-ros2-guidelines.mdc.
#   - The ESP32 must be running MicroRos.h and reachable on the WiFi network.

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_DISTRO="${ROS_DISTRO:-lyrical}"
AGENT_TRANSPORT="${AGENT_TRANSPORT:-udp4}"
AGENT_PORT="${AGENT_PORT:-8888}"
SKIP_AGENT="${SKIP_AGENT:-false}"

# ----- Args --------------------------------------------------------------------
opt="${1:-true}"

if [[ "$opt" == "--check" ]]; then
    do_check_only=1
    HEADLESS="${2:-false}"
elif [[ -z "$opt" ]]; then
    opt="true"
elif [[ "$opt" != "true" && "$opt" != "false" ]]; then
    echo "Usage: $0 [true|false] [--check]"
    echo "       true|false   Open RViz2 (default true)"
    echo "       --check      Verify deps + launch syntax only"
    exit 1
fi

OPEN_RVIZ="$opt"

# ----- Sanity checks -----------------------------------------------------------
if [[ ! -d "$SCRIPT_DIR/install/smb_robot_bringup" ]]; then
    echo "ERROR: install/smb_robot_bringup not found."
    echo "Build it first:"
    echo "  cd $SCRIPT_DIR"
    echo "  source /opt/ros/${ROS_DISTRO}/setup.bash"
    echo "  colcon build --parallel-workers 2 --packages-select smb_msgs smb_bridge smb_nodes smb_robot smb_robot_bringup"
    exit 1
fi

if ! [[ -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]]; then
    echo "ERROR: /opt/ros/${ROS_DISTRO}/setup.bash not found."
    echo "Is ROS '${ROS_DISTRO}' installed? Try: ls /opt/ros/"
    exit 1
fi

# Source ROS (handle set -u semantics in /opt/ros setup.bash).
set +u
# shellcheck source=/opt/ros/lyrical/setup.bash
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source "$SCRIPT_DIR/install/setup.bash"

# ----- --check short-circuit ---------------------------------------------------
if [[ "${do_check_only:-0}" -eq 1 ]]; then
    echo "[test_robot] --check mode: verifying deps + launch syntax (no agent, no bringup)."
    printf "  %-30s ... " "micro_ros_agent"
    if ros2 pkg executables micro_ros_agent 2>/dev/null | grep -q .; then
        echo "OK"
    else
        echo "FAIL"
        echo "    On ${ROS_DISTRO}, the agent is NOT in apt. Vendor from source:"
        echo "    vcs import src < ros2_ws.repos   # adds micro_ros_agent entry"
        echo "    colcon build --packages-select micro_ros_agent"
        exit 1
    fi
    for f in smb.launch.py smb_robot.launch.py; do
        printf "  %-30s ... " "$f"
        if ros2 launch smb_robot_bringup "$f" --show-args >/dev/null 2>&1; then
            echo "OK"
        else
            echo "FAIL"
            ros2 launch smb_robot_bringup "$f" --show-args 2>&1 | tail -20
            exit 1
        fi
    done
    echo "[test_robot] --check OK. Nothing was started."
    trap - INT TERM EXIT
    exit 0
fi

# ----- Pre-flight: topics check ------------------------------------------------
# Refuse to start if a previous run is still publishing to /scan, /odom, or
# /clock (clock implies sim is still running). The agent binds to UDP so it
# won't conflict with leftover publishers, but stale slam_toolbox / RViz
# processes will eat messages.
echo "[test_robot] Cleaning leftover sim/agent/slam processes..."
pkill -INT -f "ros2 launch smb_robot_bringup" 2>/dev/null || true
pkill -INT -f "ros2 launch smb.launch.py"     2>/dev/null || true
sleep 2
pkill -9 -f "micro_ros_agent"                                                    2>/dev/null || true
pkill -9 -f "/opt/ros/lyrical/lib/slam_toolbox/.*async_slam_toolbox_node"          2>/dev/null || true
pkill -9 -x async_slam_toolbox_node                                                2>/dev/null || true
pkill -9 -f "/opt/ros/lyrical/lib/robot_state_publisher/robot_state_publisher"     2>/dev/null || true
pkill -9 -x robot_state_publi                                                      2>/dev/null || true
pkill -9 -f "/opt/ros/lyrical/lib/rviz2/rviz2.*smb_robot_bringup"                  2>/dev/null || true
pkill -9 -x rviz2                                                                 2>/dev/null || true
# Catch sim leftovers from a previous test_sim.sh session that might be on
# the same machine.
pkill -9 -f "/opt/ros/lyrical/lib/gz_sim_vendor/libexec/gz/sim10/gz-sim-main"     2>/dev/null || true
pkill -9 -f "gz-sim-gui-client"                                                    2>/dev/null || true
pkill -9 -f "/opt/ros/lyrical/lib/ros_gz_bridge/parameter_bridge"                  2>/dev/null || true
pkill -9 -x parameter_bridge                                                       2>/dev/null || true
sleep 1
echo "[test_robot] Cleanup done."

# ----- Start micro-ROS agent (if not skipped) ----------------------------------
AGENT_PID=""
if [[ "$SKIP_AGENT" == "true" ]]; then
    echo "[test_robot] SKIP_AGENT=true — assuming agent is already running."
else
    if ! ros2 pkg executables micro_ros_agent 2>/dev/null | grep -q .; then
        echo "ERROR: micro_ros_agent not built. On ${ROS_DISTRO} it is NOT in apt."
        echo "Either set SKIP_AGENT=true if you've started it another way, or:"
        echo "  vcs import src < ros2_ws.repos   # vendors the agent"
        echo "  colcon build --packages-select micro_ros_agent"
        exit 1
    fi
    echo "[test_robot] Starting micro-ROS agent on ${AGENT_TRANSPORT} port ${AGENT_PORT}..."
    # Background the agent. Its logs go to the agent log file so the user can
    # tail it separately. SIGINT propagation is handled by our trap below.
    AGENT_LOG="/tmp/smb_micro_ros_agent.log"
    ros2 run micro_ros_agent micro_ros_agent "${AGENT_TRANSPORT}" --port "${AGENT_PORT}" \
        > "${AGENT_LOG}" 2>&1 &
    AGENT_PID=$!
    # Give the agent a moment to bind the UDP socket so the ESP32 doesn't
    # bounce when it next sends a discovery packet.
    sleep 1
    if ! kill -0 "${AGENT_PID}" 2>/dev/null; then
        echo "[test_robot] Agent failed to start. Last 20 log lines:"
        tail -20 "${AGENT_LOG}" 2>/dev/null || true
        exit 1
    fi
    echo "[test_robot] Agent PID=${AGENT_PID}, log=${AGENT_LOG}"
fi

# ----- Cleanup on Ctrl-C -------------------------------------------------------
cleanup() {
    echo
    echo "[test_robot] Shutting down..."
    # Bring down the launch first (it forwards SIGINT to its children).
    pkill -INT -f "ros2 launch smb_robot_bringup" 2>/dev/null || true
    pkill -INT -f "ros2 launch smb.launch.py"     2>/dev/null || true
    sleep 2
    # Then nuke the agent if we started it.
    if [[ -n "${AGENT_PID}" ]]; then
        kill "${AGENT_PID}" 2>/dev/null || true
    fi
    pkill -9 -f "micro_ros_agent" 2>/dev/null || true
    # Final sweep — anything still alive from our bringup.
    pkill -9 -f "/opt/ros/lyrical/lib/slam_toolbox/.*async_slam_toolbox_node"     2>/dev/null || true
    pkill -9 -x async_slam_toolbox_node                                              2>/dev/null || true
    pkill -9 -f "/opt/ros/lyrical/lib/robot_state_publisher/robot_state_publisher"  2>/dev/null || true
    pkill -9 -x robot_state_publi                                                    2>/dev/null || true
    pkill -9 -f "/opt/ros/lyrical/lib/rviz2/rviz2.*smb_robot_bringup"                2>/dev/null || true
    pkill -9 -x rviz2                                                                2>/dev/null || true
    sleep 1
    echo "[test_robot] Done."
}
trap cleanup INT TERM EXIT

# ----- Launch ------------------------------------------------------------------
if [[ "$OPEN_RVIZ" == "true" ]]; then
    LAUNCH_ARGS=(mode:=robot rviz:=true)
    HEADER="RViz=YES"
else
    LAUNCH_ARGS=(mode:=robot rviz:=false)
    HEADER="RViz=NO"
fi

echo
echo "[test_robot] Workspace : $SCRIPT_DIR"
echo "[test_robot] ROS distro: ${ROS_DISTRO}"
echo "[test_robot] Agent     : ${SKIP_AGENT} (transport=${AGENT_TRANSPORT}, port=${AGENT_PORT})"
echo "[test_robot] Mode      : ${HEADER}"
echo "[test_robot] Command   : ros2 launch smb_robot_bringup smb.launch.py ${LAUNCH_ARGS[*]}"
echo "[test_robot] Tip       : in another terminal, run ./test_teleop.sh to drive /cmd_vel"
echo

ros2 launch smb_robot_bringup smb.launch.py "${LAUNCH_ARGS[@]}"
exit_code=$?
cleanup
exit "$exit_code"