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
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String
import cv2
import json
import time
import os
import sys
import numpy as np

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
        self.declare_parameter('model_path', 'best.pt')
        self.declare_parameter('conf_threshold', 0.06)
        self.declare_parameter('fps_limit', 5.0)
        
        model_path = self.get_parameter('model_path').get_parameter_value().string_value
        conf_threshold = self.get_parameter('conf_threshold').get_parameter_value().double_value
        self.min_interval = 1.0 / max(1.0, self.get_parameter('fps_limit').get_parameter_value().double_value)
        
        # Load resource directory for ROS 2 package
        try:
            from ament_index_python.packages import get_package_share_directory
            resource_dir = get_package_share_directory('smb_ai_camera')
        except Exception as e:
            self.get_logger().warning(f"Không thể tìm thấy resource directory: {e}")
            resource_dir = None
            
        self.get_logger().info(f"Khởi tạo ShelfVisionEngine V7 (YOLO + MobileNetV3 Re-ID) với model: {model_path}...")
        
        if not HAS_VISION_ENGINE:
            self.get_logger().fatal(f"Không thể nạp ShelfVisionEngine: {IMPORT_ERROR}")
            self.engine = None
        else:
            self.engine = ShelfVisionEngine(model_path=model_path, conf_threshold=conf_threshold, resource_dir=resource_dir)
            self.get_logger().info(f"Đã nạp thành công mô hình với {len(self.engine.matcher.reference_embeddings)} danh mục kệ!")
            
        # Đăng ký Topic
        self.sub_image = self.create_subscription(
            CompressedImage,
            '/camera/image_raw/compressed',
            self.image_callback,
            10
        )
        self.pub_analysis = self.create_publisher(String, '/shelf/analysis', 10)
        self.pub_annotated = self.create_publisher(CompressedImage, '/shelf/annotated_image/compressed', 10)
        
        self.last_inference_time = 0.0
        self.get_logger().info("ShelfVisionNode V5 đã sẵn sàng hoạt động!")

    def image_callback(self, msg: CompressedImage):
        # Tiết kiệm tài nguyên cho CPU/GPU robot: giới hạn tần suất xử lý
        now = time.time()
        if now - self.last_inference_time < self.min_interval:
            return
        self.last_inference_time = now

        try:
            np_arr = np.frombuffer(msg.data, np.uint8)
            cv_frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        except Exception as e:
            self.get_logger().error(f"Lỗi giải nén CompressedImage: {e}")
            return

        if self.engine is None or cv_frame is None:
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
                ret, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ret:
                    img_msg = CompressedImage()
                    img_msg.header = msg.header
                    img_msg.format = "jpeg"
                    img_msg.data = buffer.tobytes()
                    self.pub_annotated.publish(img_msg)
            except Exception as e:
                self.get_logger().warning(f"Lỗi vẽ ảnh HUD: {e}")

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
