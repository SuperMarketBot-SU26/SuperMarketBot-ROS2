# SuperMarketBot-ROS2

ROS2 workspace for the SuperMarketBot project. Bridges ESP32 firmware (IOT side) to the ROS2 navigation stack.

## Environment

- **OS:** Ubuntu 26.04 "Resolute Raccoon"
- **Distro:** ROS 2 "lyrical" (new; many packages must be built from source — see `ros2_ws.repos`)
- **Simulator:** Gazebo Sim (ros_gz bridge, `gz` CLI)

## Relationship to other repos

This repo is the **ROS2 half** of the SuperMarketBot project. The other half is:

- [`SuperMarketBot-SU26/SuperMarketBot-IOT`](https://github.com/SuperMarketBot-SU26/SuperMarketBot-IOT) — ESP32-S3 firmware, ESP32-CAM firmware, Android native hub.

The boundary between the two is the **ROS2 topic contract** in [`docs/TOPIC_CONTRACT.md`](docs/TOPIC_CONTRACT.md). Both sides publish/subscribe to the same topics (`/scan`, `/odom`, `/imu/data`, `/cmd_vel`) with the same frame IDs (`base_link`, `laser_frame`, `imu_link`, `odom`, `map`). Topic/frame ID changes require updating the contract and notifying the teammate.

## AI assistant rules

This repo has project-specific `.cursor/rules/` for AI assistants (mirroring the structure of `SuperMarketBot-BE/.cursor/rules/`):

- `00-unified-ai-behavior.mdc` — universal AI behavior rules
- `00-karpathy-workflow.mdc` — 6-step workflow
- `10-ros2-ament-layout.mdc` — package structure and ownership
- `20-sim-robot-roadmap.mdc` — phased plan; **role split: this repo = ROS2 only**
- `30-ros2-guidelines.mdc` — launch, params, TF tree, lyrical/Ubuntu 26 caveats

Read `.cursor/rules/` before starting work. Topic/frame IDs are part of the contract — do NOT change them without updating `docs/TOPIC_CONTRACT.md` AND notifying the teammate.

## Workspace layout

```
ros2_ws/
├── src/
│   ├── smb_msgs/              # custom .msg definitions (Phase 1)
│   ├── smb_bridge/            # ESP32 ↔ ROS2 topic bridge (Phase 3)
│   ├── smb_robot/             # URDF + meshes (Phase 1)
│   ├── smb_robot_bringup/     # launch files, params, worlds (Phase 1)
│   ├── smb_nodes/             # higher-level nodes: safety, dock, FSM (Phase 4)
│   └── slam_toolbox/          # upstream vendor — gitignored, re-cloned from ros2_ws.repos
├── docs/
│   └── TOPIC_CONTRACT.md      # firmware ↔ ROS2 interface spec (READ FIRST)
├── .cursor/rules/             # AI assistant rules (mirror of BE repo)
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

# 3. Install ROS2 dependencies (verify availability first — see "Lyrical caveat" below)
#    ros-lyrical-{nav2-bringup, robot-state-publisher, xacro} are usually available.
#    ros-lyrical-slam-toolbox may not be — build from source via ros2_ws.repos.
sudo apt install ros-${ROS_DISTRO}-nav2-bringup ros-${ROS_DISTRO}-robot-state-publisher \
                 ros-${ROS_DISTRO}-xacro ros-${ROS_DISTRO}-ros-gz ros-${ROS_DISTRO}-ros-gz-bridge

# 4. Build (parallel-workers 2 to avoid OOM on Ubuntu 26)
source /opt/ros/${ROS_DISTRO:-lyrical}/setup.bash
colcon build --parallel-workers 2

# 5. Run sim bringup (Phase 1+ — verified working)
source install/setup.bash

# Windowed Gazebo (default; needs display):
ros2 launch smb_robot_bringup smb.launch.py mode:=sim

# Headless (CI/server use):
ros2 launch smb_robot_bringup smb.launch.py mode:=sim headless:=true rviz:=false

# Custom world, no RViz:
ros2 launch smb_robot_bringup smb_sim.launch.py world:=smb_world.sdf rviz:=false

# Verify topics:
ros2 topic list | grep -E "/scan|/odom|/imu/data|/cmd_vel|/tf|/map"
# Expected: /scan (LaserScan), /odom (Odometry), /imu/data (Imu),
#           /cmd_vel (Twist), /tf + /tf_static (TFMessage), /map (OccupancyGrid)
```

### Current verified pipeline (Phase 1 done)

The following launches cleanly and produces all expected topics:

- `smb_sim.launch.py` — Gazebo Sim + ros_gz_bridge + URDF + SLAM Toolbox + RViz2
- `smb_robot.launch.py` — same minus Gazebo (assumes micro-ROS agent feeding /scan, /odom, /imu/data)
- `smb.launch.py mode:=sim|robot` — dispatcher

Physical constants (URDF + SDF matched):
- Chassis: 0.30 m × 0.22 m × 0.13 m
- Wheel radius: 0.04 m, wheelbase (track): 0.22 m
- LiDAR: 360 samples, range 0.08–10 m (sim); publish on `/lidar` → `/scan`
- IMU: 100 Hz (sim); publish on `/imu` → `/imu/data`

Topic contract enforced via `config/ros_gz_bridge.yaml`:

| Topic | Type | frame_id |
|---|---|---|
| `/scan` | sensor_msgs/LaserScan | `laser_frame` |
| `/odom` | nav_msgs/Odometry | `odom` (child: `base_link`) |
| `/imu/data` | sensor_msgs/Imu | `imu_link` |
| `/cmd_vel` | geometry_msgs/Twist | — |
| `/tf` | tf2_msgs/TFMessage | — |

See `docs/TOPIC_CONTRACT.md` for the full spec.

### Lyrical caveat (Ubuntu 26.04)

ROS2 "lyrical" is a **new distro** — not all packages are in apt yet. Before running `apt install ros-lyrical-X`:

```bash
apt-cache search ros-lyrical-X
```

If empty, find the source on GitHub (often branch `rolling`, `main`, or latest release tag), clone into `src/`, and add the entry to `ros2_ws.repos` so teammates can reproduce the build.

## Build flags

`.colcon_defaults` sets:

- `--packages-skip slam_toolbox` — slam_toolbox is upstream vendor; we keep its source in the workspace tree but skip rebuilding it by default (use `colcon build --packages-select slam_toolbox` to rebuild after `git pull`).
- `--cmake-args -DBUILD_TESTING=OFF` — bypass test builds in third-party packages.

## Phases

See `.cursor/rules/20-sim-robot-roadmap.mdc` for the active plan. Summary:

| Phase | Goal | Status |
|-------|------|--------|
| 0 | Repo init (packages, .gitignore, README) | done |
| 0.5 | AI rules + topic contract | done |
| 1 | Sim end-to-end: adapted SDF + URDF + smb_sim.launch.py + smb_robot.launch.py | pending |
| 2 | Port ekf_config.yaml + mapper_params from IOT repo; add EKF to launch | pending |
| 3 | `smb_bridge` decide: WS JSON vs micro-ROS (with teammate) | pending |
| 4 | `smb_nodes` FSM (idle / nav / dock / estop) | pending |
