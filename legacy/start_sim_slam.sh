#!/bin/bash

source /opt/ros/$ROS_DISTRO/setup.bash
source ~/ros2_ws/install/setup.bash

echo "🚀 Starting Teleop + SLAM..."

cleanup() {
  echo ""
  echo "🛑 Stopping all nodes..."
  kill $(jobs -p) 2>/dev/null
  pkill -9 -f parameter_bridge 2>/dev/null
  pkill -9 -f static_transform_publisher 2>/dev/null
  sleep 1
  exit
}
trap cleanup SIGINT SIGTERM EXIT

# 0. Sanity check: warn if a stale bridge/gz process is already running
if pgrep -f parameter_bridge > /dev/null; then
  echo "⚠️  A parameter_bridge process is already running from a previous session."
  echo "    Run: pkill -9 -f parameter_bridge   then try again."
  exit 1
fi

# 1. Bridge clock, cmd_vel, tf, odometry, and lidar2 as a LaserScan (for SLAM)
ros2 run ros_gz_bridge parameter_bridge \
  /clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock \
  /model/vehicle_blue/cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist \
  /lidar2@sensor_msgs/msg/LaserScan@gz.msgs.LaserScan \
  /model/vehicle_blue/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry \
  /model/vehicle_blue/tf@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V \
  --ros-args \
  -r /model/vehicle_blue/tf:=/tf \
  -r /model/vehicle_blue/odometry:=/odom \
  -p use_sim_time:=true &
sleep 3

# 2. Static transform: chassis -> lidar_link/gpu_lidar
#    (matches the LaserScan/PointCloud2 header.frame_id, confirmed via:
#     ros2 topic echo /lidar2 --field header.frame_id --once)
ros2 run tf2_ros static_transform_publisher \
  --x 0 --y 0 --z 0.5 \
  --roll 0 --pitch 0 --yaw 0 \
  --frame-id vehicle_blue/chassis \
  --child-frame-id vehicle_blue/lidar_link/gpu_lidar \
  --ros-args -p use_sim_time:=true &
sleep 1

# 3. Teleop keyboard in its own xterm window
xterm -T "Teleop Keyboard" -e "ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/model/vehicle_blue/cmd_vel" &
sleep 1

# 4. SLAM Toolbox
ros2 launch slam_toolbox online_async_launch.py \
  slam_params_file:=/home/nhatkhoa1124/ros2_ws/slam_params.yaml \
  use_sim_time:=True &
sleep 5

# 5. RViz2
ros2 run rviz2 rviz2 --ros-args -p use_sim_time:=true &

echo "✅ Teleop + SLAM running!"
echo "   Click into the xterm window to send teleop keys and drive the robot."
echo "   In RViz:"
echo "     - Fixed Frame -> map"
echo "     - Add -> By topic -> /map -> Map"
echo "     - Add -> By topic -> /lidar2 -> LaserScan (optional, to see raw scan)"
echo "   Drive the robot around to build up the map."
wait