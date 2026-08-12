import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from visualization_msgs.msg import Marker, MarkerArray
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
            
        # Publisher for visual markers in RViz
        self.marker_pub = self.create_publisher(MarkerArray, '/recorded_waypoints_markers', 10)
        
        self.waypoints = {}
        self.counter = 0
        self.yaml_path = filename
        self.get_logger().info(f"Ready! Click 'Nav2 Goal' in RViz to record waypoints to: {self.yaml_path}")
        self.get_logger().info("TIP: Add a 'MarkerArray' display in RViz subscribing to '/recorded_waypoints_markers' to see them!")

    def publish_markers(self):
        marker_array = MarkerArray()
        for i, (wp_name, data) in enumerate(self.waypoints.items()):
            marker = Marker()
            marker.header.frame_id = 'map'
            marker.header.stamp = self.get_clock().now().to_msg()
            marker.ns = 'recorded_waypoints'
            marker.id = i
            marker.type = Marker.ARROW
            marker.action = Marker.ADD
            
            marker.pose.position.x = float(data['pose'][0])
            marker.pose.position.y = float(data['pose'][1])
            marker.pose.position.z = float(data['pose'][2])
            
            marker.pose.orientation.w = float(data['orientation'][0])
            marker.pose.orientation.x = float(data['orientation'][1])
            marker.pose.orientation.y = float(data['orientation'][2])
            marker.pose.orientation.z = float(data['orientation'][3])
            
            marker.scale.x = 0.5  # Arrow length
            marker.scale.y = 0.05 # Arrow width
            marker.scale.z = 0.05 # Arrow height
            
            # Bright Green arrow
            marker.color.a = 1.0
            marker.color.r = 0.0
            marker.color.g = 1.0
            marker.color.b = 0.0
            
            marker_array.markers.append(marker)
            
        self.marker_pub.publish(marker_array)

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
            
        # Update RViz display
        self.publish_markers()
            
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
