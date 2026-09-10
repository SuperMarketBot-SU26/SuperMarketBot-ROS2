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
        self.sub_trigger = self.create_subscription(String, '/shelf/sweep/trigger', self.trigger_cb, 10)
        self.pub = self.create_publisher(String, '/shelf/density_report', 10)
        
        self.state = "IDLE"
        self.current_shelf_id = 0
        self.density_history = []
        self.status_history = []
        self.start_time = 0.0
        self.last_seen_time = 0.0
        
        self.AGGREGATION_WINDOW = 2.0 # seconds (được cập nhật theo duration từ lệnh FE)
        
        self.get_logger().info("Shelf Aggregator Node started. Chỉ quét khi nhận lệnh thủ công từ FE qua /shelf/sweep/trigger.")

    def trigger_cb(self, msg: String):
        """Kích hoạt quét khi nhận lệnh bấm từ FE."""
        try:
            data = json.loads(msg.data)
            shelf_id = int(data.get("shelfId", 0))
            duration = float(data.get("duration", 2.0))
            if shelf_id > 0:
                self.get_logger().info(f"🎯 Nhận lệnh quét từ FE: Kệ #{shelf_id} trong {duration}s. Bắt đầu gom dữ liệu...")
                self.state = "AGGREGATING"
                self.current_shelf_id = shelf_id
                self.density_history = []
                self.status_history = []
                self.AGGREGATION_WINDOW = duration
                self.start_time = time.time()
                self.last_seen_time = self.start_time
        except Exception as e:
            self.get_logger().error(f"Lỗi cú pháp lệnh trigger từ FE: {e}")

    def analysis_cb(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            return
            
        shelf_id = payload.get("shelfId", 0)
        now = time.time()
        
        # ĐÃ XÓA AUTO-TRIGGER: Ở trạng thái IDLE, robot KHÔNG tự động quét khi nhìn thấy ArUco tag
        if self.state == "AGGREGATING":
            # Gom mẫu phân tích nếu khớp kệ đang yêu cầu hoặc nếu shelfId từ vision = current_shelf_id
            if shelf_id == self.current_shelf_id or shelf_id == 0:
                pct = payload.get("densityPct", payload.get("densityPercentage", None))
                if pct is not None:
                    self.density_history.append(float(pct))
                    self.status_history.append(payload.get("stockStatus", "Normal"))
                self.last_seen_time = now
                
            if (now - self.start_time) >= self.AGGREGATION_WINDOW:
                self.report_and_reset(now)

    def report_and_reset(self, now):
        self.state = "IDLE"
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
        
        self.state = "IDLE"
        self.get_logger().info("Hoàn tất quét. Đã về trạng thái IDLE sẵn sàng cho lần bấm tiếp theo.")

def main(args=None):
    rclpy.init(args=args)
    node = ShelfAggregatorNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
