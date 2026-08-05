"""Unified QoS + timestamp relay for ESP32 → ROS2 data streams.

Why this exists
---------------
The ESP32 firmware publishes ``/scan``, ``/odom``, and ``/imu/data`` with
two problems that prevent SLAM / EKF from consuming them directly:

1. **QoS mismatch**: ESP32 publishes ``/scan`` with ``RELIABLE`` QoS;
   slam_toolbox subscribes with ``BEST_EFFORT``. DDS rejects the match.

2. **Timestamp mismatch**: ESP32 stamps all messages with ``millis()/1000``
   (seconds since boot, year 1970). Host-side nodes (slam_toolbox, EKF,
   Nav2) use wall-clock and reject messages ~50 years in the past.

The previous approach used two separate Python nodes (``scan_relay.py``
and ``odom_imu_relay.py``), each independently stamping with ``now()``.
This caused **timing skew**: scan and odom data captured simultaneously on
the ESP32 would arrive at SLAM with different host-side stamps (10-50ms
apart due to OS scheduling), making the scan-to-TF lookup extrapolate
instead of interpolate and causing progressive map drift.

This unified node solves the skew by:

- Subscribing to all three topics in a single process with a single clock
- Tracking the latest odom stamp and using it as the baseline for scan
  stamps (so SLAM always finds a valid TF at the scan's stamp)
- Optionally publishing odom → base_link TF directly (bypassing EKF for
  the simple single-source case)

Topic / QoS contract
--------------------
Subscribes:
  - ``/scan``      (RELIABLE / VOLATILE / depth=10)  → matches ESP32
  - ``/odom``      (RELIABLE / VOLATILE / depth=10)  → matches ESP32
  - ``/imu/data``  (RELIABLE / VOLATILE / depth=10)  → matches ESP32

Publishes:
  - ``/scan_relay``  (BEST_EFFORT / VOLATILE / depth=5)  → matches slam_toolbox
  - ``/odom_relay``  (RELIABLE / VOLATILE / depth=10)    → matches EKF
  - ``/imu_relay``   (RELIABLE / VOLATILE / depth=10)    → matches EKF
  - ``/tf``          (odom → base_link, if publish_tf=true)

All output stamps are rewritten to coordinated host-clock times.
"""

import math

import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Imu, LaserScan
from tf2_ros import TransformBroadcaster


class UnifiedRelay(Node):
    """Single-node relay for scan + odom + IMU with coordinated timestamps."""

    def __init__(self):
        super().__init__('unified_relay')

        # ---- Parameters ----
        self.declare_parameter('scan_in', '/scan')
        self.declare_parameter('scan_out', '/scan_relay')
        self.declare_parameter('odom_in', '/odom')
        self.declare_parameter('odom_out', '/odom_relay')
        self.declare_parameter('imu_in', '/imu/data')
        self.declare_parameter('imu_out', '/imu_relay')
        self.declare_parameter('publish_tf', False)
        self.declare_parameter('odom_frame', 'odom')
        self.declare_parameter('base_frame', 'base_link')

        scan_in = self.get_parameter('scan_in').value
        scan_out = self.get_parameter('scan_out').value
        odom_in = self.get_parameter('odom_in').value
        odom_out = self.get_parameter('odom_out').value
        imu_in = self.get_parameter('imu_in').value
        imu_out = self.get_parameter('imu_out').value
        self._publish_tf = self.get_parameter('publish_tf').value
        self._odom_frame = self.get_parameter('odom_frame').value
        self._base_frame = self.get_parameter('base_frame').value

        # ---- State: Clock synchronization ----
        # The ESP32 stamps messages with millis() since boot (1970).
        # We must shift these to ROS 2 wall-clock time. If we just use now(),
        # variable transmission latency (UDP/WiFi) breaks the relative timing
        # between odom and scan. By calculating a fixed offset (ROS_time - ESP32_time),
        # we preserve the exact relative timing generated on the microcontroller.
        self._time_offset_ns = None
        self._latest_odom_stamp_ns = None

        # ---- QoS profiles ----
        # Input: match ESP32 micro-ros-arduino defaults (RELIABLE for scan; BEST_EFFORT for odom/imu)
        qos_reliable_in = QoSProfile(
            depth=20,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
        )
        qos_best_effort_in = QoSProfile(
            depth=20,
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            durability=QoSDurabilityPolicy.VOLATILE,
        )
        # Scan output: match slam_toolbox's BEST_EFFORT subscriber; expand depth to 20 for dense scan queues
        qos_scan_out = QoSProfile(
            depth=20,
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            durability=QoSDurabilityPolicy.VOLATILE,
        )
        # Odom/IMU output: keep RELIABLE for EKF
        qos_reliable_out = QoSProfile(
            depth=20,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
        )

        # ---- Publishers ----
        self._scan_pub = self.create_publisher(LaserScan, scan_out, qos_scan_out)
        self._odom_pub = self.create_publisher(Odometry, odom_out, qos_reliable_out)
        self._imu_pub = self.create_publisher(Imu, imu_out, qos_reliable_out)

        # ---- Subscribers ----
        self._scan_sub = self.create_subscription(
            LaserScan, scan_in, self._on_scan, qos_reliable_in
        )
        self._odom_sub = self.create_subscription(
            Odometry, odom_in, self._on_odom, qos_reliable_in
        )
        self._imu_sub = self.create_subscription(
            Imu, imu_in, self._on_imu, qos_best_effort_in
        )

        # ---- Optional static odom → base_link broadcaster ----
        self._tf_broadcaster: Optional[TransformBroadcaster] = None
        if self._publish_tf:
            self._tf_broadcaster = TransformBroadcaster(self)

        self.get_logger().info(
            f'unified_relay started:\n'
            f'  scan:  {scan_in} (RELIABLE) → {scan_out} (BEST_EFFORT)\n'
            f'  odom:  {odom_in} → {odom_out}\n'
            f'  imu:   {imu_in} → {imu_out}\n'
            f'  publish_tf: {self._publish_tf}'
        )

    def _get_coordinated_stamp(self, esp32_stamp):
        """Convert ESP32 timestamp to host wall-clock time using an offset to preserve relative timing and eliminate UDP jitter."""
        esp32_ns = esp32_stamp.sec * 1000000000 + esp32_stamp.nanosec
        ros_ns = self.get_clock().now().nanoseconds
        # Re-sync offset if uninitialized or if drift/jitter exceeds 500ms
        if self._time_offset_ns is None or abs(ros_ns - (esp32_ns + self._time_offset_ns)) > 500000000:
            self._time_offset_ns = ros_ns - esp32_ns
        synced_ns = esp32_ns + self._time_offset_ns
        return rclpy.time.Time(nanoseconds=synced_ns).to_msg()

    def _on_odom(self, msg: Odometry) -> None:
        """Relay odom with synchronized host-clock stamp."""
        stamp = self._get_coordinated_stamp(msg.header.stamp)
        self._latest_odom_stamp_ns = stamp.sec * 1000000000 + stamp.nanosec
        msg.header.stamp = stamp
        self._odom_pub.publish(msg)

        # Optionally broadcast odom → base_link TF directly
        if self._tf_broadcaster is not None:
            t = TransformStamped()
            t.header.stamp = stamp
            t.header.frame_id = self._odom_frame
            t.child_frame_id = self._base_frame
            t.transform.translation.x = msg.pose.pose.position.x
            t.transform.translation.y = msg.pose.pose.position.y
            t.transform.translation.z = msg.pose.pose.position.z
            t.transform.rotation = msg.pose.pose.orientation
            self._tf_broadcaster.sendTransform(t)

    def _on_scan(self, msg: LaserScan) -> None:
        """Relay scan with synchronized host-clock stamp clamped to latest odom stamp."""
        stamp = self._get_coordinated_stamp(msg.header.stamp)
        scan_ns = stamp.sec * 1000000000 + stamp.nanosec
        # Clamp scan timestamp so it never exceeds the latest odom timestamp,
        # preventing SLAM Toolbox from dropping scans due to future TF extrapolation.
        if self._latest_odom_stamp_ns is not None and scan_ns > self._latest_odom_stamp_ns:
            scan_ns = self._latest_odom_stamp_ns
            stamp = rclpy.time.Time(nanoseconds=scan_ns).to_msg()
        msg.header.stamp = stamp
        self._scan_pub.publish(msg)

    def _on_imu(self, msg: Imu) -> None:
        """Relay IMU with synchronized host-clock stamp."""
        msg.header.stamp = self._get_coordinated_stamp(msg.header.stamp)
        self._imu_pub.publish(msg)


def main(args=None) -> int:
    rclpy.init(args=args)
    node = UnifiedRelay()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
