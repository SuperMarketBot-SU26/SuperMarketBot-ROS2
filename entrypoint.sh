#!/bin/bash
set -e

# Source official ROS 2 distribution environment
if [ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]; then
    source "/opt/ros/$ROS_DISTRO/setup.bash"
fi

echo "[Docker Entrypoint] Compiling/verifying ROS 2 workspace packages natively..."
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF --packages-skip nav2_system_tests smb_sim || true

# Source local workspace build if available
if [ -f "/ros2_ws/install/setup.bash" ]; then
    source "/ros2_ws/install/setup.bash"
fi

echo "[Docker Entrypoint] Environment sourced successfully (ROS_DISTRO=$ROS_DISTRO, DOMAIN_ID=$ROS_DOMAIN_ID)."
exec "$@"
