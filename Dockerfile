# Default ROS 2 distribution (targeting ROS 2 Lyrical Lyrebird for 2026 LTS compatibility)
ARG ROS_DISTRO=lyrical
FROM ros:${ROS_DISTRO}-ros-base

# Disable interactive prompts during apt installations
ENV DEBIAN_FRONTEND=noninteractive
ENV ROS_DOMAIN_ID=0
ENV RCUTILS_CONSOLE_OUTPUT_FORMAT="[{severity}] [{time}]: {message}"

# Install core build dependencies, python utilities, planning libraries, and networking tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-pip \
    python3-colcon-common-extensions \
    python3-rosdep \
    libompl-dev \
    libboost-all-dev \
    libasio-dev \
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    ros-${ROS_DISTRO}-robot-state-publisher \
    ros-${ROS_DISTRO}-tf2-ros \
    ros-${ROS_DISTRO}-tf2-tools \
    net-tools \
    iproute2 \
    usbutils \
    && rm -rf /var/lib/apt/lists/*

# Install YDLidar-SDK (requires older CMake due to ancient CMakeLists.txt)
RUN apt-get update && apt-get install -y --no-install-recommends pkg-config git python3-pip \
    && python3 -m pip install cmake==3.28.4 --break-system-packages \
    && git clone https://github.com/YDLIDAR/YDLidar-SDK.git /tmp/YDLidar-SDK \
    && cd /tmp/YDLidar-SDK && mkdir build && cd build \
    && /usr/local/bin/cmake .. && make -j$(nproc) && make install \
    && rm -rf /tmp/YDLidar-SDK \
    && ldconfig \
    && rm -rf /var/lib/apt/lists/*

# Set CycloneDDS as default middleware for dependable Wi-Fi and container networking
ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# Create workspace directory inside container
WORKDIR /ros2_ws

# Copy ONLY src directory first to maximize Docker layer caching
COPY src/ ./src/
COPY entrypoint.sh /entrypoint.sh

# Fix script permissions
RUN chmod +x /entrypoint.sh

# Resolve and install any ROS 2 package dependencies from source manifests (excluding heavy desktop simulation engines)
RUN apt-get update && \
    rosdep init || true && \
    rosdep update && \
    rosdep install --from-paths src --ignore-src -r -y \
      --skip-keys="nav2_minimal_tb3_sim gz_ros2_control gz_ros2_control_demos ros_gz_sim ros_gz_bridge ros_gz_interfaces ignition-gazebo6 ignition-sensors6 gazebo_ros gazebo_ros_pkgs" \
      --rosdistro ${ROS_DISTRO} || true && \
    rm -rf /var/lib/apt/lists/*

# Auto-source environments in terminal shells
RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /root/.bashrc && \
    echo "source /ros2_ws/install/setup.bash" >> /root/.bashrc

ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "launch", "smb_robot_bringup", "smb_robot.launch.py", "use_nav2:=true", "use_rviz:=false"]
