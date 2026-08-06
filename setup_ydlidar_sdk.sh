#!/usr/bin/env bash
# setup_ydlidar_sdk.sh — Install YDLidar-SDK inside the Docker container.
# Run this ONCE inside the container before building the workspace:
#   docker exec -it smb_ros2_core bash -c '/ros2_ws/setup_ydlidar_sdk.sh'

set -e

echo "[setup] Installing YDLidar-SDK..."

# Check if already installed
if [ -f /usr/local/lib/libydlidar_sdk.a ] || [ -f /usr/local/lib/libydlidar_sdk.so ]; then
    echo "[setup] YDLidar-SDK already installed. Skipping."
    exit 0
fi

apt-get update && apt-get install -y --no-install-recommends pkg-config git python3-pip
python3 -m pip install cmake==3.28.4 --break-system-packages

TMP_DIR=$(mktemp -d)
cd "$TMP_DIR"
git clone https://github.com/YDLIDAR/YDLidar-SDK.git
cd YDLidar-SDK
mkdir build && cd build
/usr/local/bin/cmake ..
make -j$(nproc)
make install

# Cleanup
rm -rf "$TMP_DIR"
ldconfig

echo "[setup] YDLidar-SDK installed successfully."
