#!/bin/bash

# start_camera.sh
# This script starts the AI camera node natively on the Raspberry Pi OS.
# It should be run OUTSIDE of the Docker container.

# Source ROS 2 (assuming Humble is installed natively)
source /opt/ros/humble/setup.bash

# Source the workspace if it's built natively
if [ -f "/home/nhatkhoa1124/ros2_ws/install/setup.bash" ]; then
    source /home/nhatkhoa1124/ros2_ws/install/setup.bash
else
    echo "Warning: Native ROS 2 workspace not built yet. The smb_ai_camera package might not be found."
    echo "Please run 'colcon build --packages-select smb_ai_camera' natively."
fi

# Set ROS 2 Domain ID to match the Docker container (default is usually 0)
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}

# Run the camera node
echo "Starting AI Camera Node (IMX500) natively..."
ros2 run smb_ai_camera camera_node
