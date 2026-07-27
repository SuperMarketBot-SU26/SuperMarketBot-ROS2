#!/usr/bin/env bash
# smb_restart_nav2.sh — full clean restart with Nav2 enabled.
# Run as: bash smb_restart_nav2.sh
set -uo pipefail

cd ~/ros2_ws

echo "=== Step 1: kill any leftover ROS/Gazebo/SLAM ==="
# Use exact process names to avoid matching our own shell.
pkill -9 -x ros2daemon       2>/dev/null || true
pkill -9 -x gz               2>/dev/null || true
pkill -9 -x gz-sim-main      2>/dev/null || true
pkill -9 -x gz-sim-gui-client 2>/dev/null || true
pkill -9 -x parameter_bridge  2>/dev/null || true
pkill -9 -x async_slam_toolbox_node  2>/dev/null || true
pkill -9 -x robot_state_publisher  2>/dev/null || true
pkill -9 -x rviz2            2>/dev/null || true
pkill -9 -x supervisor       2>/dev/null || true
sleep 3
echo "  done."

echo
echo "=== Step 2: verify environment ==="
echo "  NAV2=$NAV2"
if [[ -z "${NAV2:-}" ]]; then
  echo "  WARNING: NAV2 not set in this shell. Setting it now."
  export NAV2=true
fi
echo "  After ensure: NAV2=$NAV2"

echo
echo "=== Step 3: launch with NAV2=true ==="
echo "  (will run in foreground; Ctrl-C to stop)"
echo
NAV2=true ./test_sim.sh 2>&1 | tee /tmp/smb_restart.log