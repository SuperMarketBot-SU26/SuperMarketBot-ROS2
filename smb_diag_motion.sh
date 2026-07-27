#!/usr/bin/env bash
# smb_diag_motion.sh — figure out why the robot isn't following Nav2's path.
set -uo pipefail
# Don't fail on unset vars when sourcing ROS setup
set +u
source /opt/ros/lyrical/setup.bash
source /home/nhatkhoa1124/ros2_ws/install/setup.bash
set -u

echo "=== 1. Is the controller actually outputting velocities? ==="
echo "Sample /cmd_vel_nav for 3s (should be ~20Hz when active, ~0Hz when idle)"
timeout 4 ros2 topic hz /cmd_vel_nav 2>&1 &
HZ_PID=$!
sleep 4
echo
echo "=== 2. Sample last few TwistStamped values ==="
timeout 3 ros2 topic echo /cmd_vel_nav --once 2>&1
echo
echo "=== 3. Sample /cmd_vel (after supervisor) ==="
timeout 3 ros2 topic echo /cmd_vel --once 2>&1
echo
echo "=== 4. Lifecycle states ==="
for n in controller_server planner_server behavior_server bt_navigator waypoint_follower; do
  state=$(ros2 lifecycle get "/${n}" 2>&1 | tr -d '\n')
  echo "  /${n}: ${state}"
done
echo
echo "=== 5. Is the global plan being generated? ==="
timeout 3 ros2 topic echo /plan --once 2>&1 | head -5
echo
echo "=== 6. Is the local plan being generated? ==="
timeout 3 ros2 topic echo /local_plan --once 2>&1 | head -5
echo
echo "=== 7. Stuck goal check ==="
ros2 action list 2>&1 | grep -E "navigate_to_pose|follow_path|compute_path"
echo
echo "=== 8. bt_navigator state ==="
ros2 lifecycle get /bt_navigator 2>&1