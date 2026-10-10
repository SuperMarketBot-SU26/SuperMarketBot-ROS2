#!/usr/bin/env bash
# test_teleop.sh — keyboard driver for the sim (or real robot).
#
# Usage:
#   ./test_teleop.sh             # spawns xterm with teleop_twist_keyboard (default)
#   ./test_teleop.sh false       # do not spawn xterm; just clean up leftover teleop
#   ./test_teleop.sh --check     # verify dependencies (xterm + teleop package) only
#
# What it does:
#   1. Cleans leftover teleop processes from a previous run.
#   2. Spawns an xterm window with teleop_twist_keyboard. Teleop publishes
#      plain geometry_msgs/Twist, which it remaps to ``/cmd_vel_manual`` —
#      that is the manual-input topic that ``smb_nodes.supervisor``
#      subscribes to. (We do NOT publish to ``/cmd_vel`` directly:
#      ``/cmd_vel`` is the contract output of the supervisor and the
#      firmware/ros_gz_bridge listens there. Publishing teleop to
#      ``/cmd_vel`` directly would bypass the supervisor's ESTOP gate —
#      see supervisor.py docstring.)
#      Nav2 sends TwistStamped to ``/cmd_vel_nav`` → supervisor →
#      ``/cmd_vel`` (separate path).
#   3. Cleans up teleop processes on Ctrl-C / exit. Does NOT touch the sim —
#      run test_sim.sh in parallel to get the full bringup.
#
# Why this is a separate script from test_sim.sh:
#   - Decouples lifetime: Ctrl-C in this window stops the teleop only; the sim
#     keeps running. Useful when you want to swap in Nav2 or hand-drive tests.
#   - Reusable: same driver works against the real robot via the supervisor's
#     manual input; no code change needed.
#   - Replaceable: a future gamepad_joy/cmd_vel script can drop in cleanly.
#
# Requires:
#   - xterm (sudo apt install xterm)
#   - teleop_twist_keyboard (apt install ros-$ROS_DISTRO-teleop-twist-keyboard)
#
# Default key bindings (i/j/k/l/u/m/o/,/.; q/z, etc.) are inherited from
# teleop_twist_keyboard. See its README for the full layout.

set -eo pipefail

# ----- Parse args ---------------------------------------------------------------
# Optional arg: "true" (default; spawn xterm), "false" (cleanup only), or "--check".
opt="${1:-true}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_DISTRO="${ROS_DISTRO:-lyrical}"

# ----- Source ROS ---------------------------------------------------------------
# Always source setup.bash so ros2 run can find the teleop executable.
# shellcheck source=/opt/ros/lyrical/setup.bash
source /opt/ros/${ROS_DISTRO}/setup.bash 2>/dev/null || {
    echo "[test_teleop] ERROR: failed to source /opt/ros/${ROS_DISTRO}/setup.bash"
    echo "                Is ROS2 ${ROS_DISTRO} installed? Current ROS_DISTRO=${ROS_DISTRO}"
    exit 1
}

# ----- --check short-circuit ----------------------------------------------------
# Verify the dependencies are present without spawning anything. Used as a smoke
# test in CI / before deployment.
if [[ "$opt" == "--check" ]]; then
    echo "[test_teleop] --check mode: verifying dependencies (no teleop started)."
    printf "  %-30s ... " "xterm"
    if command -v xterm >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
        echo "    sudo apt install xterm"
        exit 1
    fi
    printf "  %-30s ... " "teleop_twist_keyboard"
    # ros2 pkg executables is the canonical way to check if a package is installed.
    if ros2 pkg executables teleop_twist_keyboard >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
        echo "    sudo apt install ros-${ROS_DISTRO}-teleop-twist-keyboard"
        exit 1
    fi
    echo "[test_teleop] --check OK."
    exit 0
fi

# ----- Cleanup ------------------------------------------------------------------
# Mirrors the cleanup logic in test_sim.sh but scoped to teleop only. Both
# scripts are independent: each one's Ctrl-C only kills its own processes.
#
# We still sweep the wider sim processes in kill_zombies in case the user ran
# the sim and teleop in the same terminal and Ctrl-C'd out of the wrong one;
# that keeps robustness without coupling the two scripts.
cleanup() {
    echo
    echo "[test_teleop] Shutting down..."
    # Kill the xterm first — it owns the keyboard and would otherwise keep the
    # script alive after Ctrl-C.
    if [[ -n "${TELEOP_XTERM_PID:-}" ]]; then
        kill "$TELEOP_XTERM_PID" 2>/dev/null || true
    fi
    pkill -f "teleop_twist_keyboard" 2>/dev/null || true
    pkill -f "xterm.*teleop_twist_keyboard" 2>/dev/null || true
    sleep 1
    # Catch-all: any orphan xterm or teleop the patterns above missed.
    kill_zombies
    echo "[test_teleop] Done."
}
trap cleanup INT TERM EXIT

# kill_zombies — final-pass sweep. Same logic as test_sim.sh; kept local so each
# script is self-contained and usable independently.
kill_zombies() {
    local pid
    for pid in $(pgrep -f "xterm.*teleop|teleop_twist_keyboard" 2>/dev/null | head -20); do
        if [[ "$pid" == "$$" || "$pid" == "$PPID" ]]; then
            continue
        fi
        local comm
        comm="$(ps -p "$pid" -o comm= 2>/dev/null || true)"
        case "$comm" in
            xterm|teleop_twist_keyboard)
                kill -9 "$pid" 2>/dev/null || true
                ;;
            *)
                : # unknown comm, leave it alone
                ;;
        esac
    done
}

# ----- Pre-launch cleanup -------------------------------------------------------
# Kill any leftover teleop from a previous run.
echo "[test_teleop] Cleaning leftover teleop processes..."
pkill -9 -f "teleop_twist_keyboard" 2>/dev/null || true
pkill -9 -f "xterm.*teleop_twist_keyboard" 2>/dev/null || true
sleep 1
kill_zombies
echo "[test_teleop] Cleanup done."

# ----- Mode: "false" (cleanup only) --------------------------------------------
if [[ "$opt" == "false" ]]; then
    echo "[test_teleop] Cleanup-only mode. Exiting."
    trap - INT TERM EXIT
    exit 0
fi

# ----- Spawn xterm with teleop --------------------------------------------------
# Default mode: open an xterm window with teleop_twist_keyboard. The xterm is
# its own window so the user controls the keyboard input there; this script
# stays in the foreground so Ctrl-C in this terminal cleanly stops the xterm.
#
# ros_gz_bridge maps /cmd_vel (ROS, supervisor output) -> /model/smb/cmd_vel
# (gz). The supervisor gates both Nav2 (/cmd_vel_nav → /cmd_vel) and
# teleop (/cmd_vel_manual → /cmd_vel). See config/ros_gz_bridge.yaml and
# smb_nodes/supervisor.py for the topic contract.
# smb_nodes/supervisor.py.
if ! command -v xterm >/dev/null 2>&1; then
    echo "[test_teleop] ERROR: xterm is not installed."
    echo "                sudo apt install xterm"
    exit 1
fi

if ! ros2 pkg executables teleop_twist_keyboard >/dev/null 2>&1; then
    echo "[test_teleop] ERROR: teleop_twist_keyboard package not found."
    echo "                sudo apt install ros-${ROS_DISTRO}-teleop-twist-keyboard"
    exit 1
fi

echo
echo "[test_teleop] Workspace : $SCRIPT_DIR"
echo "[test_teleop] ROS distro: $ROS_DISTRO"
echo "[test_teleop] Spawning xterm with teleop_twist_keyboard..."
echo "[test_teleop]   - Click into the xterm to send keyboard input."
echo "[test_teleop]   - Default keys: i/k/j/l/u/o/m/,/. + q/z + space."
echo "[test_teleop]   - Press Ctrl-C here (or close the xterm) to stop."
echo

# -hold: keep xterm open after the child exits, so you can see errors.
# -e:   run the command inside the xterm.
# Remap teleop's default cmd_vel -> /cmd_vel_manual, the supervisor's
# manual-input topic. (Publishing teleop directly to /cmd_vel would bypass
# the supervisor's ESTOP gate — see supervisor.py docstring.)
# Background with `&`, capture PID so cleanup() can kill it.
xterm -hold -e "ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/cmd_vel_manual" &
TELEOP_XTERM_PID=$!

# Block until the xterm is closed (or Ctrl-C here).
wait "$TELEOP_XTERM_PID" 2>/dev/null || true
cleanup
