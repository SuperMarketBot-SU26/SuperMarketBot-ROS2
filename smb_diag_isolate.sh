#!/usr/bin/env bash
# smb_diag_isolate.sh — boot twice with minimal noise:
#   pass A: sim + SLAM           (known good, just to confirm baseline)
#   pass B: sim + SLAM + Nav2    (the failing config)
# Then compare slam_toolbox lifecycle state in each.
set +u
source /opt/ros/lyrical/setup.bash
source /home/nhatkhoa1124/ros2_ws/install/setup.bash
set -u

short_log() {
  grep -E "slam_toolbox|configure|activate|fail|error|exception|abort" -i \
  | grep -vE "controller_|planner_|costmap_|bt_navigator|behavior_server|waypoint_follower|lifecycle_manager_navigation|feedback|publishing" \
  | head -50
}

boot() {
  local label="$1"; shift
  echo
  echo "============================================"
  echo "$label"
  echo "============================================"
  pkill -9 -x gz 2>/dev/null
  pkill -9 -x rviz2 2>/dev/null
  pkill -9 -x ros2daemon 2>/dev/null
  pkill -9 -x supervisor 2>/dev/null
  pkill -9 -x async_slam_toolbox_node 2>/dev/null
  pkill -9 -x parameter_bridge 2>/dev/null
  pkill -9 -x robot_state_publisher 2>/dev/null
  pkill -9 -x component_container 2>/dev/null
  sleep 2
  timeout 22 ros2 launch smb_robot_bringup smb.launch.py mode:=sim headless:=true rviz:=false "$@" 2>&1 | short_log
}

boot "PASS A: SLAM only (known good)" slam:=true use_nav2:=false
boot "PASS B: SLAM + Nav2 (the bug)"  slam:=true use_nav2:=true