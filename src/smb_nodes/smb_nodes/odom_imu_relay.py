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
(odom_in == odom_out, imu_in == imu_out) so it does nothing.
"""

import math

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import Imu


def quat_to_yaw(qx, qy, qz, qw):
    """Extract yaw angle from quaternion (ZYX Euler convention)."""
    # yaw (z-axis rotation)
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)
    return math.atan2(siny_cosp, cosy_cosp)


def yaw_to_quat(yaw):
    """Create quaternion from yaw angle (Z-axis rotation only)."""
    half = yaw * 0.5
    return (
        0.0,
        0.0,
        math.sin(half),
        math.cos(half),
    )


class OdomImuRelay(Node):
    def __init__(self) -> None:
        super().__init__('odom_imu_relay')

        self.declare_parameter('odom_in_topic', '/odom')
        self.declare_parameter('odom_out_topic', '/odom_relay')
        self.declare_parameter('imu_in_topic', '/imu/data')
        self.declare_parameter('imu_out_topic', '/imu/data')
        self.declare_parameter('flip_odom_x', False)
        odom_in = self.get_parameter('odom_in_topic').value
        odom_out = self.get_parameter('odom_out_topic').value
        imu_in = self.get_parameter('imu_in_topic').value
        imu_out = self.get_parameter('imu_out_topic').value
        self._flip_x = self.get_parameter('flip_odom_x').value

        qos_pub = rclpy.qos.QoSProfile(
            depth=10,
            reliability=rclpy.qos.ReliabilityPolicy.RELIABLE,
            durability=rclpy.qos.DurabilityPolicy.VOLATILE,
        )
        qos_sub = rclpy.qos.QoSProfile(
            depth=10,
            reliability=rclpy.qos.ReliabilityPolicy.BEST_EFFORT,
            durability=rclpy.qos.DurabilityPolicy.VOLATILE,
        )

        self._odom_pub = None
        self._imu_pub = None

        if odom_out:
            self._odom_pub = self.create_publisher(Odometry, odom_out, qos_pub)
        if imu_out:
            self._imu_pub = self.create_publisher(Imu, imu_out, qos_pub)

        if odom_in and self._odom_pub:
            self.create_subscription(Odometry, odom_in, self._on_odom, qos_pub)
            self.get_logger().info(f'subscribe /odom {odom_in} -> {odom_out}')
        if imu_in and self._imu_pub:
            self.create_subscription(Imu, imu_in, self._on_imu, qos_sub)
            self.get_logger().info(f'subscribe /imu {imu_in} -> {imu_out}')

        self.get_logger().info(
            f'odom_imu_relay started: '
            f'/odom {odom_in} -> {odom_out}, '
            f'/imu {imu_in} -> {imu_out} '
            f'(disabled paths skipped)')

    def _on_odom(self, msg: Odometry) -> None:
        msg.header.stamp = self.get_clock().now().to_msg()
        if self._flip_x:
            # ESP32 odom +X = motor direction = URDF +X = arrow side = physical forward.
            # Lidar angle 0° = URDF +Y = wall direction.
            # Robot initially at origin facing +X (yaw=0). Pressing teleop 'i'
            # (forward) should make ESP32 publish vx>0, which keeps vx'>0,
            # moving the robot in URDF +X direction.
            #
            # Earlier versions applied a 90° rotation here under the assumption
            # that arrow side was URDF +Y. That was wrong — URDF +X is forward.
            # Leaving this branch in place (disabled by default) so a future
            # chassis flip can re-enable it via the `flip_odom_x` launch arg
            # without re-deriving the math.
            pass
        if self._odom_pub is not None:
            self._odom_pub.publish(msg)

    def _on_imu(self, msg: Imu) -> None:
        msg.header.stamp = self.get_clock().now().to_msg()
        if self._imu_pub is not None:
            self._imu_pub.publish(msg)


def main():
    rclpy.init()
    node = OdomImuRelay()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
