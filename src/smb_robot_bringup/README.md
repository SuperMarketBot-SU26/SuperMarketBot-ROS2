# smb_robot_bringup

Launch files, configs, and Gazebo worlds for SuperMarketBot (sim and real-robot modes).

## Contents

- `launch/`
  - `smb.launch.py` — top-level dispatcher. `mode:=sim` (default) or `mode:=robot`. Forwards all other args to the sub-launch.
  - `smb_sim.launch.py` — sim bringup: Gazebo Sim + ros_gz_bridge + URDF + SLAM Toolbox + RViz.
  - `smb_robot.launch.py` — real-robot bringup: URDF + joint_state_publisher + SLAM Toolbox + RViz. Assumes micro-ROS agent is already publishing `/scan`, `/odom`, `/imu/data`. Use `slam_params_file:=...` to override the SLAM config.
- `config/`
  - `common/smb.rviz` — RViz2 config (grid + map + laser scan + robot model). Fixed frame: `odom`.
  - `sim/`
    - `ros_gz_bridge.yaml` — Gazebo ↔ ROS2 topic mapping (sensor topics, cmd_vel, /tf, /clock). Sim-only.
    - `slam_toolbox.yaml` — SLAM Toolbox params for sim: `do_loop_closing: false` (Phase-1 sim room is near-symmetric; loop closure causes false-positive snaps). Per-step link matching tightened.
  - `robot/`
    - `slam_toolbox.yaml` — SLAM Toolbox params for real-robot: `do_loop_closing: true` (real environments are not symmetric; loop closure is needed to correct wheel-encoder drift). Upstream-style response thresholds.
- `worlds/`
  - `smb_world.sdf` — sim world: 10×10 m room, ground plane, walls, shelf obstacles, robot model with DiffDrive + lidar + IMU. World starts unpaused.

## How to run

Use the wrapper scripts at the repo root:

```bash
# Sim (Gazebo + SLAM + RViz)
./test_sim.sh             # windowed (Gazebo GUI + RViz)
./test_sim.sh true        # headless (Gazebo server only, no RViz)
./test_sim.sh --check     # verify launch-file syntax only

# Real robot (URDF + SLAM + RViz, requires micro-ROS agent + ESP32)
./test_robot.sh           # open RViz
./test_robot.sh false     # robot bringup only (no RViz)
./test_robot.sh --check   # verify deps + launch syntax only
SKIP_AGENT=true ./test_robot.sh   # run bringup without starting the agent

# Drive with keyboard (works against both modes)
./test_teleop.sh
```

Or run `ros2 launch` directly:

```bash
ros2 launch smb_robot_bringup smb.launch.py mode:=sim                  # windowed + RViz
ros2 launch smb_robot_bringup smb.launch.py mode:=sim headless:=true   # headless
ros2 launch smb_robot_bringup smb.launch.py mode:=robot                # real robot (uses config/robot/)
ros2 launch smb_robot_bringup smb.launch.py mode:=robot \
    slam_params_file:=/abs/path/to/custom_slam.yaml                    # override SLAM config
```

## Sim vs robot mode

| Aspect | Sim (`mode:=sim`) | Robot (`mode:=robot`) |
|---|---|---|
| Gazebo + ros_gz_bridge | started by `smb_sim.launch.py` | not started; ESP32 publishes topics directly |
| micro-ROS agent | not started | must already be running (`./test_robot.sh` starts it for you) |
| `use_sim_time` | `true` (default) | `false` (default) |
| SLAM config | `config/sim/slam_toolbox.yaml` | `config/robot/slam_toolbox.yaml` |
| RViz config | `config/common/smb.rviz` | `config/common/smb.rviz` |
| `joint_state_publisher` | not started (gz publishes joint states) | started (zero-pose fallback) |
| Topics | gz → bridge → ROS | ESP32 → micro-ROS agent → ROS |

Both modes share the same URDF (`smb_robot`), RViz config, topic names, and frame IDs — that's the contract defined in `../docs/TOPIC_CONTRACT.md`.

## Status

Phase 1 (sim end-to-end): done. Real-robot mode: ready, but requires a sourced-built `micro_ros_agent` (not in apt for lyrical) — see `ros2_ws.repos` and `../test_robot.sh --check`. See `../README.md` for the full pipeline status and topic contract.