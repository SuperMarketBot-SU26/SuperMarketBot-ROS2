#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from geometry_msgs.msg import PoseStamped
import argparse
import sys
import math

class GoToClient(Node):
    def __init__(self):
        super().__init__('go_to_client')
        self._action_client = ActionClient(self, NavigateToPose, '/navigate_to_pose')

    def send_goal(self, x, y, yaw):
        self.get_logger().info('Waiting for /navigate_to_pose action server...')
        if not self._action_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('Action server not available!')
            sys.exit(1)

        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        
        goal_msg.pose.pose.position.x = float(x)
        goal_msg.pose.pose.position.y = float(y)
        goal_msg.pose.pose.position.z = 0.0
        
        # Convert yaw (radians) to Quaternion (z, w) for 2D map
        goal_msg.pose.pose.orientation.x = 0.0
        goal_msg.pose.pose.orientation.y = 0.0
        goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)

        self.get_logger().info(f'Sending robot to X: {x}, Y: {y}, Yaw: {yaw} rad...')
        self._send_goal_future = self._action_client.send_goal_async(goal_msg)
        self._send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('Robot rejected the goal!')
            sys.exit(1)

        self.get_logger().info('Robot accepted the goal! Driving now...')
        self._get_result_future = goal_handle.get_result_async()
        self._get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        result_status = future.result().status
        # Status 4 = SUCCEEDED in actionlib
        if result_status == 4:
            self.get_logger().info('Success! Robot reached the destination.')
            sys.exit(0)
        else:
            self.get_logger().warn(f'Navigation ended with status code: {result_status}')
            sys.exit(1)


def main(args=None):
    parser = argparse.ArgumentParser(description='Send a single coordinate goal to Nav2')
    parser.add_argument('-x', type=float, required=True, help='X coordinate in meters')
    parser.add_argument('-y', type=float, required=True, help='Y coordinate in meters')
    parser.add_argument('-yaw', type=float, default=0.0, help='Heading angle in radians (default: 0.0)')
    
    parsed_args, unknown = parser.parse_known_args()
    
    rclpy.init(args=args)
    client = GoToClient()
    client.send_goal(parsed_args.x, parsed_args.y, parsed_args.yaw)
    
    try:
        rclpy.spin(client)
    except KeyboardInterrupt:
        pass
    finally:
        client.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
