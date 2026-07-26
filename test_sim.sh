#!/usr/bin/env bash
# test_sim.sh — one-command test for the Phase 1 sim bringup.
#
# Usage:
#   ./test_sim.sh             # windowed (default; needs display)
#   ./test_sim.sh true        # headless (Gazebo server only, no RViz)
#   ./test_sim.sh false       # windowed
#   ./test_sim.sh --check     # verify launch-file syntax only, do not start sim
#
# Env vars:
#   ROS_DISTRO  (default: lyrical)
#   HEADLESS    (default: false; alternatives: true)
#
# What it does:
#   1. Cleans leftover sim/slam processes from a previous run.
#   2. Launches Gazebo + ros_gz_bridge + SLAM + (optional) RViz via smb.launch.py.
#   3. Cleans up all child processes on Ctrl-C / exit.
#
# Telemetry input (teleop) is NOT included here. To drive the sim with a keyboard,
# run this script in one terminal and `test_teleop.sh` in another. This separation
# lets you test the sim without teleop (e.g. driven by Nav2, or as a CI smoke test),
# and lets you Ctrl-C the teleop without killing the sim.
#
#   Terminal 1:  ./test_sim.sh            # sim only
#   Terminal 2:  ./test_teleop.sh         # autonomous keyboard driver see its own log
#   1. Sources /opt/ros/${ROS_DISTRO}/setup.bash and install/setup.bash
#   2. Tears down any leftover sim/Gazebo/SLAM processes from previous runs
#   3. Runs `ros2 launch smb_robot_bringup smb.launch.py mode:=sim ...`
#   4. Spawns an xterm running teleop_twist_keyboard (publishing /cmd_vel),
#      unless TELEOP=false. Default key bindings: i/k/j/l/u/o/m/,/. + q/z.
#   5. On Ctrl+C: cleans up all subprocesses (incl. the xterm) and exits

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS_DISTRO="${ROS_DISTRO:-lyrical}"

# ----- Args --------------------------------------------------------------------
HEADLESS="${1:-${HEADLESS:-}}"

# `--check` is a subcommand that only verifies launch-file syntax. Bypasses all
# display/memory preflight and skips the actual launch; used in CI / quick edit
# verification. Compatible with `HEADLESS=true ./test_sim.sh --check` (the bool
# is ignored when --check is passed).
if [[ "$HEADLESS" == "--check" ]]; then
    do_check_only=1
    HEADLESS="${2:-false}"
elif [[ -z "$HEADLESS" ]]; then
    HEADLESS="false"
elif [[ "$HEADLESS" != "true" && "$HEADLESS" != "false" ]]; then
    echo "Usage: $0 [true|false] [--check]"
    echo "       --check   verify launch-file syntax only (no sim, no cleanup)"
    exit 1
fi

# ----- Display-server pre-flight ----------------------------------------------
# NOTE: windowed mode (`gz sim <world>`, combined GUI+server process) is the
# default and works on both Wayland and X11 on Ubuntu 26.04 — the previous
# `gz sim -g` hang was the separate-process GUI client, not a fundamental
# Wayland issue. No preflight needed. If you ever do hit a hang with the
# combined-mode GUI, run `./test_sim.sh true` (or pass `headless:=true`) to
# drop the GUI entirely; the sim server still publishes everything.

# ----- Memory pre-flight -------------------------------------------------------
# Gazebo + RViz together need ~2-3 GB free. Headless mode is ~0.5 GB.
if [[ "${do_check_only:-0}" -eq 0 ]]; then
FREE_MEM_GB="$(free -g | awk '/^Mem:/ { print $7 }')"
if [[ "$HEADLESS" != "true" && "$FREE_MEM_GB" -lt 3 ]]; then
    echo "WARNING: only ${FREE_MEM_GB} GB RAM free. Gazebo GUI + RViz typically need 2-3 GB."
    echo "         Strongly recommend: ./test_sim.sh true   (headless, no GUI)"
    echo "         Or close some apps (Firefox with many tabs?) and re-run."
    echo
    read -r -p "Continue anyway? [y/N] " RESP || true
    if [[ "$RESP" != "y" && "$RESP" != "Y" ]]; then
        echo "Aborted. Run ./test_sim.sh true for headless mode."
        exit 1
    fi
fi
fi  # end preflight gate

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
source "/opt/ros/${ROS_DISTRO}/setup.bash"
source "$SCRIPT_DIR/install/setup.bash"

# ----- Cleanup on Ctrl+C -------------------------------------------------------
# Note: ros2 launch spawns children via Popen *without* putting them in a process
# group. SIGINT to the launch parent doesn't propagate to children — we have to
# explicitly nuke them. The patterns below are scoped tightly to our packages.
cleanup() {
    echo
    echo "[test_sim] Shutting down..."
    # Kill the teleop xterm first — it has its own stdin/Ctrl-C handling and
    # if we leave it open it'll keep the script alive after Ctrl-C.
    if [[ -n "${TELEOP_XTERM_PID:-}" ]]; then
        kill "$TELEOP_XTERM_PID" 2>/dev/null || true
    fi
    pkill -f "teleop_twist_keyboard" 2>/dev/null || true
    pkill -f "xterm.*teleop_twist_keyboard" 2>/dev/null || true
    # Send SIGINT to the launch orchestrator first so it can SIGINT its children
    # (it does forward SIGINT on graceful shutdown).
    pkill -INT -f "ros2 launch smb_robot_bringup" 2>/dev/null || true
    pkill -INT -f "ros2 launch smb.launch.py"     2>/dev/null || true
    sleep 2
    # Anything still alive gets SIGKILL'd.
    pkill -9 -f "/opt/ros/lyrical/lib/gz_sim_vendor/libexec/gz/sim10/gz-sim-main"     2>/dev/null || true
    pkill -9 -f "gz-sim-gui-client"                                                    2>/dev/null || true
    pkill -9 -f "/opt/ros/lyrical/lib/slam_toolbox/.*async_slam_toolbox_node"          2>/dev/null || true
    pkill -9 -x async_slam_toolbox_node                                                2>/dev/null || true
    pkill -9 -f "/opt/ros/lyrical/lib/ros_gz_bridge/parameter_bridge"                  2>/dev/null || true
    pkill -9 -x parameter_bridge                                                       2>/dev/null || true
    pkill -9 -f "/opt/ros/lyrical/lib/robot_state_publisher/robot_state_publisher"     2>/dev/null || true
    pkill -9 -x robot_state_publi                                                      2>/dev/null || true
    pkill -9 -f "/opt/ros/lyrical/lib/rviz2/rviz2.*smb_robot_bringup"                  2>/dev/null || true
    pkill -9 -x rviz2                                                                 2>/dev/null || true
    sleep 1
    # Catch-all: kill any remaining smb/gz/slam processes that the strict
    # patterns above missed (e.g. gz running a different world, or a child
    # that was orphaned). Wide net, but scoped to known sim binaries so we
    # never touch unrelated processes.
    kill_zombies
    echo "[test_sim] Done."
}
# Single trap covers Ctrl-C (INT), kill (TERM), and normal exit (EXIT). The
# pre-launch cleanup() call below is the only path that runs before any
# processes exist — it short-circuits cleanly via `|| true`.
trap cleanup INT TERM EXIT

# kill_zombies — final-pass sweep that catches anything the strict pkill patterns
# above missed (gz with a different world path, an orphaned child, a stray
# teleop xterm, etc.). Scoped to known sim binaries so we never touch unrelated
# processes. Used by both cleanup() on exit and by the pre-launch cleanup block.
kill_zombies() {
    # pgrep -f matches the full command line; head -50 caps the work in case
    # something is wildly stuck. Each pattern is a substring match against the
    # cmdline, so unrelated processes that happen to share a name are safe.
    local pid
    for pid in $(pgrep -f "gz-sim|parameter_bridge|robot_state_publisher|async_slam_toolbox_node|rviz2|teleop_twist_keyboard" 2>/dev/null | head -50); do
        # Don't kill our own shell, pgrep itself, or any grep/pkill in flight.
        if [[ "$pid" == "$$" || "$pid" == "$PPID" ]]; then
            continue
        fi
        local comm
        comm="$(ps -p "$pid" -o comm= 2>/dev/null || true)"
        # Skip anything whose executable isn't one we recognize — protects
        # against matching an unrelated process whose cmdline happens to
        # contain the substring (rare but possible).
        case "$comm" in
            gz-sim-*|gz-sim-main*|parameter_bridge|robot_state_publisher|async_slam_toolbox_node|rviz2|teleop_twist_keyboard)
                kill -9 "$pid" 2>/dev/null || true
                ;;
            *)
                : # unknown comm, leave it alone
                ;;
        esac
    done
}

# Pre-launch cleanup: kill any leftover sim/slam processes from a previous run.
# Same patterns as cleanup() — kept separate so we can re-run the script without
# re-running its own trap.
echo "[test_sim] Cleaning leftover sim/slam processes..."
pkill -INT -f "ros2 launch smb_robot_bringup"  2>/dev/null || true
pkill -INT -f "ros2 launch smb.launch.py"      2>/dev/null || true
sleep 2
pkill -9 -f "/opt/ros/lyrical/lib/gz_sim_vendor/libexec/gz/sim10/gz-sim-main"     2>/dev/null || true
pkill -9 -f "gz-sim-gui-client"                                                    2>/dev/null || true
pkill -9 -f "/opt/ros/lyrical/lib/slam_toolbox/.*async_slam_toolbox_node"          2>/dev/null || true
pkill -9 -x async_slam_toolbox_node                                                2>/dev/null || true
pkill -9 -f "/opt/ros/lyrical/lib/ros_gz_bridge/parameter_bridge"                  2>/dev/null || true
pkill -9 -x parameter_bridge                                                       2>/dev/null || true
pkill -9 -f "/opt/ros/lyrical/lib/robot_state_publisher/robot_state_publisher"     2>/dev/null || true
pkill -9 -x robot_state_publi                                                      2>/dev/null || true
pkill -9 -f "/opt/ros/lyrical/lib/rviz2/rviz2.*smb_robot_bringup"                  2>/dev/null || true
pkill -9 -x rviz2                                                                 2>/dev/null || true
# Kill any leftover teleop/xterm from previous runs.
pkill -9 -f "teleop_twist_keyboard"                                                2>/dev/null || true
pkill -9 -f "xterm.*teleop_twist_keyboard"                                          2>/dev/null || true
sleep 1
# Final catch-all: sweep any leftover sim-related processes the strict patterns
# above missed. Useful when the previous run was killed mid-cleanup (e.g. Ctrl-C
# during the sleep window) and left an orphan.
kill_zombies
echo "[test_sim] Cleanup done."

# ----- Build launch args -------------------------------------------------------
# Windowed mode = full Gazebo GUI + RViz. Headless mode = Gazebo server only
# (no display, no OGRE), bridge + SLAM still run. Useful for CI and remote boxes.
if [[ "$HEADLESS" == "true" ]]; then
    LAUNCH_ARGS=(mode:=sim headless:=true rviz:=false)
    HEADER="Windowed=NO, RViz=NO, gz sim server-only + bridge + SLAM"
else
    LAUNCH_ARGS=(mode:=sim headless:=false rviz:=true)
    HEADER="Windowed=YES (combined-mode GUI), RViz=YES"
fi

echo
echo "[test_sim] Workspace : $SCRIPT_DIR"
echo "[test_sim] ROS distro: $ROS_DISTRO"
echo "[test_sim] Mode      : headless=$HEADLESS  ($HEADER)"
echo "[test_sim] Command   : ros2 launch smb_robot_bringup smb.launch.py ${LAUNCH_ARGS[*]}"
echo

# ----- --check short-circuit ---------------------------------------------------
# Verify launch-file syntax without starting any processes. Useful for CI and
# for sanity-checking edits to launch files / config.
if [[ "${do_check_only:-0}" -eq 1 ]]; then
    echo "[test_sim] --check mode: verifying launch-file syntax (no sim started)."
    # Verify each of the three launch files parses. --show-args is the standard
    # "does this load?" probe.
    for f in smb.launch.py smb_sim.launch.py smb_robot.launch.py; do
        printf "  %-30s ... " "$f"
        if ros2 launch smb_robot_bringup "$f" --show-args >/dev/null 2>&1; then
            echo "OK"
        else
            echo "FAIL"
            echo
            echo "ros2 launch smb_robot_bringup $f --show-args produced an error:"
            ros2 launch smb_robot_bringup "$f" --show-args 2>&1 | tail -20
            exit 1
        fi
    done
    echo "[test_sim] --check OK. No processes were started; nothing to clean up."
    # Skip the trap-based cleanup since nothing is running.
    trap - INT TERM EXIT
    exit 0
fi

echo "[test_sim] Press Ctrl+C to stop and clean up."
echo
echo "[test_sim] (Tip: in another terminal, run ./test_teleop.sh to drive cmd_vel)"
echo

# ----- Launch ------------------------------------------------------------------
# We don't `exec` so the cleanup() trap stays alive after the launch replaces
# the shell. If we used `exec`, ros2 launch would inherit the trap but signals
# received by ros2 launch (instead of being forwarded by us) wouldn't trigger
# the trap. Keeping the wrapper lets us run cleanup() on any EXIT.
#
# Args: run ros2 launch directly (backgrounded so we can install our own
# signal handler and clean up afterwards).
ros2 launch smb_robot_bringup smb.launch.py "${LAUNCH_ARGS[@]}"
exit_code=$?
# When the launch exits (Ctrl-C, kill, or natural completion), run cleanup.
cleanup
exit "$exit_code"
