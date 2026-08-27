#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import json
import time
import random

class MockAIPublisher(Node):
    def __init__(self):
        super().__init__('mock_ai_publisher')
        self.pub = self.create_publisher(String, '/shelf/analysis', 10)
        self.timer = self.create_timer(0.1, self.timer_callback) # 10 FPS
        self.start_time = time.time()
        self.get_logger().info("Mock AI Publisher started. Simulating a robot locking onto Shelf 4 for 10 seconds...")

    def timer_callback(self):
        elapsed = time.time() - self.start_time
        
        # For the first 10 seconds, simulate looking at Shelf 4
        if elapsed < 10.0:
            shelf_id = 4
            # Add some random noise to simulate real AI flickering
            base_density = 45.0
            noise = random.uniform(-5.0, 5.0)
            density = base_density + noise
            status = "Normal" if density >= 40.0 else "Low Stock"
        else:
            # After 10 seconds, simulate moving away (Shelf 0)
            shelf_id = 0
            density = 0.0
            status = "Unknown"
            
        payload = {
            "shelfId": shelf_id,
            "densityPct": round(density, 1),
            "stockStatus": status,
            "timestamp": int(time.time() * 1000)
        }
        
        msg = String()
        msg.data = json.dumps(payload)
        self.pub.publish(msg)
        
        if elapsed > 15.0:
            self.get_logger().info("Simulation complete. Exiting...")
            raise SystemExit

def main(args=None):
    rclpy.init(args=args)
    node = MockAIPublisher()
    try:
        rclpy.spin(node)
    except SystemExit:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
