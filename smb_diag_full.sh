#!/usr/bin/env bash
# smb_diag_full.sh — clean boot with Nav2, wait for /map, send goal; observe the FULL chain.
set +u
source /opt/ros/lyrical/setup.bash
source /home/nhatkhoa1124/ros2_ws/install/setup.bash
set -u

# Step 1: launch
ros2 launch smb_robot_bringup smb.launch.py mode:=sim headless:=true rviz:=false use_nav2:=true 2>&1 &
LAUNCH_PID=$!
echo "Launch PID: $LAUNCH_PID"
sleep 18  # give SLAM 15s to publish first /map

echo
echo "=== after 18s: is /map alive? ==="
ros2 topic hz /map --window 30 2>&1 &
HZ_PID=$!
sleep 4
kill $HZ_PID 2>/dev/null
wait $HZ_PID 2>/dev/null

echo
echo "=== sample /plan while we send goal to 2,0 ==="
timeout 4 ros2 topic echo /plan --once 2>&1
echo
echo "=== bt_navigator lifecycle ==="
ros2 lifecycle get /bt_navigator 2>&1
echo
echo "=== local_costmap footprint publication? ==="
timeout 3 ros2 topic echo /local_costmap/published_footprint --once 2>&1 | head -3

echo
echo "=== STOP: send the user a goal now manually ==="
echo "=== To send a goal, in a SEPARATE terminal run: ==="
echo "ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose --feedback \\"
echo "  \"{pose: {header: {frame_id: 'map'}, pose: {position: {x: 2.0, y: 0.0, z: 0.0}, orientation: {w: 1.0}}}}\""
echo
echo "=== sample /cmd_vel_nav for 5s after you send goal ==="
timeout 8 ros2 topic hz /cmd_vel_nav 2>&1 | head -8
echo
echo "=== finished. killing launch ==="
kill -INT $LAUNCH_PID 2>/dev/null
wait $LAUNCH_PID 2>/dev/null
echo "done"