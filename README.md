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
│   │   ├── config/
│   │   │   ├── common/smb.rviz       # shared RViz config
│   │   │   ├── sim/                  # sim-only configs
│   │   │   │   ├── ros_gz_bridge.yaml
│   │   │   │   └── slam_toolbox.yaml # loop closing disabled (symmetric room)
│   │   │   └── robot/                # real-robot configs
│   │   │       └── slam_toolbox.yaml # loop closing enabled
│   │   ├── launch/
│   │   └── worlds/smb_world.sdf
│   ├── smb_nodes/             # higher-level nodes: safety, dock, FSM (Phase 4)
│   ├── slam_toolbox/          # upstream vendor — re-cloned from ros2_ws.repos
│   └── micro_ros_agent/       # upstream vendor — re-cloned from ros2_ws.repos
├── docs/
│   └── TOPIC_CONTRACT.md      # firmware ↔ ROS2 interface spec (READ FIRST)
├── scripts/                   # bringup, test, diagnostic, and deployment scripts
│   ├── start_pi5_robot.sh     # real-robot hardware bringup (Pi 5 + Docker)
│   ├── diagnose_mapping.sh    # non-intrusive 10s pre-flight audit
│   ├── test_sim.sh            # sim wrapper: launches Gazebo + SLAM + RViz
│   ├── test_robot.sh          # host bringup wrapper: micro-ROS agent + SLAM + RViz
│   ├── test_teleop.sh         # keyboard driver for /cmd_vel
│   ├── test_calibration.sh    # wheel encoder calibration wizard
│   ├── test_odom_drift.sh     # real-time odometry drift monitor
│   ├── test_nav2_goal.sh      # CLI action goal sender
│   └── ...
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

# 5a. Run sim bringup (Phase 1+ — verified working)
source install/setup.bash
./scripts/test_sim.sh             # windowed (Gazebo GUI + RViz)
./scripts/test_sim.sh true        # headless (Gazebo server only, no RViz)

# 5b. Run real-robot bringup (requires ESP32 flashed with MicroRos.h)
./scripts/test_robot.sh           # starts micro-ROS agent + robot bringup + RViz
./scripts/test_robot.sh --check   # verify deps + launch syntax first
```

> **Note on `micro_ros_agent`:** ROS2 Lyrical does **not** ship `ros-lyrical-micro-ros-agent` in apt. `ros2_ws.repos` vendors it from `micro-ROS/micro-ROS-Agent` (rolling branch). On a fresh machine, after step 2 (`vcs import src < ros2_ws.repos`), the agent source lives at `src/micro_ros_agent/` and is built with `colcon build --packages-select micro_ros_agent`. `test_robot.sh --check` verifies the binary exists.

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

Topic contract enforced via `src/smb_robot_bringup/config/sim/ros_gz_bridge.yaml`:

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

### Nav2 vendoring notes (lyrical build patches)

Nav2 (monorepo `ros-planning/navigation2` branch `main`) is built from source under `src/nav2_repo/`. Three patches are required for it to compile on Ubuntu 26.04 / GCC 15 / ROS2 lyrical:

1. **`src/nav2_repo/nav2_common/cmake/nav2_package.cmake`** — drop `-Werror` from the default compile flags. GCC 15 treats `BT::Any::tryCast()`'s `expected_lite` destructor as `free-nonheap-object` (a false positive in templated headers); the warning floods Nav2's plugin condition sources and breaks the build.
2. **`src/nav2_repo/nav2_behavior_tree/include/nav2_behavior_tree/utils/loop_rate.hpp`** — `BT::Tree::emitWakeUpSignal()` returns `void` in lyrical's `behaviortree_cpp` 4.x, not a waitable connection object as upstream Nav2 assumed. Replaced the wake-signal-based sleep with simple polling (optimization, not correctness).
3. **`src/nav2_repo/nav2_bringup/{CMakeLists.txt,package.xml}`** — drop the `find_package(navigation2 REQUIRED)` / `build_depend>navigation2</build_depend>`. `navigation2` is a metapackage whose `<exec_depend>` includes `nav2_smac_planner` / `nav2_mppi_controller` (OMPL/MPI deps, not in apt for lyrical). We don't need the metapackage at runtime — explicit per-package exec_depends on what we actually use are listed in the package.xml.
4. **`src/nav2_repo/nav2_bringup/launch/navigation_launch.py`** — remove the `ComposableNode` and standalone `Node` entries for `smoother_server`, `velocity_smoother`, `collision_monitor`, `route_server`, `docking_server`, `following_server` (none of those packages are built on lyrical). Update `lifecycle_nodes` list to match the components we actually load (without this, the lifecycle manager blocks forever waiting for services that don't exist).
5. **`src/smb_robot_bringup/params/nav2_params.yaml`** — DWBLocalPlanner (our controller choice) needs an explicit `critics` list since Nav2 1.1+. Without it, `controller_server` configure callback throws "Parameter FollowPath.critics not in overrides" and lifecycle aborts. We use the subset of critics available in `dwb_critics`: `["RotateToGoal", "Oscillation", "BaseObstacle", "GoalDist", "PathAlign", "PathDist"]` (note the spelling — `GoalDist`, not `GoalDistance`).
6. **`src/smb_robot_bringup/worlds/smb_world.sdf`** — DiffDrive plugin must declare `<max_linear_acceleration>`, `<min_linear_acceleration>`, `<max_angular_acceleration>`, `<min_angular_acceleration>`, `<max_linear_velocity>`, `<min_linear_velocity>`, `<max_angular_velocity>`, `<min_angular_velocity>`. Without these, the plugin loads and subscribes to cmd_vel but never drives the wheels or publishes `/model/smb/odometry` and `/model/smb/tf`. The reference example at `/opt/ros/lyrical/opt/gz_sim_vendor/share/gz/gz-sim/worlds/diff_drive.sdf` shows the canonical values.
7. **`src/smb_robot_bringup/launch/smb_sim.launch.py`** — the `gz sim` command must include `-r` (run / start immediately). Without `-r`, gz sim defaults to PAUSED and DiffDrive's tick callback never fires — no `/cmd_vel`, `/odom`, `/tf`, or joint-state messages publish from gz even though `gz topic -l` advertises the topics (those are just ros_gz_bridge's subscriptions). This is the silent-no-odom issue we hit on Phase 3: the topic was declared, the bridge was wired, but no publishers on the gz side ever ticked. Symptom: `ros2 topic info /odom` shows 1 publisher (the bridge), but `gz topic -e -t /model/smb/odometry` returns empty. Fix: pass `-r` to `gz sim` in both headless (`-s -r --headless-rendering`) and windowed (`-r`) branches.

Additional packages we install (transitively required for our subset):

- `nav_2d_utils`, `costmap_queue`, `dwb_critics`, `dwb_plugins` — pulled in by `dwb_core` / `nav2_dwb_controller`.

Packages **skipped** (depend on OMPL or MPI, not in `ros-lyrical-ompl`):

- `nav2_smac_planner`, `nav2_mppi_controller`, `nav2_smoother`, `nav2_theta_star_planner`,
  `nav2_velocity_smoother`, `nav2_collision_monitor`, `nav2_constrained_smoother`,
  `nav2_graceful_controller`, `nav2_loopback_sim`, `nav2_rviz_plugins`,
  `nav2_route`, `opennav_docking*`, `opennav_following`, `navigation2` (metapkg).

The `--packages-skip` flags in our build commands below reflect this.

Our planner choice: `nav2_navfn_planner` (NavfnPlanner) — no extra deps.
Our controller choice: `nav2_dwb_controller` (DWBLocalPlanner) — no extra deps.

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
| 1 | Sim end-to-end: adapted SDF + URDF + smb_sim.launch.py + smb_robot.launch.py | done |
| 2 | Port ekf_config.yaml + mapper_params from IOT repo; add EKF to launch | pending |
| 3 | Nav2 + waypoint navigation in sim | done (verified `follow_waypoints` action runs end-to-end) |
| 4 | `smb_nodes` FSM (idle / nav / dock / estop) | pending |
