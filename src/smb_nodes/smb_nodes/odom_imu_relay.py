"""Stamp-rewriting relay for /odom (and /imu/data) published by the ESP32.

Why this exists
---------------
The ESP32 firmware publishes ``/odom`` (and ``/imu/data``) with ``header.stamp``
filled from ``millis() / 1000`` — seconds since boot, in ``uint32_t`` cast to
``int32_t``. That lands in 1970 + uptime seconds. ROS2 nodes running on the host
(robot_localization EKF, slam_toolbox, Nav2) use the wall-clock for TF lookups
and reject any sample whose stamp is more than ``transform_tolerance`` seconds
away from ``now()``. With a ~50-year difference the messages are effectively
unfusable.

The companion ``scan_relay.py`` already rewrites ``/scan`` stamps. We need the
same fix for ``/odom`` and ``/imu/data``. Both relays are stateless: subscribe,
replace ``header.stamp`` with the relay's current ROS2 clock time, republish.

Topic contract
--------------
- Subscribes:
  - ``/odom``       (nav_msgs/Odometry, RELIABLE / VOLATILE / depth=10)
  - ``/imu/data``   (sensor_msgs/Imu, RELIABLE / VOLATILE / depth=10)
- Publishes:
  - ``/odom_relay`` (nav_msgs/Odometry, RELIABLE / VOLATILE / depth=10)
  - ``/imu_relay``  (sensor_msgs/Imu, RELIABLE / VOLATILE / depth=10)

The remap convention (``*_relay``) mirrors the existing ``scan_relay.py``
(which rewrites ``/scan`` -> ``/scan_relay``). Downstream subscribers
(EKF, slam_toolbox) must subscribe to the ``*_relay`` variants — the raw
topics still carry year-1970 stamps.

``smb_robot_bringup/launch/smb_robot.launch.py`` launches this relay
with the active defaults above; the matching YAMLs
(``config/robot/ekf_minimal.yaml``, ``config/robot/slam_toolbox.yaml``)
consume the ``*_relay`` topics. The sim bringup
(``smb_sim.launch.py``) launches this relay in passthrough mode
(``/odom`` -> ``/odom``) because Gazebo already stamps messages with
host-clock time.

When to remove this fix
-----------------------
Once the ESP32 firmware stamps messages with wall-clock time (NTP sync via
WiFi or an RTC), the relay can stop rewriting ``header.stamp`` and go back to
field-for-field passthrough.
"""

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu


class OdomImuRelay(Node):
    """Rewrite header.stamp on ESP32's /odom and /imu/data to host wall-clock."""

    def __init__(self) -> None:
        super().__init__('odom_imu_relay')

        # ---- Parameters (overridable via --ros-args -p ...) ----
        self.declare_parameter('odom_in_topic', '/odom')
        self.declare_parameter('odom_out_topic', '/odom_relay')
        self.declare_parameter('imu_in_topic', '/imu/data')
        self.declare_parameter('imu_out_topic', '/imu_relay')
        odom_in = self.get_parameter('odom_in_topic').value
        odom_out = self.get_parameter('odom_out_topic').value
        imu_in = self.get_parameter('imu_in_topic').value
        imu_out = self.get_parameter('imu_out_topic').value

        # ---- QoS ----
        # ESP32 micro-ros-arduino defaults to RELIABLE/VOLATILE/keep_last(10) for
        # both /odom and /imu/data. Match exactly so the subscription succeeds.
        qos = QoSProfile(
            depth=10,
            reliability=QoSReliabilityPolicy.RELIABLE,
        )

        # ---- I/O ----
        # Only subscribe/publish when in_topic != out_topic (no-op passthrough
        # is the default, which lets users opt-out without removing the node).
        if odom_out and odom_out != odom_in:
            self._odom_pub = self.create_publisher(Odometry, odom_out, qos)
            self._odom_sub = self.create_subscription(
                Odometry, odom_in, self._on_odom, qos)
        else:
            self._odom_pub = None
            self._odom_sub = None

        if imu_out and imu_out != imu_in:
            self._imu_pub = self.create_publisher(Imu, imu_out, qos)
            self._imu_sub = self.create_subscription(
                Imu, imu_in, self._on_imu, qos)
        else:
            self._imu_pub = None
            self._imu_sub = None

        self.get_logger().info(
            f'odom_imu_relay started: '
            f'/odom {odom_in} -> {odom_out}, '
            f'/imu {imu_in} -> {imu_out} '
            f'(disabled paths skipped)')

    def _on_odom(self, msg: Odometry) -> None:
        msg.header.stamp = self.get_clock().now().to_msg()
        if self._odom_pub is not None:
            self._odom_pub.publish(msg)

    def _on_imu(self, msg: Imu) -> None:
        msg.header.stamp = self.get_clock().now().to_msg()
        if self._imu_pub is not None:
            self._imu_pub.publish(msg)


def main(args=None) -> int:
    rclpy.init(args=args)
    node = OdomImuRelay()
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
