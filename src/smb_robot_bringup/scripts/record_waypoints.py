import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
import yaml
import os
import argparse

class WaypointRecorder(Node):
    def __init__(self, filename):
        super().__init__('waypoint_recorder')
        self.subscription = self.create_subscription(
            PoseStamped,
            '/goal_pose',
            self.goal_cb,
            10)
        self.waypoints = {}
        self.counter = 0
        self.yaml_path = filename
        self.get_logger().info(f"Ready! Click 'Nav2 Goal' in RViz to record waypoints to: {self.yaml_path}")

    def goal_cb(self, msg):
        wp_name = f'waypoint{self.counter}'
        self.waypoints[wp_name] = {
            'pose': [
                msg.pose.position.x,
                msg.pose.position.y,
                msg.pose.position.z
            ],
            'orientation': [
                msg.pose.orientation.w,
                msg.pose.orientation.x,
                msg.pose.orientation.y,
                msg.pose.orientation.z
            ]
        }
        
        # Save to YAML
        with open(self.yaml_path, 'w') as f:
            yaml.dump({'waypoints': self.waypoints}, f, sort_keys=False)
            
        self.get_logger().info(f"Recorded {wp_name}: X={msg.pose.position.x:.2f}, Y={msg.pose.position.y:.2f}")
        self.counter += 1

def main(args=None):
    parser = argparse.ArgumentParser(description='Record RViz 2D Goal Poses to a YAML file.')
    parser.add_argument('-f', '--file', type=str, default='waypoints.yaml', help='Output YAML filename (e.g., my_path.yaml)')
    
    # Parse args, removing ROS args if any
    parsed_args, unknown = parser.parse_known_args()
    
    rclpy.init(args=args)
    recorder = WaypointRecorder(parsed_args.file)
    rclpy.spin(recorder)
    recorder.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
