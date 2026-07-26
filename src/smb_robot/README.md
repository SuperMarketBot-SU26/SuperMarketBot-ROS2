# smb_robot

Robot description package for SuperMarketBot — the URDF consumed by `robot_state_publisher` in both sim (`smb_sim.launch.py`) and real-robot (`smb_robot.launch.py`) modes.

## Contents

- `urdf/` — Xacro files describing the physical robot (chassis + wheels + lidar mount + IMU mount). The single source of truth for sensor offsets (`laser_frame`, `imu_link`) used by both sim and real bringup.
- `package.xml` — exports the URDF directory via `<ament_index_python>` so other packages can find `urdf/smb.urdf.xacro` via `get_package_share_directory('smb_robot')`.

## Status

Phase 1: done. URDF dimensions match the SDF in `smb_robot_bringup/worlds/smb_world.sdf` (chassis 0.30×0.22×0.13 m, wheel radius 0.04 m, wheelbase 0.22 m, lidar height 0.075 m above `base_link`).
