#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import json
import statistics
import time

class ShelfAggregatorNode(Node):
    def __init__(self):
        super().__init__('shelf_aggregator')
        self.sub = self.create_subscription(String, '/shelf/analysis', self.analysis_cb, 10)
        self.pub = self.create_publisher(String, '/shelf/density_report', 10)
        
        self.state = "IDLE"
        self.current_shelf_id = 0
        self.density_history = []
        self.status_history = []
        self.start_time = 0.0
        self.last_seen_time = 0.0
        
        self.AGGREGATION_WINDOW = 3.0 # seconds
        self.COOLDOWN_WINDOW = 10.0 # seconds
        
        self.get_logger().info("Shelf Aggregator Node started. Waiting for ArUco triggers...")

    def analysis_cb(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            return
            
        shelf_id = payload.get("shelfId", 0)
        now = time.time()
        
        if self.state == "IDLE":
            if shelf_id != 0:
                self.get_logger().info(f"Detected ArUco ID {shelf_id}. Starting {self.AGGREGATION_WINDOW}s aggregation window.")
                self.state = "AGGREGATING"
                self.current_shelf_id = shelf_id
                self.density_history = [payload.get("densityPct", 0.0)]
                self.status_history = [payload.get("stockStatus", "Normal")]
                self.start_time = now
                self.last_seen_time = now
                
        elif self.state == "AGGREGATING":
            if shelf_id == self.current_shelf_id:
                self.density_history.append(payload.get("densityPct", 0.0))
                self.status_history.append(payload.get("stockStatus", "Normal"))
                self.last_seen_time = now
                
            if (now - self.start_time) >= self.AGGREGATION_WINDOW:
                self.report_and_cooldown(now)
                
        elif self.state == "COOLDOWN":
            if shelf_id == self.current_shelf_id:
                self.last_seen_time = now # Keep extending cooldown while we still see it
            
            # If we haven't seen the marker for 5 seconds, or we see a completely different marker
            if (now - self.last_seen_time) > 5.0 or (shelf_id != 0 and shelf_id != self.current_shelf_id):
                self.get_logger().info(f"Cooldown finished for shelf {self.current_shelf_id}. Resetting to IDLE.")
                self.state = "IDLE"
                self.current_shelf_id = 0

    def report_and_cooldown(self, now):
        if not self.density_history:
            return
            
        median_density = statistics.median(self.density_history)
        
        # Most frequent status
        status_counts = {}
        for s in self.status_history:
            status_counts[s] = status_counts.get(s, 0) + 1
        final_status = max(status_counts, key=status_counts.get)
        
        report = {
            "shelfId": self.current_shelf_id,
            "densityPct": round(median_density, 1),
            "stockStatus": final_status,
            "timestamp": int(now * 1000)
        }
        
        self.get_logger().info(f"--- AGGREGATION COMPLETE ---")
        self.get_logger().info(f"Shelf {self.current_shelf_id} final density: {report['densityPct']}% ({final_status})")
        self.get_logger().info(f"Samples collected: {len(self.density_history)}")
        
        # Publish to the bridge topic
        msg = String()
        msg.data = json.dumps(report, ensure_ascii=False)
        self.pub.publish(msg)
        
        self.state = "COOLDOWN"
        self.last_seen_time = now
        self.get_logger().info("Entering COOLDOWN state. Ignoring this shelf until robot moves away.")

def main(args=None):
    rclpy.init(args=args)
    node = ShelfAggregatorNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
