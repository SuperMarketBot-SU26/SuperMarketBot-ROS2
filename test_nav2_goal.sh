#!/usr/bin/env bash
# test_nav2_goal.sh — send a NavigateToPose goal to the running sim.
#
# Usage:
#   ./test_nav2_goal.sh                 # goal = current pose + (1.0, 0.0)
#   ./test_nav2_goal.sh 2.0 0.5         # goal = current pose + (2.0, 0.5)
#   ./test_nav2_goal.sh --check         # verify /navigate_to_pose is reachable
#
# Assumes:
#   - The sim is already up (use smb_restart_nav2.sh or NAV2=true ./test_sim.sh).
#   - Nav2 lifecycle manager reports "Managed nodes are active".
#
# Requires:
#   - ros2 action CLI + Python 3 (always present with a sourced ROS env).
#   - pyyaml (for parsing the PoseWithCovarianceStamped message).

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_DISTRO="${ROS_DISTRO:-lyrical}"

# ----- Args --------------------------------------------------------------------
if [[ "${1:-}" == "--check" ]]; then
    do_check_only=1
    shift
fi
DX="${1:-1.0}"   # meters forward of current pose
DY="${2:-0.0}"   # meters left of current pose

# ----- Source ROS --------------------------------------------------------------
source "/opt/ros/${ROS_DISTRO}/setup.bash" 2>/dev/null || {
    echo "[test_nav2_goal] ERROR: failed to source /opt/ros/${ROS_DISTRO}/setup.bash"
    exit 1
}

# ----- --check short-circuit ---------------------------------------------------
if [[ "${do_check_only:-0}" -eq 1 ]]; then
    echo "[test_nav2_goal] --check mode: verifying dependencies."
    printf "  %-30s ... " "ros2 action CLI"
    if ros2 action --help >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
        exit 1
    fi
    printf "  %-30s ... " "pyyaml"
    if python3 -c 'import yaml' >/dev/null 2>&1; then
        echo "OK"
    else
        echo "FAIL"
        echo "    pip install pyyaml"
        exit 1
    fi
    printf "  %-30s ... " "/navigate_to_pose server"
    for _ in 1 2 3 4 5; do
        if ros2 action list 2>/dev/null | grep -q '^/navigate_to_pose$'; then
            echo "OK"
            exit 0
        fi
        sleep 1
    done
    echo "NOT FOUND"
    echo "    Is Nav2 running? Try: NAV2=true ./test_sim.sh"
    exit 1
fi

# ----- Sanity ------------------------------------------------------------------
echo "[test_nav2_goal] Workspace : $SCRIPT_DIR"
echo "[test_nav2_goal] Offset    : dx=$DX m, dy=$DY m"
echo

if ! ros2 action list 2>/dev/null | grep -q '^/navigate_to_pose$'; then
    echo "[test_nav2_goal] ERROR: /navigate_to_pose action server not found."
    echo "                  Is Nav2 running? Try: NAV2=true ./test_sim.sh"
    exit 1
fi
echo "[test_nav2_goal] Action server present."

# ----- Read current pose -------------------------------------------------------
# Try /pose first (slam_toolbox publishes it in /map — the frame Nav2 plans in).
# Fall back to /odom if slam_toolbox isn't publishing yet. The fallback lets you
# drive goals immediately after bringup, before the first SLAM fix arrives.
POSE_RAW="$(timeout 3 ros2 topic echo --once --field pose.pose /pose 2>/dev/null || \
             timeout 3 ros2 topic echo --once --field pose.pose /odom 2>/dev/null || true)"
# ros2 topic echo --field appends a trailing '---' document separator which
# trips yaml.safe_load. Strip it.
POSE_RAW="$(printf '%s' "$POSE_RAW" | sed '/^---$/d')"

if [[ -z "$POSE_RAW" ]]; then
    echo "[test_nav2_goal] WARN: could not read any pose; using origin (0,0,0)."
    CUR_X=0.0; CUR_Y=0.0; CUR_YAW=0.0
    FRAME_ID="map"
else
    read CUR_X CUR_Y _ CUR_QX CUR_QY CUR_QZ CUR_QW < <(python3 - <<PY
import yaml, sys
# ros2 topic echo --field pose.pose returns the inner geometry_msgs/Pose, which
# is a clean single-document YAML (no covariance array spanning 36 elements
# with embedded '---' separators that would trip safe_load).
data = yaml.safe_load("""$POSE_RAW""")
if not isinstance(data, dict):
    sys.exit(1)
p = data.get('position', {})
o = data.get('orientation', {})
print(p.get('x', 0.0), p.get('y', 0.0), p.get('z', 0.0),
      o.get('x', 0.0), o.get('y', 0.0), o.get('z', 0.0), o.get('w', 1.0))
PY
)
    # slam_toolbox /pose is in /map (the goal frame). /odom fallback would only
    # work for short-term planning, but in practice the SLAM pose is up within
    # a few seconds of bringup; the fallback mostly exists for "sim is just
    # starting" scenarios.
    FRAME_ID="map"
    CUR_YAW=$(python3 -c "
import math
qx, qy, qz, qw = $CUR_QX, $CUR_QY, $CUR_QZ, $CUR_QW
print(math.atan2(2*(qw*qz+qx*qy), 1-2*(qy*qy+qz*qz)))
")
    echo "[test_nav2_goal] Current pose (frame=$FRAME_ID): x=$CUR_X y=$CUR_Y yaw=$CUR_YAW"
fi

# ----- Compute goal pose -------------------------------------------------------
# Rotate (DX, DY) by current yaw (body-frame offset) and add to current pose.
read GOAL_X GOAL_Y GOAL_YAW GOAL_QX GOAL_QY GOAL_QZ GOAL_QW < <(python3 -c "
import math
cx, cy, cyaw = $CUR_X, $CUR_Y, $CUR_YAW
dx, dy = $DX, $DY
gx = cx + dx*math.cos(cyaw) - dy*math.sin(cyaw)
gy = cy + dx*math.sin(cyaw) + dy*math.cos(cyaw)
gyaw = cyaw  # face the same direction at the goal
print(f'{gx} {gy} {gyaw} 0.0 0.0 {math.sin(gyaw/2)} {math.cos(gyaw/2)}')
")
echo "[test_nav2_goal] Goal pose   (frame=$FRAME_ID): x=$GOAL_X y=$GOAL_Y yaw=$GOAL_YAW"
echo

# ----- Send goal ---------------------------------------------------------------
GOAL_YAML=$(cat <<EOF
{pose: {header: {frame_id: "$FRAME_ID"}, pose: {position: {x: $GOAL_X, y: $GOAL_Y, z: 0.0}, orientation: {x: $GOAL_QX, y: $GOAL_QY, z: $GOAL_QZ, w: $GOAL_QW}}}}
EOF
)

echo "[test_nav2_goal] Sending NavigateToPose goal..."
echo "[test_nav2_goal]   $GOAL_YAML"
echo "[test_nav2_goal]   (Ctrl-C here to cancel.)"
echo

ros2 action send_goal --feedback /navigate_to_pose nav2_msgs/action/NavigateToPose "$GOAL_YAML"

echo
echo "[test_nav2_goal] Done."