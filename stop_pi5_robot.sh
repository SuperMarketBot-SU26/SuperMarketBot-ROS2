#!/usr/bin/env bash
# stop_pi5_robot.sh - Safe cleanup script for ROS 2 processes

echo "[stop_pi5_robot] 🧹 Cleaning any existing ROS 2 / Micro-ROS processes..."
pkill -9 -f "micro_ros_agent" 2>/dev/null || true
pkill -9 -f "ydlidar_ros2_driver" 2>/dev/null || true
pkill -9 -f "smb_robot.launch.py" 2>/dev/null || true
pkill -9 -f "smb.launch.py" 2>/dev/null || true
pkill -9 -f "unified_relay" 2>/dev/null || true
pkill -9 -f "supervisor" 2>/dev/null || true
pkill -9 -f "smb_mqtt_bridge" 2>/dev/null || true
pkill -9 -f "foxglove_bridge" 2>/dev/null || true
pkill -9 -f "rosbridge_server" 2>/dev/null || true
sleep 1
echo "[stop_pi5_robot] Cleanup completed cleanly."
