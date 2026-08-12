"""Read-only health check for the real robot localization/SLAM pipeline.

Keep the robot stationary while this node runs. It never publishes a velocity
or navigation goal; it only subscribes to sensor/odometry topics and inspects
the TF tree.
"""

import math
import statistics
import time

import rclpy
from nav_msgs.msg import Odometry
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import QoSProfile, qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import Imu, LaserScan
from tf2_ros import Buffer, TransformListener


def _yaw(quaternion):
    siny_cosp = 2.0 * (
        quaternion.w * quaternion.z + quaternion.x * quaternion.y)
    cosy_cosp = 1.0 - 2.0 * (
        quaternion.y * quaternion.y + quaternion.z * quaternion.z)
    return math.atan2(siny_cosp, cosy_cosp)


def _angle_delta(current, start):
    return math.atan2(math.sin(current - start), math.cos(current - start))


def _stamp_seconds(stamp):
    return float(stamp.sec) + float(stamp.nanosec) * 1e-9


class StreamStats:
    def __init__(self):
        self.count = 0
        self.first_rx = None
        self.last_rx = None
        self.ages = []
        self.frame_ids = set()

    def add(self, node, header):
        now_mono = time.monotonic()
        now_ros = node.get_clock().now().nanoseconds * 1e-9
        self.count += 1
        self.first_rx = self.first_rx or now_mono
        self.last_rx = now_mono
        self.ages.append(now_ros - _stamp_seconds(header.stamp))
        self.frame_ids.add(header.frame_id)

    @property
    def hz(self):
        if self.count < 2 or self.last_rx <= self.first_rx:
            return 0.0
        return (self.count - 1) / (self.last_rx - self.first_rx)


class MappingDiagnostics(Node):
    def __init__(self):
        super().__init__('mapping_diagnostics')
        self.declare_parameter('duration', 10.0)
        self._duration = max(3.0, float(self.get_parameter('duration').value))
        self.done = False

        self._stats = {
            '/scan': StreamStats(),
            '/odom': StreamStats(),
            '/odom_relay': StreamStats(),
            '/imu/data': StreamStats(),
            '/imu_relay': StreamStats(),
            '/odometry/filtered': StreamStats(),
        }
        self._odom_poses = {'/odom': [], '/odom_relay': [], '/odometry/filtered': []}
        self._gyro_z = []
        self._scan_valid_ratios = []

        reliable = QoSProfile(depth=50)
        self.create_subscription(
            LaserScan, '/scan', self._on_scan, qos_profile_sensor_data)
        self.create_subscription(
            Odometry, '/odom', lambda msg: self._on_odom('/odom', msg), reliable)
        self.create_subscription(
            Odometry, '/odom_relay',
            lambda msg: self._on_odom('/odom_relay', msg), reliable)
        self.create_subscription(
            Odometry, '/odometry/filtered',
            lambda msg: self._on_odom('/odometry/filtered', msg), reliable)
        self.create_subscription(
            Imu, '/imu/data', lambda msg: self._on_imu('/imu/data', msg),
            qos_profile_sensor_data)
        self.create_subscription(
            Imu, '/imu_relay', lambda msg: self._on_imu('/imu_relay', msg),
            reliable)

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._timer = self.create_timer(self._duration, self._finish)

        self.get_logger().info(
            f'Read-only mapping audit for {self._duration:.0f}s. '
            'Keep robot stationary; no motor commands will be sent.')

    def _on_scan(self, msg):
        self._stats['/scan'].add(self, msg.header)
        if msg.ranges:
            valid = sum(
                1 for value in msg.ranges
                if math.isfinite(value) and msg.range_min <= value <= msg.range_max)
            self._scan_valid_ratios.append(valid / len(msg.ranges))

    def _on_odom(self, topic, msg):
        self._stats[topic].add(self, msg.header)
        pose = msg.pose.pose
        self._odom_poses[topic].append(
            (pose.position.x, pose.position.y, _yaw(pose.orientation)))

    def _on_imu(self, topic, msg):
        self._stats[topic].add(self, msg.header)
        if topic == '/imu_relay' and math.isfinite(msg.angular_velocity.z):
            self._gyro_z.append(msg.angular_velocity.z)

    def _topic_publishers(self, topic):
        try:
            return len(self.get_publishers_info_by_topic(topic))
        except Exception:  # graph may change during shutdown
            return -1

    def _tf_status(self, target, source):
        try:
            transform = self._tf_buffer.lookup_transform(
                target, source, Time(), timeout=Duration(seconds=0.2))
            t = transform.transform.translation
            yaw = math.degrees(_yaw(transform.transform.rotation))
            return f'OK xyz=({t.x:+.3f},{t.y:+.3f},{t.z:+.3f}) yaw={yaw:+.1f}deg'
        # Catch the base exception for compatibility across ROS 2 distributions;
        # the tf2_ros exception export changed between releases.
        except Exception as exc:
            return f'MISSING ({exc})'

    def _finish(self):
        self._timer.cancel()
        print('\n=== SmartMarketBot mapping audit (robot stationary) ===')
        for topic, stats in self._stats.items():
            if stats.count == 0:
                print(f'[FAIL] {topic:<20} no messages '
                      f'(publishers={self._topic_publishers(topic)})')
                continue
            mean_age = statistics.fmean(stats.ages)
            max_abs_age = max(abs(value) for value in stats.ages)
            frames = ','.join(sorted(stats.frame_ids)) or '<empty>'
            timing_ok = max_abs_age <= 0.50
            state = ' OK ' if timing_ok else 'WARN'
            print(f'[{state}] {topic:<20} {stats.hz:6.1f} Hz  '
                  f'age(avg={mean_age:+.3f}s max|age|={max_abs_age:.3f}s)  '
                  f'frame={frames}  publishers={self._topic_publishers(topic)}')

        for topic, poses in self._odom_poses.items():
            if len(poses) < 2:
                continue
            x0, y0, yaw0 = poses[0]
            x1, y1, yaw1 = poses[-1]
            drift_cm = math.hypot(x1 - x0, y1 - y0) * 100.0
            drift_deg = abs(math.degrees(_angle_delta(yaw1, yaw0)))
            state = ' OK ' if drift_cm <= 2.0 and drift_deg <= 2.0 else 'WARN'
            print(f'[{state}] stationary drift {topic:<10} '
                  f'{drift_cm:.2f} cm, {drift_deg:.2f} deg')

        if self._gyro_z:
            gyro_mean = statistics.fmean(self._gyro_z)
            gyro_std = statistics.pstdev(self._gyro_z)
            state = ' OK ' if abs(gyro_mean) <= 0.02 and gyro_std <= 0.03 else 'WARN'
            print(f'[{state}] IMU gyro_z mean={gyro_mean:+.4f} rad/s '
                  f'std={gyro_std:.4f} rad/s')

        if self._scan_valid_ratios:
            valid_pct = statistics.fmean(self._scan_valid_ratios) * 100.0
            state = ' OK ' if valid_pct >= 20.0 else 'WARN'
            print(f'[{state}] LiDAR valid samples={valid_pct:.1f}%')

        print(f'[ TF ] base_link <- laser_frame : '
              f'{self._tf_status("base_link", "laser_frame")}')
        print(f'[ TF ] odom <- base_link        : '
              f'{self._tf_status("odom", "base_link")}')
        print(f'[ TF ] map <- odom              : '
              f'{self._tf_status("map", "odom")}')
        print('=== End audit; no cmd_vel or goal was published ===\n')
        self.done = True


def main(args=None):
    rclpy.init(args=args)
    node = MappingDiagnostics()
    try:
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
