#!/usr/bin/env python3
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from geometry_msgs.msg import TwistStamped
from sensor_msgs.msg import Range
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from action_msgs.srv import CancelGoal
import time

class UltrasonicGuard(Node):
    def __init__(self):
        super().__init__('ultrasonic_guard')

        # Configuration
        self.declare_parameter('stop_distance_m', 0.30)
        self.declare_parameter('abort_timeout_s', 30.0)
        
        self.stop_distance = self.get_parameter('stop_distance_m').value
        self.abort_timeout = self.get_parameter('abort_timeout_s').value
        
        self.obstacle_detected = False
        self.obstacle_start_time = 0.0

        # Post-rotation wait state (REMOVED)

        # Subscriptions & Publishers
        self.sub_cmd_vel_nav = self.create_subscription(
            TwistStamped,
            '/cmd_vel_nav_raw',
            self.cmd_vel_nav_cb,
            10
        )
        
        from rclpy.qos import qos_profile_sensor_data
        
        self.sub_us_front = self.create_subscription(
            Range,
            '/us_front_dist',
            self.us_front_cb,
            qos_profile_sensor_data
        )
        
        self.pub_cmd_vel = self.create_publisher(
            TwistStamped,
            '/cmd_vel_nav',
            10
        )
        
        # Service client to cancel Nav2 goals globally
        self.nav_cancel_client = self.create_client(CancelGoal, '/navigate_to_pose/_action/cancel_goal')

        self.get_logger().info(f"Ultrasonic Guard started. Stop dist: {self.stop_distance}m, Abort timeout: {self.abort_timeout}s")

    def us_front_cb(self, msg: Range):
        import math
        # 0.0, NaN, or values <= 4cm indicate sensor timeout / no echo (clear open space), NOT an obstacle!
        is_valid_reading = not math.isnan(msg.range) and msg.range > 0.04 and msg.range <= 2.5
        is_obstacle_close = is_valid_reading and (msg.range < self.stop_distance)

        if is_obstacle_close:
            if not self.obstacle_detected:
                self.obstacle_detected = True
                self.obstacle_start_time = time.time()
                self.get_logger().warning(f"Obstacle detected at {msg.range:.2f}m! Forward motion blocked.")
            else:
                # Check timeout
                if time.time() - self.obstacle_start_time > self.abort_timeout:
                    self.get_logger().error(f"Obstacle present for > {self.abort_timeout}s! Cancelling Nav2 goal.")
                    self.cancel_nav2_goal()
                    self.obstacle_start_time = time.time() # Reset timer so we don't spam cancels
        else:
            if self.obstacle_detected:
                self.obstacle_detected = False
                self.get_logger().info("Obstacle cleared. Resuming normal motion.")

    def cmd_vel_nav_cb(self, msg: TwistStamped):
        out_msg = TwistStamped()
        out_msg.header = msg.header
        
        # Determine if the robot is currently doing an in-place rotation
        is_rotating = abs(msg.twist.angular.z) > 0.01 and abs(msg.twist.linear.x) < 0.01
        
        # (Post-rotation delay removed)
        # We only block forward motion (linear.x > 0) for obstacles. We allow backing up or pure rotation.
        out_msg.twist.linear.y = msg.twist.linear.y
        out_msg.twist.linear.z = msg.twist.linear.z
        out_msg.twist.angular.x = msg.twist.angular.x
        out_msg.twist.angular.y = msg.twist.angular.y
        out_msg.twist.angular.z = msg.twist.angular.z
        
        if self.obstacle_detected and msg.twist.linear.x > 0.0:
            out_msg.twist.linear.x = 0.0
            # If it's trying to move forward and turn, let it just turn
        else:
            out_msg.twist.linear.x = msg.twist.linear.x
            
        self.pub_cmd_vel.publish(out_msg)

    def cancel_nav2_goal(self):
        if not self.nav_cancel_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().error('Nav2 cancel service not available!')
            return
            
        # Send an empty cancel request to cancel all active goals
        cancel_req = CancelGoal.Request()
        cancel_future = self.nav_cancel_client.call_async(cancel_req)
        cancel_future.add_done_callback(self.cancel_done_cb)

    def cancel_done_cb(self, future):
        try:
            cancel_response = future.result()
            if len(cancel_response.goals_canceling) > 0:
                self.get_logger().info('Successfully cancelled Nav2 goal due to timeout.')
            else:
                self.get_logger().info('Goal cancel request accepted, but no active goals to cancel.')
        except Exception as e:
            self.get_logger().error(f'Failed to cancel goal: {e}')

def main(args=None):
    rclpy.init(args=args)
    node = UltrasonicGuard()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()
