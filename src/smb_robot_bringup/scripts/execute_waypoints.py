#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import FollowWaypoints
from geometry_msgs.msg import PoseStamped
import yaml
import argparse
import sys

class WaypointFollowerClient(Node):
    def __init__(self):
        super().__init__('waypoint_follower_client')
        self._action_client = ActionClient(self, FollowWaypoints, '/follow_waypoints')

    def send_goal(self, yaml_file):
        self.get_logger().info(f'Loading waypoints from {yaml_file}...')
        
        try:
            with open(yaml_file, 'r') as f:
                data = yaml.safe_load(f)
        except Exception as e:
            self.get_logger().error(f'Failed to open YAML file: {e}')
            return

        if 'waypoints' not in data:
            self.get_logger().error('Invalid YAML format: missing "waypoints" key.')
            return

        waypoints = []
        for wp_name, wp_data in data['waypoints'].items():
            pose = PoseStamped()
            pose.header.frame_id = 'map'
            pose.header.stamp = self.get_clock().now().to_msg()
            
            pose.pose.position.x = float(wp_data['pose'][0])
            pose.pose.position.y = float(wp_data['pose'][1])
            pose.pose.position.z = float(wp_data['pose'][2])
            
            pose.pose.orientation.w = float(wp_data['orientation'][0])
            pose.pose.orientation.x = float(wp_data['orientation'][1])
            pose.pose.orientation.y = float(wp_data['orientation'][2])
            pose.pose.orientation.z = float(wp_data['orientation'][3])
            
            waypoints.append(pose)
            self.get_logger().info(f'Loaded {wp_name}: x={pose.pose.position.x:.2f}, y={pose.pose.position.y:.2f}')

        if not waypoints:
            self.get_logger().error('No waypoints found in file.')
            return

        self.get_logger().info('Waiting for /follow_waypoints action server...')
        if not self._action_client.wait_for_server(timeout_sec=10.0):
            self.get_logger().error('Action server not available!')
            return

        goal_msg = FollowWaypoints.Goal()
        goal_msg.poses = waypoints

        self.get_logger().info(f'Sending {len(waypoints)} waypoints to the robot...')
        self._send_goal_future = self._action_client.send_goal_async(goal_msg)
        self._send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('Robot rejected the waypoints!')
            sys.exit(1)

        self.get_logger().info('Robot accepted the waypoints! Navigation started.')
        self._get_result_future = goal_handle.get_result_async()
        self._get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        result = future.result().result
        missed_waypoints = len(result.missed_waypoints)
        if missed_waypoints > 0:
            self.get_logger().warn(f'Navigation completed, but robot missed {missed_waypoints} waypoints.')
        else:
            self.get_logger().info('Success! Robot successfully reached all waypoints.')
        sys.exit(0)


def main(args=None):
    parser = argparse.ArgumentParser(description='Send a YAML file of waypoints to Nav2')
    parser.add_argument('-f', '--file', type=str, required=True, help='Path to the YAML waypoints file')
    
    parsed_args, unknown = parser.parse_known_args()
    
    rclpy.init(args=args)
    client = WaypointFollowerClient()
    client.send_goal(parsed_args.file)
    
    try:
        rclpy.spin(client)
    except KeyboardInterrupt:
        pass
    finally:
        client.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
