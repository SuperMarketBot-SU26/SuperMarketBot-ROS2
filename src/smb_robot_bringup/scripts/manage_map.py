#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
import argparse
import sys
import subprocess
from slam_toolbox.srv import SerializePoseGraph, DeserializePoseGraph
from geometry_msgs.msg import Pose

class MapManager(Node):
    def __init__(self):
        super().__init__('map_manager')

    def serialize_map(self, filename):
        self.get_logger().info(f'Saving occupancy grid (.yaml and .pgm) to: {filename}')
        try:
            subprocess.run(["ros2", "run", "nav2_map_server", "map_saver_cli", "-f", filename], check=True)
            self.get_logger().info('Occupancy grid saved successfully!')
        except subprocess.CalledProcessError as e:
            self.get_logger().error(f'Failed to save occupancy grid! Error: {e}')
            return False

        client = self.create_client(SerializePoseGraph, '/slam_toolbox/serialize_map')
        if not client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('Serialize service not available! Is SLAM Toolbox running?')
            return False

        req = SerializePoseGraph.Request()
        req.filename = filename
        
        self.get_logger().info(f'Calling serialize_map for: {filename}')
        future = client.call_async(req)
        rclpy.spin_until_future_complete(self, future)
        
        response = future.result()
        if response is not None:
            if response.result == 0: # RESULT_SUCCESS
                self.get_logger().info('Map serialized successfully!')
                return True
            else:
                self.get_logger().error(f'Failed to serialize map. Error code: {response.result}')
                return False
        else:
            self.get_logger().error('Service call failed')
            return False

    def deserialize_map(self, filename, match_type):
        client = self.create_client(DeserializePoseGraph, '/slam_toolbox/deserialize_map')
        if not client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('Deserialize service not available! Is SLAM Toolbox running?')
            return False

        req = DeserializePoseGraph.Request()
        req.filename = filename
        
        # Match type: 0=UNSET, 1=START_AT_FIRST_NODE, 2=START_AT_GIVEN_POSE, 3=LOCALIZATION
        if match_type == 'localization':
            req.match_type = 3
        elif match_type == 'first_node':
            req.match_type = 1
        else:
            req.match_type = 0
            
        req.initial_pose = Pose() # Zero pose, ignored if START_AT_FIRST_NODE
        
        self.get_logger().info(f'Calling deserialize_map for: {filename} with mode {match_type}')
        future = client.call_async(req)
        rclpy.spin_until_future_complete(self, future)
        
        response = future.result()
        if response is not None:
            self.get_logger().info('Map deserialize request processed.')
            return True
        else:
            self.get_logger().error('Service call failed')
            return False

def main(args=None):
    parser = argparse.ArgumentParser(description='Save (serialize) or Load (deserialize) SLAM Toolbox maps.')
    parser.add_argument('action', choices=['save', 'load'], help='Action to perform')
    parser.add_argument('-f', '--file', type=str, required=True, help='Absolute path and base filename of the map (no extension)')
    parser.add_argument('--mode', type=str, choices=['localization', 'first_node'], default='first_node', help='Load mode (for load action only)')
    
    parsed_args, unknown = parser.parse_known_args()
    
    rclpy.init(args=args)
    manager = MapManager()
    
    if parsed_args.action == 'save':
        manager.serialize_map(parsed_args.file)
    elif parsed_args.action == 'load':
        manager.deserialize_map(parsed_args.file, parsed_args.mode)
        
    manager.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
