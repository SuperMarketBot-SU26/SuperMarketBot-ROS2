#!/usr/bin/env python3
"""
ROS 2 Shelf Vision Node for SuperMarketBot
Subscriptions:
  - /camera/image_raw (sensor_msgs/msg/Image)
Publications:
  - /shelf/analysis (std_msgs/msg/String - JSON string compatible with Backend & MQTT)
  - /shelf/annotated_image (sensor_msgs/msg/Image - Optional HUD visualization)
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String
from cv_bridge import CvBridge
import cv2
import json
import time
import os

try:
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False

class ShelfVisionNode(Node):
    def __init__(self):
        super().__init__('shelf_vision_node')
        
        # Declare parameters
        self.declare_parameter('model_path', 'best.pt')
        self.declare_parameter('conf_threshold', 0.25)
        self.declare_parameter('shelf_id', 4) # Default to Shelf 4 (Noodles/Porridge)
        
        model_path = self.get_parameter('model_path').get_parameter_value().string_value
        self.conf_threshold = self.get_parameter('conf_threshold').get_parameter_value().double_value
        self.shelf_id = self.get_parameter('shelf_id').get_parameter_value().integer_value
        
        self.get_logger().info(f"Loading YOLO Model from: {model_path}...")
        self.model = YOLO(model_path) if HAS_YOLO else None
        self.bridge = CvBridge()
        
        # Publishers & Subscribers
        self.sub_image = self.create_subscription(
            Image,
            '/camera/image_raw',
            self.image_callback,
            10
        )
        self.pub_analysis = self.create_publisher(String, '/shelf/analysis', 10)
        self.pub_annotated = self.create_publisher(Image, '/shelf/annotated_image', 10)
        
        self.last_inference_time = 0.0
        self.get_logger().info("ShelfVisionNode initialized and ready.")

    def image_callback(self, msg: Image):
        # Throttle inference to ~5-10 FPS on Raspberry Pi to preserve CPU/GPU
        now = time.time()
        if now - self.last_inference_time < 0.1:
            return
        self.last_inference_time = now

        try:
            cv_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f"Failed to convert ROS Image to OpenCV: {e}")
            return

        if self.model is None:
            return

        start_t = time.time()
        results = self.model(cv_frame, conf=self.conf_threshold, verbose=False)[0]
        h, w = cv_frame.shape[:2]
        total_frame_area = float(h * w)

        detected_objects = []
        total_bbox_area = 0.0

        for box in results.boxes:
            cls_id = int(box.cls[0].item())
            class_name = self.model.names.get(cls_id, f"obj_{cls_id}")
            conf = float(box.conf[0].item())
            xyxy = box.xyxy[0].tolist()
            x1, y1, x2, y2 = map(int, xyxy)
            is_empty = (class_name == "empty_slot")

            if not is_empty:
                total_bbox_area += float((x2 - x1) * (y2 - y1))

            detected_objects.append({
                "label": class_name,
                "confidence": round(conf, 3),
                "box": [x1, y1, x2, y2],
                "isEmptySlot": is_empty
            })

        # Calculate density
        product_objs = [o for o in detected_objects if not o["isEmptySlot"]]
        empty_objs = [o for o in detected_objects if o["isEmptySlot"]]
        num_products = len(product_objs)
        num_empty = len(empty_objs)

        coverage_ratio = min(1.0, (total_bbox_area / (total_frame_area * 0.70)))
        raw_density_pct = round(coverage_ratio * 100.0, 1)

        if num_products == 0:
            density_pct = 0.0
            stock_status = "Out of Stock"
        elif num_empty >= 2 or num_products < 2:
            density_pct = max(10.0, min(raw_density_pct, 40.0))
            stock_status = "Low Stock"
        elif num_products >= 4 and num_empty == 0:
            density_pct = max(raw_density_pct, min(95.0, 60.0 + num_products * 8.0))
            stock_status = "Well Stocked" if density_pct >= 70.0 else "Normal"
        else:
            density_pct = max(35.0, raw_density_pct)
            stock_status = "Normal"

        inf_time_ms = round((time.time() - start_t) * 1000, 1)

        # JSON payload matching SuperMarketBot Backend Specification
        payload = {
            "shelfId": self.shelf_id,
            "shelfCategory": "Kệ 4 - Mì Ăn Liền & Đóng Gói",
            "densityPct": density_pct,
            "densityPercentage": density_pct,
            "emptyPercentage": round(max(0.0, 100.0 - density_pct), 1),
            "stockStatus": stock_status,
            "isOutOfStock": (stock_status == "Out of Stock"),
            "isLowStock": (stock_status == "Low Stock"),
            "totalObjects": num_products,
            "totalEmptySlots": num_empty,
            "inferenceTimeMs": inf_time_ms,
            "detectedObjects": detected_objects,
            "timestamp": int(time.time() * 1000)
        }

        # Publish JSON to ROS 2 topic /shelf/analysis
        out_msg = String()
        out_msg.data = json.dumps(payload, ensure_ascii=False)
        self.pub_analysis.publish(out_msg)

def main(args=None):
    rclpy.init(args=args)
    node = ShelfVisionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
