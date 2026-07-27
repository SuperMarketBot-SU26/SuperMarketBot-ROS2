"""QoS-relay node for the LiDAR ``/scan`` topic.

Why this exists
---------------
The ESP32 firmware publishes ``/scan`` with ``RELIABLE`` QoS (the micro-ROS
default — the BEST_EFFORT variant has been observed to silently fail on the
heap-constrained ESP32-S3). slam_toolbox subscribes with ``BEST_EFFORT``
because laser scans are inherently lossy and the SLAM stack does not need
guaranteed delivery. DDS treats this combination as incompatible: no
discovery matches between the publisher and subscriber, and the scan is
effectively dropped on the subscriber side.

This node sits between the two: it subscribes to ``/scan`` with the
RELIABLE QoS that matches the ESP32, and republishes the same data on
``/scan_relay`` with the BEST_EFFORT QoS that matches slam_toolbox. RViz
and any other consumer that wants the BEST_EFFORT data should subscribe
to ``/scan_relay``; slam_toolbox is remapped to ``/scan_relay`` in
``smb_robot_bringup/config/robot/slam_toolbox.yaml``.

Why we also rewrite ``header.stamp``
------------------------------------
The ESP32 fills ``header.stamp`` with ``millis() / 1000`` (seconds since
boot) because micro-ros-arduino does not have access to wall-clock time
on the bare ESP32-S3 (no RTC, no NTP sync yet). Wall-clock time at the
ROS2 host is Unix epoch seconds. The two clocks differ by ~50 years, so
slam_toolbox's ``message_filters`` sees every scan as ~50 years in the
past and rejects it with ``the timestamp on the message is earlier than
all the data in the transform cache``. RViz applies the same filter on
its display side, hence "no laser data" in the view.

We overwrite ``header.stamp`` here with the relay's current ROS2 clock
time (Unix epoch seconds when ``use_sim_time=false``, ``/clock`` time
when ``use_sim_time=true``). ``frame_id`` is left untouched — the
URDF/robot_state_publisher define ``laser_frame``, the firmware already
publishes with that id, and the TF lookup chain ``map → odom → base_link
→ laser_frame`` is intact.

When to remove this fix
-----------------------
Once the ESP32 firmware sets a coherent wall-clock stamp at boot (NTP
sync via WiFi, or an RTC), this relay can stop rewriting the stamp and
go back to field-for-field passthrough. The QoS bridge (RELIABLE in,
BEST_EFFORT out) remains useful regardless — it lets ESP32 keep its
RELIABLE publisher default without forcing the rest of the ROS2 graph
to switch.

Topic / QoS contract
--------------------
- Subscribes: ``/scan`` (sensor_msgs/LaserScan, RELIABLE / VOLATILE /
  KEEP_LAST(10)) — matches ESP32 micro-ros-arduino defaults.
- Publishes: ``/scan_relay`` (sensor_msgs/LaserScan, BEST_EFFORT /
  VOLATILE / KEEP_LAST(5)) — matches slam_toolbox subscriber defaults.
  ``header.stamp`` is replaced with current ROS2 clock.
"""

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import LaserScan


class ScanRelay(Node):
    """QoS bridge between the ESP32 publisher and slam_toolbox."""

    def __init__(self):
        super().__init__('scan_relay')

        # ---- Parameters (overridable at launch via --ros-args -p ...) ----
        self.declare_parameter('in_topic', '/scan')
        self.declare_parameter('out_topic', '/scan_relay')
        in_topic = self.get_parameter('in_topic').value
        out_topic = self.get_parameter('out_topic').value

        # ---- QoS ----
        # In: match ESP32 micro-ros-arduino's default RELIABLE publisher.
        # Out: match slam_toolbox's BEST_EFFORT subscriber default so the
        # SLAM stack accepts the data.
        in_qos = QoSProfile(
            depth=10, reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE)
        out_qos = QoSProfile(
            depth=5, reliability=QoSReliabilityPolicy.BEST_EFFORT,
            durability=QoSDurabilityPolicy.VOLATILE)

        # ---- I/O ----
        self._pub = self.create_publisher(LaserScan, out_topic, out_qos)
        self._sub = self.create_subscription(
            LaserScan, in_topic, self._on_scan, in_qos)

        self.get_logger().info(
            f'scan_relay started: {in_topic} (RELIABLE) -> '
            f'{out_topic} (BEST_EFFORT)')

    def _on_scan(self, msg: LaserScan) -> None:
        # Overwrite header.stamp with the relay's current ROS2 clock time.
        # See module docstring "Why we also rewrite header.stamp" for why
        # this is needed: ESP32 millis()/1000 vs Unix epoch causes slam_toolbox
        # and RViz to drop every scan with "earlier than all the data in the
        # transform cache". frame_id is left alone (laser_frame is correct
        # and matches the URDF).
        now = self.get_clock().now().to_msg()
        msg.header.stamp = now
        self._pub.publish(msg)


def main(args=None) -> int:
    rclpy.init(args=args)
    node = ScanRelay()
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