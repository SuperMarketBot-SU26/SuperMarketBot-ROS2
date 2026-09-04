#!/usr/bin/env python3
"""
ROS 2 Shelf Vision Node for SuperMarketBot (Phiên bản V5 - 2-Stage Re-ID & Multi-Tier Analytics)
Subscriptions:
  - /camera/image_raw (sensor_msgs/msg/Image) : Luồng ảnh thô từ camera robot
Publications:
  - /shelf/analysis (std_msgs/msg/String)     : Chuỗi JSON phân tích kệ hàng chuẩn Backend & MQTT
  - /shelf/annotated_image (sensor_msgs/msg/Image) : Khung hình HUD trực quan (tùy chọn)
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
import sys

# Thêm thư mục hiện tại vào sys.path để nạp shelf_vision và product_matcher
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from shelf_vision import ShelfVisionEngine
    HAS_VISION_ENGINE = True
except ImportError as e:
    HAS_VISION_ENGINE = False
    IMPORT_ERROR = str(e)

class ShelfVisionNode(Node):
    def __init__(self):
        super().__init__('shelf_vision_node')
        
        # Tham số cấu hình
        self.declare_parameter('model_path', os.path.join(current_dir, 'best.pt'))
        self.declare_parameter('conf_threshold', 0.06)
        self.declare_parameter('fps_limit', 5.0)
        
        model_path = self.get_parameter('model_path').get_parameter_value().string_value
        conf_threshold = self.get_parameter('conf_threshold').get_parameter_value().double_value
        self.min_interval = 1.0 / max(1.0, self.get_parameter('fps_limit').get_parameter_value().double_value)
        
        self.get_logger().info(f"Khởi tạo ShelfVisionEngine V5 (YOLO + MobileNetV3 Re-ID) với model: {model_path}...")
        
        if not HAS_VISION_ENGINE:
            self.get_logger().fatal(f"Không thể nạp ShelfVisionEngine: {IMPORT_ERROR}")
            self.engine = None
        else:
            self.engine = ShelfVisionEngine(model_path=model_path, conf_threshold=conf_threshold)
            self.get_logger().info(f"Đã nạp thành công mô hình với {len(self.engine.matcher.reference_embeddings)} danh mục kệ!")
            
        self.bridge = CvBridge()
        
        # Đăng ký Topic
        self.sub_image = self.create_subscription(
            Image,
            '/camera/image_raw',
            self.image_callback,
            10
        )
        self.pub_analysis = self.create_publisher(String, '/shelf/analysis', 10)
        self.pub_annotated = self.create_publisher(Image, '/shelf/annotated_image', 10)
        
        self.last_inference_time = 0.0
        self.get_logger().info("ShelfVisionNode V5 đã sẵn sàng hoạt động!")

    def image_callback(self, msg: Image):
        # Tiết kiệm tài nguyên cho CPU/GPU robot: giới hạn tần suất xử lý
        now = time.time()
        if now - self.last_inference_time < self.min_interval:
            return
        self.last_inference_time = now

        try:
            cv_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f"Lỗi chuyển đổi ROS Image sang OpenCV: {e}")
            return

        if self.engine is None:
            return

        # Thực thi nhận diện 2-Stage (YOLO + MobileNetV3 Feature Matching + ArUco + Multi-Tier)
        res = self.engine.analyze_frame(cv_frame)
        res["timestamp"] = int(time.time() * 1000)

        # Xuất payload JSON lên topic /shelf/analysis
        out_msg = String()
        out_msg.data = json.dumps(res, ensure_ascii=False)
        self.pub_analysis.publish(out_msg)

        # Nếu có node đăng ký xem ảnh HUD (RViz / Kiosk UI), xuất ảnh đã vẽ box
        if self.pub_annotated.get_subscription_count() > 0:
            try:
                annotated = self.engine.render_hud_overlay(cv_frame, res)
                img_msg = self.bridge.cv2_to_imgmsg(annotated, encoding='bgr8')
                self.pub_annotated.publish(img_msg)
            except Exception as e:
                self.get_logger().warn(f"Lỗi vẽ ảnh HUD: {e}")

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
