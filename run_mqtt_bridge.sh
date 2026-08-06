#!/usr/bin/env bash
# run_mqtt_bridge.sh — Starts the SuperMarketBot with MQTT enabled.
# Run this script directly on the Pi 5 terminal (outside of Docker).

echo "=========================================================================="
echo "      🤖 STARTING SUPERMARKETBOT WITH MQTT 🤖                             "
echo "=========================================================================="

# Run the build and launch process inside the Docker container
docker exec -it smb_ros2_core bash -c "
  cd /ros2_ws

  echo '[build] Sourcing ROS 2 base environment...'
  source /opt/ros/lyrical/setup.bash

  echo '[build] Rebuilding smb_nodes and smb_robot_bringup...'
  colcon build --packages-select smb_nodes smb_robot_bringup
  
  if [ \$? -ne 0 ]; then
      echo '❌ Build failed!'
      exit 1
  fi

  echo '[build] Sourcing workspace...'
  source install/setup.bash

  echo '[config] Setting MQTT credentials...'
  export MQTT_HOST='3fa4fdf2e8444e6f84df0d24ce7fd301.s1.eu.hivemq.cloud'
  export MQTT_PORT='8883'
  export MQTT_USERNAME='supermarketbot'
  export MQTT_PASSWORD='SuperMarketBot2024!'
  export ROBOT_CODE='RB001'

  echo '[launch] Starting robot...'
  ./start_pi5_robot.sh --mqtt-bridge
"
