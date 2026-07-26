# smb_msgs

Custom ROS2 message and service definitions for SuperMarketBot.

## Planned messages

- `Scan1D.msg` — single-tuple 1D lidar scan (mirrors WS82 JSON format from ESP32-CAM)
- `CmdVelStamped.msg` — velocity command mirroring WS81 JSON format from ESP32-S3
- `RobotStatus.msg` — battery, IMU, wheel encoder state

## Status

Skeleton only. Messages are added in Phase 1 once the firmware protocol is locked.
