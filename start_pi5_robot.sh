#!/usr/bin/env bash
# start_pi5_robot.sh — Lightweight, bulletproof bringup script tailored specifically for Raspberry Pi 5 + Docker + USB Serial ESP32.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_DISTRO="${ROS_DISTRO:-lyrical}"
cd "${SCRIPT_DIR}"

# 1. Automatically source root ROS 2 environment FIRST so Python/colcon works without missing modules
if [ -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]; then
    source "/opt/ros/${ROS_DISTRO}/setup.bash"
else
    echo "[start_pi5_robot] ERROR: /opt/ros/${ROS_DISTRO}/setup.bash not found!"
    exit 1
fi

# 2. Parse arguments and check for --build request
DO_BUILD=false
# Mapping/recovery is the safe default on physical hardware. Nav2 must be
# enabled explicitly only after the odom/TF audit and a map are available.
USE_NAV2="false"
# Preflight is the default. Starting SLAM without odom -> base_link can never
# produce a map and only fills the LaserScan message-filter queue.
USE_SLAM="false"
USE_MQTT_BRIDGE="${USE_MQTT_BRIDGE:-false}"

for arg in "$@"; do
    if [ "$arg" == "--build" ] || [ "$arg" == "-b" ]; then
        DO_BUILD=true
    fi
    if [ "$arg" == "--no-nav2" ] || [ "$arg" == "--teleop" ]; then
        USE_NAV2="false"
        echo "[start_pi5_robot] Flag detected: Disabling Nav2 (Ideal for pure teleop driving)"
    fi
    if [ "$arg" == "--nav2" ]; then
        USE_NAV2="true"
        echo "[start_pi5_robot] Flag detected: Enabling Nav2"
    fi
    if [ "$arg" == "--no-slam" ]; then
        USE_SLAM="false"
        echo "[start_pi5_robot] Flag detected: Disabling SLAM"
    fi
    if [ "$arg" == "--slam" ] || [ "$arg" == "--mapping" ]; then
        USE_SLAM="true"
        echo "[start_pi5_robot] Flag detected: Enabling fresh SLAM mapping"
    fi
    if [ "$arg" == "--mqtt-bridge" ] || [ "$arg" == "--mqtt" ]; then
        USE_MQTT_BRIDGE="true"
        echo "[start_pi5_robot] Flag detected: Enabling MQTT navigation bridge"
    fi
done

# 3. Rebuild after a git pull/source edit. Sourcing an existing install tree
#    without rebuilding silently runs stale launch files and Python nodes.
BUILD_STAMP="${SCRIPT_DIR}/build/.smb_last_successful_build"
SOURCE_CHANGED=false
if [ ! -f "${BUILD_STAMP}" ]; then
    SOURCE_CHANGED=true
elif find "${SCRIPT_DIR}/src" -type f -newer "${BUILD_STAMP}" -print -quit | grep -q .; then
    SOURCE_CHANGED=true
fi

if [ "${DO_BUILD}" = true ] || [ ! -f "${SCRIPT_DIR}/install/setup.bash" ] || [ "${SOURCE_CHANGED}" = true ]; then
    # This workspace vendors the complete Navigation2 source tree, including
    # nav2_system_tests. Those tests depend on simulation-only packages such as
    # nav2_minimal_tb3_sim and must never gate real-robot startup. The Docker
    # image already provides/built the Nav2 runtime; only rebuild SMB production
    # packages and the directly connected LiDAR driver after a pull.
    SMB_BUILD_PACKAGES=(
        smb_msgs
        smb_robot
        smb_nodes
        smb_robot_bringup
        ydlidar_ros2_driver
        smb_ai_camera
    )
    echo "[start_pi5_robot] 📦 Building production packages: ${SMB_BUILD_PACKAGES[*]}"
    if ! colcon build --packages-select "${SMB_BUILD_PACKAGES[@]}"; then
        echo "[start_pi5_robot] ERROR: colcon build failed; refusing to launch a stale install tree."
        exit 1
    fi
    mkdir -p "$(dirname "${BUILD_STAMP}")"
    touch "${BUILD_STAMP}"
    echo "[start_pi5_robot] Build complete!"
fi

# Source local workspace build environment
if [ -f "${SCRIPT_DIR}/install/local_setup.bash" ]; then
    source "${SCRIPT_DIR}/install/local_setup.bash"
else
    echo "[start_pi5_robot] ERROR: install/setup.bash still not found after build!"
    exit 1
fi

# 4. Safe Cleanup of leftover processes from previous sessions
echo "[start_pi5_robot] 🧹 Cleaning any existing ROS 2 / Micro-ROS processes..."
pkill -9 -f "micro_ros_agent" 2>/dev/null || true
pkill -9 -f "ydlidar_ros2_driver" 2>/dev/null || true
pkill -9 -f "smb_robot.launch.py" 2>/dev/null || true
pkill -9 -f "smb.launch.py" 2>/dev/null || true
pkill -9 -f "unified_relay" 2>/dev/null || true
pkill -9 -f "odom_imu_relay" 2>/dev/null || true
pkill -9 -f "supervisor" 2>/dev/null || true
pkill -9 -f "smb_mqtt_bridge" 2>/dev/null || true
sleep 1
echo "[start_pi5_robot] Cleanup completed cleanly."

# 5. Auto-detect USB devices
#    - ESP32 shows up as /dev/ttyACM* (USB CDC native serial)
#    - YDLIDAR X3 shows up as /dev/ttyUSB* (USB-to-UART adapter, typically CH340/CP2102)
ESP32_PORT=""
for port in /dev/ttyACM0 /dev/ttyACM1; do
    if [ -e "$port" ]; then
        ESP32_PORT="$port"
        break
    fi
done

LIDAR_PORT=""
for port in /dev/ttyUSB0 /dev/ttyUSB1; do
    if [ -e "$port" ]; then
        LIDAR_PORT="$port"
        break
    fi
done

SERIAL_ARG=""
if [ -n "$ESP32_PORT" ]; then
    echo "[start_pi5_robot] 🚀 Auto-detected ESP32 connected to: $ESP32_PORT"
    SERIAL_ARG="serial_port:=$ESP32_PORT"
else
    echo "[start_pi5_robot] ⚠️ WARNING: No ESP32 (/dev/ttyACM*) found!"
    echo "                      Micro-ROS agent will boot with default setting, but waiting for hardware."
fi

LIDAR_ARG=""
if [ -n "$LIDAR_PORT" ]; then
    echo "[start_pi5_robot] 📡 Auto-detected YDLIDAR connected to: $LIDAR_PORT"
    LIDAR_ARG="lidar_port:=$LIDAR_PORT"
else
    echo "[start_pi5_robot] ⚠️ WARNING: No YDLIDAR (/dev/ttyUSB*) found!"
    echo "                      YDLIDAR driver will boot with default /dev/ttyUSB0."
fi

# 5b. MQTT Bridge credentials (from environment or .env file)
MQTT_HOST="${MQTT_HOST:-}"
MQTT_PORT="${MQTT_PORT:-8883}"
MQTT_USERNAME="${MQTT_USERNAME:-}"
MQTT_PASSWORD="${MQTT_PASSWORD:-}"
ROBOT_CODE="${ROBOT_CODE:-RB001}"

MQTT_ARGS=""
if [ "${USE_MQTT_BRIDGE}" = "true" ]; then
    MQTT_ARGS="use_mqtt_bridge:=true"
    if [ -n "$MQTT_HOST" ]; then
        MQTT_ARGS="${MQTT_ARGS} mqtt_host:=${MQTT_HOST} mqtt_port:=${MQTT_PORT}"
    fi
    if [ -n "$MQTT_USERNAME" ]; then
        MQTT_ARGS="${MQTT_ARGS} mqtt_username:=${MQTT_USERNAME} mqtt_password:=${MQTT_PASSWORD}"
    fi
    MQTT_ARGS="${MQTT_ARGS} robot_code:=${ROBOT_CODE}"
fi

# 6. Display launch summary
echo "=========================================================================="
echo "      🤖 SUPERMARKETBOT-ROS2 : PI 5 HARDWARE BRINGUP 🤖                   "
echo "=========================================================================="
echo "  Workspace   : ${SCRIPT_DIR}"
echo "  ESP32 Port  : ${ESP32_PORT:-None detected}"
echo "  LiDAR Port  : ${LIDAR_PORT:-/dev/ttyUSB0 (default)}"
echo "  RViz GUI    : disabled (headless Docker mode)"
echo "  SLAM Engine : ${USE_SLAM}"
echo "  Nav2 Stack  : ${USE_NAV2}"
echo "  MQTT Bridge : ${USE_MQTT_BRIDGE} (robot_code=${ROBOT_CODE})"
echo "=========================================================================="
echo "[start_pi5_robot] Launching engine in active terminal..."

# 7. Execute launch directly in foreground for maximum stability & zero background hanging
exec ros2 launch smb_robot_bringup smb.launch.py mode:=robot \
    rviz:=false \
    use_nav2:="${USE_NAV2}" \
    use_slam:="${USE_SLAM}" \
    serial_baud:=921600 \
    ${SERIAL_ARG} \
    ${LIDAR_ARG} \
    ${MQTT_ARGS}
