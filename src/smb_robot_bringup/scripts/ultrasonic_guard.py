#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TwistStamped
from sensor_msgs.msg import Range
import time

class UltrasonicGuard(Node):
    def __init__(self):
        super().__init__('ultrasonic_guard')

        # Emergency stop threshold
        self.declare_parameter('stop_distance_m', 0.15)
        self.stop_distance = self.get_parameter('stop_distance_m').value
        
        # Keep track of actual distances to decide which way to spin
        self.distances = {
            'front': 2.0,
            'left': 2.0,
            'right': 2.0
        }

        # Spin speed when actively overriding Nav2
        self.spin_speed = 1.0  # rad/s

        # Subscriptions
        from rclpy.qos import qos_profile_sensor_data
        self.create_subscription(Range, '/us_front_dist', self.us_front_cb, qos_profile_sensor_data)
        self.create_subscription(Range, '/us_left_dist', self.us_left_cb, qos_profile_sensor_data)
        self.create_subscription(Range, '/us_right_dist', self.us_right_cb, qos_profile_sensor_data)
        # We don't need rear for this new logic as requested

        self.sub_cmd_vel_nav = self.create_subscription(
            TwistStamped,
            '/cmd_vel_nav_raw',
            self.cmd_vel_nav_cb,
            10
        )
        
        # Publisher
        self.pub_cmd_vel = self.create_publisher(TwistStamped, '/cmd_vel_nav', 10)
        
        self.get_logger().info(f"Active Override Guard started. Stop dist: {self.stop_distance}m.")

    def update_sensor(self, key, msg: Range):
        self.distances[key] = msg.range

    def us_front_cb(self, msg: Range): self.update_sensor('front', msg)
    def us_left_cb(self, msg: Range): self.update_sensor('left', msg)
    def us_right_cb(self, msg: Range): self.update_sensor('right', msg)

    def cmd_vel_nav_cb(self, msg: TwistStamped):
        out_msg = TwistStamped()
        out_msg.header = msg.header
        
        # NO-REVERSE Constraint: Never allow linear.x < 0
        cmd_linear_x = max(0.0, msg.twist.linear.x)
        cmd_angular_z = msg.twist.angular.z

        # Active Override Logic: If front is blocked, take over steering
        if self.distances['front'] < self.stop_distance:
            out_msg.twist.linear.x = 0.0
            
            # Spin away from the nearest side obstacle
            if self.distances['left'] < self.distances['right']:
                # Left is more blocked, spin right
                out_msg.twist.angular.z = -self.spin_speed
            else:
                # Right is more blocked (or equal), spin left
                out_msg.twist.angular.z = self.spin_speed
                
        else:
            # Front is clear! Let Nav2 drive (even if sides are close)
            out_msg.twist.linear.x = cmd_linear_x
            out_msg.twist.angular.z = cmd_angular_z
                
        self.pub_cmd_vel.publish(out_msg)

def main(args=None):
    rclpy.init(args=args)
    node = UltrasonicGuard()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
