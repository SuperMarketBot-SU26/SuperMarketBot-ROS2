# smb_bridge

Translates between ESP32 firmware protocols and ROS2 topics.

## Role

- **Lidar bridge**: subscribes TCP socket reading WS82 JSON from ESP32-CAM → publishes `sensor_msgs/LaserScan` (or `smb_msgs/Scan1D`)
- **Cmd_vel bridge**: subscribes `/cmd_vel` → publishes WS81 JSON to ESP32-S3 over TCP
- **Status bridge**: subscribes WS84 (TBD) status JSON → publishes `sensor_msgs/BatteryState`, `sensor_msgs/Imu`

## Status

Skeleton only. Implementation begins in Phase 2.
