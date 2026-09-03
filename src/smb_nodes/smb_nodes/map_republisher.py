"""map_republisher.py — Periodically re-publishes /map with volatile QoS.

Why this exists:
    nav2_map_server publishes /map with transient_local QoS durability.
    DDS multicast over the network does NOT reliably propagate transient_local
    messages to late-joining subscribers on different machines (e.g. RViz on a
    dev laptop connecting to a Pi 5 robot). This node subscribes locally with
    transient_local QoS (guaranteed to receive the latched message) and then
    re-publishes it every few seconds with volatile QoS so remote clients
    always see the map.
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from nav_msgs.msg import OccupancyGrid


class MapRepublisher(Node):
    def __init__(self):
        super().__init__('map_republisher')

        self.declare_parameter('republish_rate', 2.0)  # Hz
        rate = self.get_parameter('republish_rate').value

        # Subscribe with transient_local to get the latched message from map_server
        sub_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.sub = self.create_subscription(
            OccupancyGrid, '/map', self._on_map, sub_qos)

        # Publish with transient_local so RViz (which expects transient_local) can subscribe.
        # Since we republish in a loop, remote clients will catch the next broadcast.
        pub_qos = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.pub = self.create_publisher(
            OccupancyGrid, '/map_volatile', pub_qos)

        self._latest_map = None
        self.timer = self.create_timer(1.0 / rate, self._republish)
        self.get_logger().info(
            f'Map republisher started: /map (transient_local) → /map_volatile (volatile) @ {rate} Hz')

    def _on_map(self, msg: OccupancyGrid):
        self._latest_map = msg
        self.get_logger().info(
            f'Received map: {msg.info.width}x{msg.info.height} @ {msg.info.resolution} m/pix',
            once=True)

    def _republish(self):
        if self._latest_map is not None:
            # Update the timestamp so RViz's message filter doesn't drop it
            # complaining that the timestamp is too old compared to current TF
            self._latest_map.header.stamp = self.get_clock().now().to_msg()
            self.pub.publish(self._latest_map)


def main(args=None):
    rclpy.init(args=args)
    node = MapRepublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
