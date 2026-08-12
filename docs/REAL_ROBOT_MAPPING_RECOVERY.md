# Real robot mapping recovery

This runbook isolates odometry/TF/LiDAR faults before allowing Nav2 to move the
physical robot. Do not reuse a torn map to judge the corrected pipeline.

## Safety gate

- Keep one person beside the physical E-Stop.
- First bringup is stationary and uses `--no-nav2`.
- Do not publish `/cmd_vel`, a Nav2 goal, or an MQTT mission during the audit.
- Ensure only one robot container is running. Two EKF or SLAM instances can
  publish competing transforms and tear the map even when every parameter is
  individually correct.

## Build and stationary audit

Run the container with a stable name so a second SSH terminal can execute the
read-only diagnostic:

```bash
docker run -it --rm \
  --name supermarket-bot-ros2 \
  -v ~/ros2_ws:/ros2_ws \
  --network host --privileged \
  supermarket-bot-ros2:latest \
  bash -c "cd /ros2_ws && source /opt/ros/lyrical/setup.bash && ./start_pi5_robot.sh --build --no-nav2"
```

In a second terminal:

```bash
docker exec -it supermarket-bot-ros2 bash
cd /ros2_ws
source /opt/ros/lyrical/setup.bash
source install/setup.bash
bash ./diagnose_mapping.sh 10
```

Expected stationary results:

- `/scan`: about 6–10 Hz, frame `laser_frame`.
- `/odom`, `/odom_relay`, `/imu/data`, `/imu_relay`: about 50 Hz.
- `/odometry/filtered`: about 30 Hz.
- Message stamp absolute age below 0.5 s.
- Translation drift below 2 cm and yaw drift below 2 degrees in 10 s.
- Exactly one publisher for `/odom`, `/odom_relay`, and
  `/odometry/filtered`.
- TF `base_link <- laser_frame` and `odom <- base_link` present. `map <- odom`
  is present after SLAM activates.

## Verify LiDAR orientation while stationary

In RViz, set `Fixed Frame` to `base_link`, display only RobotModel and `/scan`,
and put one flat object about 1 m directly in front of the robot. The object
must appear on `base_link +X`. Test right and left as well.

The X3 driver profile keeps `reversion=false` and `inverted=false`. Correct a
physical mounting offset only in `base_link -> laser_frame`; never compensate
the same offset in both the driver and URDF.

## Calibrate wheel odometry before mapping

The current firmware assumes:

```text
ENC_PPR          = 960 pulses per wheel revolution
WHEEL_DIAM_M     = 0.065 m
WHEEL_BASE_M     = 0.22 m effective track width
ODOM_CALIB_FACTOR= 1.0
```

`ENC_PPR=960` is correct only when the 20-slot sensor is upstream of a 1:48
gearbox. If the FC-03 disc is on the wheel axle, it is 20, not 960. Confirm the
physical mounting before flashing a different value.

The encoder inputs are GPIO43/44. Firmware therefore requires **USB CDC On
Boot = Enabled** and carries micro-ROS on native USB (`/dev/ttyACM*`, physical
GPIO19/20). Never use `Serial0` while encoders remain on GPIO43/44; UART0 would
reuse those pins and serial traffic would corrupt encoder counts.

With a clear floor and E-Stop operator:

1. Drive exactly 1.00 m straight at low constant speed.
2. Read raw `/odom` displacement, not `/odometry/filtered` or `/map`.
3. Set `ODOM_CALIB_FACTOR *= actual_distance / reported_distance`.
4. Command one slow 360-degree rotation and compare raw `/odom` yaw.
5. Set `WHEEL_BASE_M *= reported_rotation / actual_rotation`.
6. Repeat until straight distance is within 3% and a full turn within 5%.

Also rotate the powered-but-stationary chassis 90 degrees counter-clockwise by
hand and verify `/imu_relay.angular_velocity.z` is positive. If it is negative,
set `IMU_YAW_INVERTED=1`, reflash, and repeat.

## Create a clean map

After the stationary and calibration checks pass, archive the torn map and
start a new mapping session. Move at 0.10–0.20 m/s, turn slowly, and revisit
distinctive areas for loop closure. Do not evaluate waypoint accuracy while
the base odometry checks are still failing.

For routine/production waypoint navigation, save the accepted map and launch a
localization pipeline (map server + AMCL or SLAM Toolbox localization mode)
instead of continuing online mapping. Mapping and production localization are
separate operating modes.
