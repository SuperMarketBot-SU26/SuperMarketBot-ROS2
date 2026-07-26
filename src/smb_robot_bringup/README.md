# smb_robot_bringup

Launch files, configs, and Gazebo worlds for SuperMarketBot (sim and real-robot modes).

## Contents

- `launch/`
  - `smb.launch.py` — top-level dispatcher. `mode:=sim` (default) or `mode:=robot`. Forwards all other args to the sub-launch.
  - `smb_sim.launch.py` — sim bringup: Gazebo Sim + ros_gz_bridge + URDF + SLAM Toolbox + RViz.
  - `smb_robot.launch.py` — real-robot bringup: URDF + joint_state_publisher + SLAM Toolbox + RViz. Assumes micro-ROS agent is already publishing `/scan`, `/odom`, `/imu/data`.
- `config/`
  - `ros_gz_bridge.yaml` — Gazebo ↔ ROS2 topic mapping (sensor topics, cmd_vel, /tf, /clock).
  - `slam_toolbox.yaml` — SLAM Toolbox params (online_async, map → odom → base_link).
  - `smb.rviz` — RViz2 config (grid + map + laser scan + robot model). Fixed frame: `odom`.
- `worlds/`
  - `smb_world.sdf` — sim world: 10×10 m room, ground plane, walls, shelf obstacles, robot model with DiffDrive + lidar + IMU. World starts unpaused.

## How to run

Use the wrapper script at the repo root (`../test_sim.sh`):

```bash
./test_sim.sh             # windowed (Gazebo GUI + RViz)
./test_sim.sh true        # headless (Gazebo server only, no RViz)
./test_sim.sh --check     # verify launch-file syntax only
```

Or run ros2 launch directly:

```bash
ros2 launch smb_robot_bringup smb.launch.py mode:=sim                  # windowed + RViz
ros2 launch smb_robot_bringup smb.launch.py mode:=sim headless:=true   # headless
ros2 launch smb_robot_bringup smb.launch.py mode:=robot                # real robot
```

## Status

Phase 1 (sim end-to-end): done. See `../README.md` for the full pipeline status and topic contract.
