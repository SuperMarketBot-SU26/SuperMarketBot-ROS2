#!/usr/bin/env bash
# deploy_and_run.sh — One-click sync and launch script for the Raspberry Pi 5.

# Default to snake@snake.local if no argument is provided
PI_HOST="${1:-snake@snake.local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================================="
echo "      🤖 DEPLOYING SUPERMARKETBOT TO PI 5 🤖                              "
echo "=========================================================================="
echo "Target: $PI_HOST"

echo -e "\n[1/2] Syncing workspace to Pi 5 (skipping heavy build artifacts)..."
rsync -avz --progress \
  --exclude='build/' \
  --exclude='install/' \
  --exclude='log/' \
  --exclude='.data/' \
  --exclude='.git/' \
  "${SCRIPT_DIR}/" "$PI_HOST:~/ros2_ws"

if [ $? -ne 0 ]; then
    echo "❌ Sync failed! Check your connection to $PI_HOST."
    exit 1
fi

echo -e "\n[2/2] Building and launching inside Docker container on Pi 5..."
echo "(Press Ctrl+C at any time to stop the robot and exit the SSH session)"
echo "--------------------------------------------------------------------------"

# SSH in, run docker exec with a fully configured command string
ssh -t "$PI_HOST" "docker exec -it smb_ros2_core bash -c \"\
  cd /ros2_ws && \
  echo '[deploy] Rebuilding smb_nodes...' && \
  colcon build --packages-select smb_nodes smb_robot_bringup && \
  source install/setup.bash && \
  export MQTT_HOST='3fa4fdf2e8444e6f84df0d24ce7fd301.s1.eu.hivemq.cloud' && \
  export MQTT_PORT='8883' && \
  export MQTT_USERNAME='supermarketbot' && \
  export MQTT_PASSWORD='SuperMarketBot2024!' && \
  export ROBOT_CODE='RB001' && \
  echo '[deploy] Launching robot with MQTT bridge enabled...' && \
  ./start_pi5_robot.sh --mqtt-bridge\""

echo "=========================================================================="
echo "Deployment session ended."
