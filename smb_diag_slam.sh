#!/usr/bin/env bash
# smb_diag_slam.sh — extract the real configure() error from slam_toolbox.
set +u
source /opt/ros/lyrical/setup.bash
source /home/nhatkhoa1124/ros2_ws/install/setup.bash
set -u

echo "=== boot only slam_toolbox standalone (no Nav2, no Gazebo) ==="
timeout 15 ros2 launch smb_robot_bringup smb.launch.py mode:=sim headless:=true rviz:=false use_nav2:=false slam:=true 2>&1 | \
  grep -E "slam_toolbox|configure|error|exception|fail|stack|address|mapped|cannot|null|threw" -i | head -80
echo
echo "=== full lifecycle state ==="
timeout 5 ros2 lifecycle get /slam_toolbox 2>&1