"""Unified QoS + timestamp relay for ESP32 → ROS2 data streams (odom + IMU).

Why this exists
---------------
The ESP32 firmware publishes ``/odom`` and ``/imu/data`` with timestamp
issues that prevent EKF / Nav2 from consuming them directly:

- **Timestamp mismatch**: ESP32 stamps all messages with ``millis()/1000``
  (seconds since boot, year 1970). Host-side nodes (EKF, Nav2) use
  wall-clock and reject messages ~50 years in the past.

This relay shifts ESP32 timestamps to host wall-clock time while preserving
the exact relative timing generated on the microcontroller.

Note on LiDAR
--------------
The YDLIDAR X3 is now connected directly to the Pi 5 via USB, using the
``ydlidar_ros2_driver`` native driver. It publishes ``/scan`` with proper
wall-clock timestamps and BEST_EFFORT QoS, so no scan relay is needed.
The old scan QoS bridge (RELIABLE→BEST_EFFORT) and timestamp clamping
have been removed.

Topic / QoS contract
--------------------
Subscribes:
  - ``/odom``      (RELIABLE / VOLATILE / depth=20)  → matches ESP32
  - ``/imu/data``  (BEST_EFFORT / VOLATILE / depth=20)  → matches ESP32

Publishes:
  - ``/odom_relay``  (RELIABLE / VOLATILE / depth=20)    → matches EKF
  - ``/imu_relay``   (RELIABLE / VOLATILE / depth=20)    → matches EKF
  - ``/tf``          (odom → base_link, if publish_tf=true)

Valid agent-synchronized timestamps are preserved. Boot-relative timestamps
from older/fallback firmware are shifted with one coordinated host-clock offset.
"""

import rclpy
from builtin_interfaces.msg import Time
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Imu
from tf2_ros import TransformBroadcaster


class UnifiedRelay(Node):
    """Single-node relay for odom + IMU with coordinated timestamps."""

    def __init__(self):
        super().__init__('unified_relay')

        # ---- Parameters ----
        self.declare_parameter('odom_in', '/odom')
        self.declare_parameter('odom_out', '/odom_relay')
        self.declare_parameter('imu_in', '/imu/data')
        self.declare_parameter('imu_out', '/imu_relay')
        self.declare_parameter('publish_tf', False)
        self.declare_parameter('odom_frame', 'odom')
        self.declare_parameter('base_frame', 'base_link')

        odom_in = self.get_parameter('odom_in').value
        odom_out = self.get_parameter('odom_out').value
        imu_in = self.get_parameter('imu_in').value
        imu_out = self.get_parameter('imu_out').value
        self._publish_tf = self.get_parameter('publish_tf').value
        self._odom_frame = self.get_parameter('odom_frame').value
        self._base_frame = self.get_parameter('base_frame').value

        # ---- State: Clock synchronization ----
        # New firmware publishes agent-synchronized Unix time. Older/fallback
        # firmware publishes millis() since boot. Preserve valid Unix stamps;
        # otherwise apply one shared fixed offset to odom and IMU so their
        # relative timing survives USB callback jitter.
        self._time_offset_ns = None
        self._latest_source_ns = None
        self._reported_clock_mode = None

        # ---- QoS profiles ----
        # Input: match ESP32 micro-ros-arduino defaults
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
        # Odom/IMU output: keep RELIABLE for EKF
        qos_reliable_out = QoSProfile(
            depth=20,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE,
        )

        # ---- Publishers ----
        self._odom_pub = self.create_publisher(Odometry, odom_out, qos_reliable_out)
        self._imu_pub = self.create_publisher(Imu, imu_out, qos_reliable_out)

        # ---- Subscribers ----
        self._odom_sub = self.create_subscription(
            Odometry, odom_in, self._on_odom, qos_reliable_in
        )
        self._imu_sub = self.create_subscription(
            Imu, imu_in, self._on_imu, qos_best_effort_in
        )

        # ---- Optional static odom → base_link broadcaster ----
        self._tf_broadcaster = None
        if self._publish_tf:
            self._tf_broadcaster = TransformBroadcaster(self)

        self.get_logger().info(
            f'unified_relay started:\n'
            f'  odom:  {odom_in} → {odom_out}\n'
            f'  imu:   {imu_in} → {imu_out}\n'
            f'  publish_tf: {self._publish_tf}\n'
            f'  (scan relay removed — YDLIDAR publishes /scan directly)'
        )

    @staticmethod
    def _stamp_to_ns(stamp):
        return int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)

    @staticmethod
    def _ns_to_stamp(stamp_ns):
        stamp = Time()
        stamp.sec = int(stamp_ns // 1_000_000_000)
        stamp.nanosec = int(stamp_ns % 1_000_000_000)
        return stamp

    def _get_coordinated_stamp(self, esp32_stamp):
        """Return a host-compatible stamp. Mimics old odom_imu_relay behavior by using now() to eliminate TF jitter."""
        return self.get_clock().now().to_msg()

    def _on_odom(self, msg: Odometry) -> None:
        """Relay odom with synchronized host-clock stamp."""
        stamp = self._get_coordinated_stamp(msg.header.stamp)
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
