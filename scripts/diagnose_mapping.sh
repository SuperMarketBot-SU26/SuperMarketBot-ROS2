#!/usr/bin/env bash
# Read-only SLAM/odometry audit. This script never publishes cmd_vel or a goal.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROS_DISTRO="${ROS_DISTRO:-lyrical}"
DURATION="${1:-10.0}"

source "/opt/ros/${ROS_DISTRO}/setup.bash"
if [[ -f "${WS_DIR}/install/setup.bash" ]]; then
    source "${WS_DIR}/install/setup.bash"
elif [[ -f "${SCRIPT_DIR}/install/setup.bash" ]]; then
    source "${SCRIPT_DIR}/install/setup.bash"
fi

echo "[diagnose_mapping] Robot must remain stationary; motors are not commanded."
ros2 run smb_nodes mapping_diagnostics --ros-args -p duration:="${DURATION}"
