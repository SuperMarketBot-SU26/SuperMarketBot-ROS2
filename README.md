# SuperMarketBot-ROS2

ROS2 workspace for the SuperMarketBot project. Bridges ESP32 firmware (IOT side) to the ROS2 navigation stack.

## Relationship to other repos

This repo is the **ROS2 half** of the SuperMarketBot project. The other half is:

- [`SuperMarketBot-SU26/SuperMarketBot-IOT`](https://github.com/SuperMarketBot-SU26/SuperMarketBot-IOT) — ESP32-S3 firmware, ESP32-CAM firmware, and Android native hub.

The boundary between the two is the **JSON protocol** over TCP. The firmware publishes WS82/W81/W84 JSON strings; this repo's `smb_bridge` package converts them into ROS2 topics. Any change to the JSON format must be mirrored in both repos:

- [Firmware JSON contract docs](https://github.com/SuperMarketBot-SU26/SuperMarketBot-IOT/tree/main/ros2/protocol) (in the IOT repo)

## Workspace layout

```
ros2_ws/
├── src/
│   ├── smb_msgs/              # custom .msg definitions (Phase 1)
│   ├── smb_bridge/            # ESP32 ↔ ROS2 topic bridge (Phase 2)
│   ├── smb_robot/             # URDF + meshes (Phase 3)
│   ├── smb_robot_bringup/     # launch files, params, worlds (Phase 1)
│   ├── smb_nodes/             # higher-level nodes: safety, dock, FSM (Phase 3+)
│   └── slam_toolbox/          # upstream vendor — gitignored, re-cloned from ros2_ws.repos
├── build/ install/ log/       # colcon artifacts — gitignored
├── ros2_ws.repos              # vcstool manifest for re-cloning on other machines
└── .colcon_defaults           # default colcon flags
```

## Quickstart (fresh machine)

```bash
# 1. Clone this repo as a colcon workspace
mkdir -p ~/ros2_ws && cd ~/ros2_ws
git clone https://github.com/SuperMarketBot-SU26/SuperMarketBot-ROS2.git .

# 2. Pull upstream slam_toolbox (and any added packages) via vcstool
sudo apt install python3-vcstool
vcs import src < ros2_ws.repos

# 3. Install ROS2 dependencies
sudo apt install ros-${ROS_DISTRO}-nav2-bringup ros-${ROS_DISTRO}-slam-toolbox \
                 ros-${ROS_DISTRO}-robot-state-publisher ros-${ROS_DISTRO}-xacro \
                 ros-${ROS_DISTRO}-ros-gz ros-${ROS_DISTRO}-ros-gz-bridge

# 4. Build
source /opt/ros/${ROS_DISTRO}/setup.bash
colcon build --symlink-install

# 5. Run sim bringup
source install/setup.bash
ros2 launch smb_robot_bringup sim_slam.launch.py
```

## Build flags

`.colcon_defaults` sets:

- `--packages-skip slam_toolbox` — slam_toolbox is upstream vendor; we keep its source in the workspace tree but skip rebuilding it (use the apt package instead).
- `--cmake-args -DBUILD_TESTING=OFF` — bypass test builds in third-party packages.

## Phases

| Phase | Goal | Status |
|-------|------|--------|
| 0 | Install Nav2 + slam_toolbox + ros_gz via apt | pending |
| 1 | Sim bringup: Gazebo Harmonic + bridge + RViz + slam_toolbox | pending |
| 2 | `smb_bridge` node: WS82 → LaserScan, /cmd_vel → WS81 | pending |
| 3 | URDF + Nav2 param tuning + real robot bringup | pending |
| 4 | Auto-dock + state machine | pending |

## Conventions

- **Branch**: `main` only (single-developer project, no PRs required for solo work).
- **Commit style**: imperative mood, ≤72 chars on subject line, mention the package in subject.
- **PRs**: optional. Open against `main` from a feature branch if you want review.
- **License**: MIT (per package).
- **ROS2 distro**: currently targeting **Jazzy** (Ubuntu 24.04). See `ros2_ws.repos` for upstream versions.
