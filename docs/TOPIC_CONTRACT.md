# SuperMarketBot — Topic Contract

This document is the **single source of truth** for the topic/frame/message interface between the ESP32 firmware (in `SuperMarketBot-IOT/`) and the ROS2 stack (in this repo). Any change here must be mirrored on both sides and announced to the team.

---

## Why a contract?

You (`ros2_ws` maintainer) don't have the robot. Teammate (in `SuperMarketBot-IOT/`) does. The bridge between your work is **these topics** — identical names, types, frame IDs. As long as both sides honor this, sim code runs on real robot unchanged.

---

## Topics (canonical)

| Topic | Direction | Type | QoS | Rate | `frame_id` (header) | `child_frame_id` | Notes |
|---|---|---|---|---|---|---|---|
| `/scan` | firmware → ROS2 | `sensor_msgs/msg/LaserScan` | `BEST_EFFORT`, depth=10 | 10 Hz | `laser_frame` | — | YDLIDAR X3 (or sim equivalent). `range_min=0.12m`, `range_max=6.0m` for indoor supermarket. |
| `/odom` | firmware → ROS2 | `nav_msgs/msg/Odometry` | `RELIABLE` | 30 Hz | `odom` | `base_link` | From wheel encoders + IMU EKF fusion. Covariance: x/y 0.25 m², yaw 0.05 rad². |
| `/imu/data` | firmware → ROS2 | `sensor_msgs/msg/Imu` | `RELIABLE` | 30 Hz | `imu_link` | — | Orientation only (no accel). Orientation covariance: `[-1, -1, 0.05, -1, -1, -1]`. |
| `/cmd_vel` | ROS2 → firmware | `geometry_msgs/msg/Twist` | `RELIABLE` | 10–50 Hz | — | — | Units: `linear.x` = m/s, `angular.z` = rad/s. Output of `smb_nodes.supervisor`. |
| `/cmd_vel_nav` | Nav2 → supervisor | `geometry_msgs/msg/TwistStamped` | `RELIABLE` | 10–50 Hz | `child_frame_id` in header (unused) | — | Internal between Nav2 and the supervisor. Nav2 main/rolling publish `TwistStamped`; the supervisor normalizes incoming `TwistStamped` to a plain `Twist` before republishing on `/cmd_vel`. (Legacy publishers writing `Twist` to this topic would need a launch arg remap or a wrapper node — DDS does not allow two subscriptions on the same topic with different types.) |
| `/tf` | both | `tf2_msgs/msg/TFMessage` | — | various | — | — | Dynamic transforms. |
| `/tf_static` | ROS2 → ROS2 | `tf2_msgs/msg/TFMessage` | `TRANSIENT_LOCAL` | latched | — | — | `robot_state_publisher` publishes `base_link → laser_frame`, `base_link → imu_link`. |
| `/map` | ROS2 internal | `nav_msgs/msg/OccupancyGrid` | `TRANSIENT_LOCAL` | on change | `map` | — | From slam_toolbox. |
| `/amcl_pose` | ROS2 internal | `geometry_msgs/msg/PoseWithCovarianceStamped` | `RELIABLE` | on change | `map` | — | From slam_toolbox. Consumed by EKF. |
| `/odometry/filtered` | ROS2 internal | `nav_msgs/msg/Odometry` | `RELIABLE` | 30 Hz | `odom` | `base_link` | From `robot_localization` EKF. **Use this as odom source for navigation**, not raw `/odom`. |

---

## Frames (TF tree)

```
                    ┌──────────┐
                    │   map    │  ← slam_toolbox (origin = SLAM start pose)
                    └────┬─────┘
                         │  map → odom
                    ┌────▼─────┐
                    │   odom   │  ← diff_drive (sim) OR EKF (real + sim-with-EKF)
                    └────┬─────┘
                         │  odom → base_link
                    ┌────▼─────┐
                    │ base_link│  ← robot root, must be at wheel-center or chassis center
                    └────┬─────┘
              ┌──────────┼───────────┐
        ┌─────▼─────┐  ┌──▼────┐  ┌──▼────┐
        │ laser_frame│  │ imu_link │  │ wheels, caster
        └───────────┘  └─────────┘  └────────┘
```

**Frame IDs in messages are always one of the above.** Free-form strings like `vehicle_blue/chassis` are NOT allowed — they break EKF config and SLAM Toolbox params.

---

## Rules

1. **Naming**: stick to lowercase `snake_case` for topic and frame IDs.
2. **Stable IDs**: once published, a topic name or frame ID is part of the contract. Removing it requires a deprecation period (publish empty / log warning for ≥1 cycle).
3. **TF authority**:
   - `map → odom`: slam_toolbox (only).
   - `odom → base_link`: diff_drive in sim; EKF in real robot (also OK to use EKF in sim).
   - `base_link → *`: robot_state_publisher from URDF (single source — sim and real share same URDF).
4. **QoS** is part of the contract. Sensor topics are `BEST_EFFORT`; commands are `RELIABLE`.
5. **Coordinate convention**: REP-103 (`x` forward, `y` left, `z` up; right-handed). Heading increases counter-clockwise (z-axis positive).

---

## Sim ↔ real parity

What the **sim** MUST publish (via Gazebo sensors / ros_gz_bridge):

- `/scan` — Gazebo `gpu_lidar` sensor, 360 samples, vertical_samples=1 (2D), horizontal range ±π, range 0.08–10m, rate 10 Hz.
- `/odom` — Gazebo `gz::sim::systems::DiffDrive` plugin, frame `odom`, child `base_link`, rate 30 Hz.
- `/imu/data` — Gazebo `<sensor type='imu'>` (when added — see `20-sim-robot-roadmap.mdc` Phase 1).

What the **real ESP32** MUST publish (via `MicroRos.h`):

- `/scan` — populated from `g_x3Scan` (YDLIDAR X3 driver), `sensor_msgs/LaserScan`, frame `laser_frame`, range 0.12–8m (filtered to 0.15–6m on bridge side).
- `/odom` — populated from `g_pose` (encoder + IMU EKF), `nav_msgs/Odometry`, frame `odom`, child `base_link`, 30 Hz.
- `/imu/data` — derived from EKF heading + gyro Z, `sensor_msgs/Imu`, frame `imu_link`, 30 Hz.
- (subscribed) `/cmd_vel` → drives `botDrive(...)`.

What **both** subscribe to via the same launch:

- `/cmd_vel` (Nav2 publishes it).

---

## When changing the contract

1. Open PR / push branch in this repo with `docs/TOPIC_CONTRACT.md` updated.
2. Announce in team chat; link the diff.
3. Teammate updates ESP32 `MicroRos.h` to match.
4. Both rebuild, both verify with `ros2 topic info <topic> --verbose` that types + frame_ids match.

**Do not** rename a topic "temporarily" then rename back — every rename flashes the firmware (risky, slow).
