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
elif [[ "$opt" == "--no-nav2" ]]; then
    do_no_nav2=1
elif [[ "$opt" == "--no-slam" ]]; then
    do_no_slam=1
elif [[ -n "$opt" && "$opt" != "--check" ]]; then
    echo "Usage: $0 [--check]"
    echo "       $0 --no-nav2   (run without Nav2 — use for teleop-only testing)"
    echo "       $0 --no-slam   (run without SLAM — teleop without map drift)"
    echo "       --check        verify deps + launch syntax only"
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
    pkill -9 -f "unified_relay"          2>/dev/null || true
    pkill -9 -f "scan_relay"             2>/dev/null || true
    pkill -9 -f "odom_imu_relay"         2>/dev/null || true
    pkill -9 -f "ekf_node"               2>/dev/null || true
    pkill -9 -f "lifecycle_manager"      2>/dev/null || true
    pkill -9 -f "controller_server"      2>/dev/null || true
    pkill -9 -f "planner_server"         2>/dev/null || true
    pkill -9 -f "bt_navigator"           2>/dev/null || true
    pkill -9 -f "behavior_server"        2>/dev/null || true
    pkill -9 -f "waypoint_follower"      2>/dev/null || true
    # Catch any zombie python launch wrappers left after their children died.
    pkill -9 -f "ros2 launch smb.launch.py" 2>/dev/null || true
    # Purge lingering ROS2 / DDS shared-memory buffers from previous runs
    rm -rf /dev/shm/fastrtps_* /dev/shm/ros2* /dev/shm/sem.* 2>/dev/null || true
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
        pkill -9 -f "unified_relay"          2>/dev/null || true
        pkill -9 -f "scan_relay"             2>/dev/null || true
        pkill -9 -f "odom_imu_relay"         2>/dev/null || true
        pkill -9 -f "ekf_node"               2>/dev/null || true
        pkill -9 -f "lifecycle_manager"      2>/dev/null || true
        pkill -9 -f "controller_server"      2>/dev/null || true
        pkill -9 -f "planner_server"         2>/dev/null || true
        pkill -9 -f "bt_navigator"           2>/dev/null || true
        pkill -9 -f "behavior_server"        2>/dev/null || true
        pkill -9 -f "waypoint_follower"      2>/dev/null || true
    pkill -9 -f "ros2 launch smb.launch.py" 2>/dev/null || true
  # Purge lingering ROS2 / DDS shared-memory buffers from this session
  rm -rf /dev/shm/fastrtps_* /dev/shm/ros2* /dev/shm/sem.* 2>/dev/null || true
  # Trim old launch logs to keep the latest 5 (most recent ones stay)
  find "$LOG_DIR" -maxdepth 1 -name '*.log' -type f -mmin +60 \
    -printf '%T@ %p\n' 2>/dev/null \
    | sort -rn | tail -n +6 | awk '{print $2}' | xargs -r rm -f
  echo "[test_robot] Done."
}
trap cleanup INT TERM EXIT

# ----- Launch + auto-activate SLAM + Nav2 --------------------------------------
echo
echo "[test_robot] Workspace : $SCRIPT_DIR"
echo "[test_robot] ROS distro: ${ROS_DISTRO}"
echo "[test_robot] Agent     : source-built micro_ros_agent (install/micro_ros_agent/lib/micro_ros_agent/micro_ros_agent)"
echo "[test_robot] Command   : ros2 launch smb_robot_bringup smb.launch.py mode:=robot"
echo
echo "[test_robot] Tip: in another terminal:"
echo "              ./test_teleop.sh    — drive via /cmd_vel"
echo "              ./test_nav2_goal.sh — send NavigateToPose goals"
echo "              --no-nav2 flag skips Nav2 entirely (Nav2 interferes with teleop)"
echo
echo "[test_robot] Auto-activation: ~15s after launch, once /scan is detected,"
echo "              SLAM + Nav2 are configured + activated automatically."
echo "              If /scan does not appear (ESP32 handshake slow / failed),"
echo "              the manual commands below still work."
echo
echo "[test_robot] Manual fallback:"
echo "              ros2 lifecycle set /slam_toolbox configure"
echo "              ros2 lifecycle set /slam_toolbox activate"
echo "              ros2 service call /lifecycle_manager_navigation/manage_nodes \\"
echo "                nav2_msgs/srv/ManageLifecycleNodes '{\"command: 0}'"
echo

# Run launch in background so a sibling helper can auto-activate SLAM + Nav2
# once the ESP32 → micro-ROS handshake completes (~10-30s on WiFi UDP).
#
# We ALSO tee launch + helper output to a file so the helper's progress
# (which stages succeeded, where it timed out) survives terminal scrollback.
LOG_DIR="${SCRIPT_DIR}/.test_robot_logs"
mkdir -p "$LOG_DIR"
SESSION_TS="$(date +%Y%m%d-%H%M%S)"
LAUNCH_LOG="$LOG_DIR/launch_${SESSION_TS}.log"
HELPER_LOG="$LOG_DIR/auto_activate_${SESSION_TS}.log"

ros2 launch smb_robot_bringup smb.launch.py mode:=robot \
  ${do_no_nav2:+use_nav2:=false} \
  ${do_no_slam:+use_slam:=false} \
  > >(tee "$LAUNCH_LOG") 2>&1 &
launch_pid=$!
echo "[test_robot] launch output: $LAUNCH_LOG"
echo "[test_robot] helper output: $HELPER_LOG"

# Background helper: wait for the ESP32 → micro-ROS handshake to settle,
# then activate SLAM + Nav2 in the right order, with enough time for the
# TF chain to be stable before the global_costmap turns on its first
# periodic updateMap() tick (otherwise the very first lookup is for
# transform at "now()" before any data has been received and the
# global_costmap faults with "extrapolation into the past").
(
  # All helper progress also goes to HELPER_LOG so it survives the user
  # scrolling the launch terminal.
  exec > >(tee -a "$HELPER_LOG") 2>&1

  # --- Helper utilities. The waiter functions return 0 (ready) or 1 (timeout)
  # and write progress to stderr so the helper log reads top-down. ------------
  wait_topic_pub() {
    # $1 = topic name, $2 = max seconds to wait
    local topic="$1"; local max="${2:-60}"
    for i in $(seq 1 "$max"); do
      if ! kill -0 "$launch_pid" 2>/dev/null; then return 1; fi
      local n
      n=$(timeout 2 ros2 topic info "$topic" --verbose 2>/dev/null \
            | awk '/^Publisher count:/ {print $3; exit}')
      if [[ -n "$n" && "$n" -ge 1 ]] 2>/dev/null; then return 0; fi
      sleep 1
    done
    return 1
  }

  wait_topic_data() {
    # $1 = topic name, $2 = max seconds to wait
    # Returns 0 when >=1 message arrives on the topic within the budget.
    # Uses a tiny Python subscriber (rclpy) instead of `ros2 topic hz`,
    # because `ros2 topic hz` only exits on SIGINT — it never returns 0
    # on its own, so a `timeout` wrapper always kills it (exit 124) and
    # our waiter would loop forever.
    #
    # Probe is generic: it parses the type from `ros2 topic info <topic>`,
    # maps the ROS2 type name to a Python class via importlib, and
    # subscribes. `rclpy.subscription_subscription` requires the actual
    # message class — passing `object` or a placeholder type does not
    # register a real subscription with the DDS layer.
    local topic="$1"; local max="${2:-30}"
    local deadline=$((SECONDS + max))
    while (( SECONDS < deadline )); do
      if ! kill -0 "$launch_pid" 2>/dev/null; then return 1; fi
      # Quick precheck: bail out fast if topic has no publisher at all
      # (e.g. ESP32 hasn't connected yet).
      local n_pubs
      n_pubs=$(timeout 2 ros2 topic info "$topic" --verbose 2>/dev/null \
                 | awk '/^Publisher count:/ {print $3; exit}')
      if [[ -z "$n_pubs" || "$n_pubs" -lt 1 ]]; then
        sleep 1
        continue
      fi
      if timeout 5 python3 - "$topic" <<'PY' >/dev/null 2>&1
import sys, importlib, time, rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from rclpy.node import Node

qos = QoSProfile(depth=10, reliability=QoSReliabilityPolicy.BEST_EFFORT,
                 durability=QoSDurabilityPolicy.VOLATILE)

class Probe(Node):
    def __init__(self, topic):
        super().__init__('__hz_probe')
        self._got = False
        # Static type map for our known topics. Adding a new topic requires
        # an entry here; this keeps the helper script self-contained.
        type_str = {
            '/scan':       'sensor_msgs/msg/LaserScan',
            '/scan_relay': 'sensor_msgs/msg/LaserScan',
            '/map':        'nav_msgs/msg/OccupancyGrid',
            '/odom':       'nav_msgs/msg/Odometry',
            '/odom_relay': 'nav_msgs/msg/Odometry',
            '/tf':         'tf2_msgs/msg/TFMessage',
            '/imu':        'sensor_msgs/msg/Imu',
            '/imu/data':   'sensor_msgs/msg/Imu',
            '/imu_relay':  'sensor_msgs/msg/Imu',
        }.get(topic, 'sensor_msgs/msg/LaserScan')
        pkg, _, rest = type_str.partition('/')
        msg_mod, _, cls_name = rest.partition('/')
        module = importlib.import_module(f'{pkg}.{msg_mod}')
        msg_cls = getattr(module, cls_name)
        self._sub = self.create_subscription(msg_cls, topic, self._cb, qos)

    def _cb(self, msg): self._got = True

rclpy.init()
n = Probe(sys.argv[1])
ex = SingleThreadedExecutor(); ex.add_node(n)
t_end = time.time() + 3.0
while not n._got and time.time() < t_end:
    ex.spin_once(timeout_sec=0.1)
ok = n._got
n.destroy_node()
if rclpy.ok(): rclpy.shutdown()
sys.exit(0 if ok else 1)
PY
      then return 0; fi
      sleep 1
    done
    return 1
  }

  # --- Stage 1: ESP32 → ROS2 handshake ---------------------------------------
  # Use a Python subscriber probe (not `ros2 topic hz`, which hangs forever
  # because it only exits on SIGINT). The probe waits up to 2s per try for
  # the first message; up to 30 tries covers ESP32's worst-case UDP handshake.
  echo "[test_robot] auto_activate: waiting for /scan_relay (stage 1 / 3)..."
  if ! wait_topic_data /scan_relay 30; then
    echo "[test_robot] auto_activate: /scan_relay never had data — checking raw /scan..."
    if ! wait_topic_data /scan 30; then
      echo "[test_robot] auto_activate: no /scan data after 60s."
      echo "[test_robot] auto_activate: ESP32 handshake failed. Use manual fallback."
      exit 0
    fi
  fi
  echo "[test_robot] auto_activate:   /scan_relay has data."

  # --- Stage 2: SLAM lifecycle (skip if use_slam:=false) ------------------
  # Check if slam_toolbox node exists before attempting lifecycle operations.
  if ! ros2 node list 2>/dev/null | grep -q '/slam_toolbox'; then
    echo "[test_robot] auto_activate: SLAM not running (use_slam:=false). Skipping."
  else
    echo "[test_robot] auto_activate: activating SLAM (stage 2 / 3)..."
    if ros2 lifecycle set /slam_toolbox configure 2>/dev/null \
       && ros2 lifecycle set /slam_toolbox activate 2>/dev/null; then
      echo "[test_robot] auto_activate:   SLAM configured + activated."
    else
      echo "[test_robot] auto_activate:   SLAM lifecycle FAILED. Run manually."
      exit 0
    fi

    # --- Stage 3: Wait for /map publisher + extra TF warmup --------------------
    echo "[test_robot] auto_activate: waiting for SLAM /map (stage 3 / 3)..."
    if ! wait_topic_pub /map 60; then
      echo "[test_robot] auto_activate:   /map never got a publisher. SLAM may be unhealthy."
      echo "[test_robot] auto_activate:   Skipping Nav2 activation. Use manual fallback."
      exit 0
    fi
    echo "[test_robot] auto_activate:   /map has a publisher."
    # SLAM's first TF publish (map → odom) trails /map by ~1s.
    echo "[test_robot] auto_activate: TF warm-up 5s..."
    sleep 5
  fi

  # --- Stage 4: Nav2 lifecycle manager (skip if use_nav2:=false) ------------
  if ! ros2 node list 2>/dev/null | grep -q '/controller_server'; then
    echo "[test_robot] auto_activate: Nav2 not running (use_nav2:=false). Skipping."
  else
    echo "[test_robot] auto_activate: activating Nav2..."
    if ros2 service call /lifecycle_manager_navigation/manage_nodes \
         nav2_msgs/srv/ManageLifecycleNodes "{command: 0}" 2>/dev/null; then
      echo "[test_robot] auto_activate:   Nav2 manager configured + activated."
    else
      echo "[test_robot] auto_activate:   Nav2 manager FAILED. Run manually."
      exit 0
    fi
  fi

  echo "[test_robot] auto_activate: SLAM + Nav2 are now active. Drive: ./test_teleop.sh"
) &
activate_pid=$!

# Wait for launch to exit (user Ctrl-C or process death).
wait "$launch_pid"
exit_code=$?

# Stop the activation helper if it's still in its sleep window.
kill "$activate_pid" 2>/dev/null || true
wait "$activate_pid" 2>/dev/null || true

cleanup
exit "$exit_code"
