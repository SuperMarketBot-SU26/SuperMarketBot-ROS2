# smb_robot_bringup

Launch files and configuration for SuperMarketBot (sim and real).

## Contents

- `launch/` — entrypoint launch files:
  - `sim_gz.launch.py` — Gazebo Harmonic + bridge + RViz
  - `sim_slam.launch.py` — sim + slam_toolbox online async
  - `sim_nav2.launch.py` — sim + slam_toolbox + Nav2
  - `real_robot.launch.py` — real robot bringup
- `params/` — Nav2 and slam_toolbox YAML configs
- `worlds/` — Gazebo SDF worlds (e.g., `visualize_lidar.sdf`)
- `config/` — RViz, ros_gz_bridge YAML

## Status

Skeleton only. Launch files are added in Phase 1 (sim) and Phase 3 (real).
