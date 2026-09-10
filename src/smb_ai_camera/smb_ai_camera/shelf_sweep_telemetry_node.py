#!/usr/bin/env python3
"""
ROS 2 Shelf Sweep & Telemetry Node for SuperMarketBot (Phiên bản V7)
Tích hợp:
  1. Horizontal Sweep & Best Frame Selection (Robot lia ngang qua kệ, tự chọn frame nét nhất có ArUco)
  2. 2-Stage AI Vision (YOLO bounding box + MobileNetV3 Re-ID so khớp 24 mặt hàng thực tế trên 6 Kệ hàng)
  3. Multi-Pass ArUco Fallback: Dò tem đa pha chống lóa băng dính chân kệ
  4. Dual Image Support: Nhận cả /camera/image_raw/compressed (Pi IMX500) lẫn /camera/image_raw
  5. Realtime MQTT Telemetry Bridge: Chuẩn hóa khớp 100% với Backend .NET (IncomingRobotPayload) & Staff Map HUD
  6. Closed-Loop Restock Reporting: Chuẩn hóa khớp 100% với Backend (densityPct, stockStatus, timestamp)

Subscriptions:
  - /camera/image_raw/compressed (sensor_msgs/msg/CompressedImage)
  - /camera/image_raw (sensor_msgs/msg/Image)
  - /odom (nav_msgs/msg/Odometry)
  - /battery_state (sensor_msgs/msg/BatteryState)
  - /shelf/sweep/trigger (std_msgs/msg/String) : Lệnh quét (vd: '{"shelfId": 4, "duration": 2.0}')

Publications:
  - /shelf/analysis (std_msgs/msg/String)               : JSON phân tích chi tiết
  - /shelf/annotated_image/compressed (CompressedImage) : Ảnh HUD trực quan nén
  - /shelf/annotated_image (sensor_msgs/msg/Image)      : Ảnh HUD trực quan thô
  - /shelf/density_report (std_msgs/msg/String)        : Báo cáo mật độ cho ROS Bridge
  - /robot/telemetry (std_msgs/msg/String)              : JSON telemetry đồng bộ
"""

import os
import sys
import time
import json
import math
from typing import Optional, Dict, Any, List

# Thêm thư mục hiện tại vào sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import cv2
import numpy as np

# Paho MQTT để kết nối trực tiếp Backend .NET
try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False

# Nạp ShelfVisionEngine lõi
try:
    from shelf_vision import ShelfVisionEngine
    HAS_VISION_ENGINE = True
except ImportError as e:
    HAS_VISION_ENGINE = False
    IMPORT_ERROR = str(e)

# ROS 2 imports
try:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import Image, CompressedImage, BatteryState
    from nav_msgs.msg import Odometry
    from std_msgs.msg import String
    from cv_bridge import CvBridge
    HAS_ROS2 = True
except ImportError:
    HAS_ROS2 = False


class ShelfSweepTelemetryEngine:
    """Xử lý nghiệp vụ Sweep lia ngang và chọn Best Frame độc lập với ROS 2."""
    def __init__(self, vision_engine: Optional[Any] = None):
        self.engine = vision_engine
        self.sweep_active = False
        self.target_shelf_id = 1
        self.sweep_start_time = 0.0
        self.sweep_duration = 2.0
        self.frame_buffer: List[Dict[str, Any]] = []
        # Cooldown giữa các lần auto-sweep cùng 1 kệ (giây)
        self.shelf_cooldowns: Dict[int, float] = {}

    def start_sweep(self, shelf_id: int = 1, duration_sec: float = 2.0):
        self.sweep_active = True
        self.target_shelf_id = shelf_id
        self.sweep_duration = duration_sec
        self.sweep_start_time = time.time()
        self.frame_buffer = []

    def can_auto_sweep(self, shelf_id: int, cooldown_sec: float = 12.0) -> bool:
        """Kiểm tra kệ này đã hết thời gian cooldown kể từ lần quét trước hay chưa."""
        last_time = self.shelf_cooldowns.get(shelf_id, 0.0)
        return (time.time() - last_time) >= cooldown_sec

    def mark_shelf_swept(self, shelf_id: int):
        self.shelf_cooldowns[shelf_id] = time.time()

    def add_frame_to_sweep(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        """Nhận frame khi robot lia ngang, tính điểm nét + ArUco. Trả về kết quả khi hết thời gian sweep."""
        if not self.sweep_active:
            return None

        now = time.time()
        # Tính độ nét Laplacian
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # Kiểm tra diện tích tem ArUco
        tag_detected = False
        tag_area = 0.0
        tag_id = None
        if self.engine is not None:
            tag_id, tag_box = self.engine.detect_aruco(frame)
            if tag_id is not None and tag_box is not None:
                tag_detected = True
                tag_area = float(cv2.contourArea(tag_box))

        # Điểm số Best Frame = (Diện tích Tag + 1.0) * Độ nét
        score = (tag_area + 1.0) * lap_var

        self.frame_buffer.append({
            "frame": frame.copy(),
            "score": score,
            "lap_var": lap_var,
            "tag_id": tag_id,
            "tag_area": tag_area,
            "timestamp": now
        })

        # Kiểm tra nếu đã hết thời lượng quét lia ngang
        if (now - self.sweep_start_time) >= self.sweep_duration:
            self.sweep_active = False
            return self.finalize_sweep()

        return None

    def finalize_sweep(self) -> Dict[str, Any]:
        """Chọn Best Frame có điểm cao nhất và phân tích thị giác 2-Stage."""
        if not self.frame_buffer:
            return {"error": "Không thu thập được frame nào trong chu kỳ quét"}

        # Sắp xếp chọn frame có điểm cao nhất
        self.frame_buffer.sort(key=lambda x: x["score"], reverse=True)
        best_item = self.frame_buffer[0]
        best_frame = best_item["frame"]

        if self.engine is None:
            return {
                "shelfId": self.target_shelf_id,
                "bestScore": best_item["score"],
                "framesCollected": len(self.frame_buffer),
                "error": "Chưa nạp được ShelfVisionEngine"
            }

        # Chạy phân tích thị giác 2-Stage trên Best Frame
        res = self.engine.analyze_frame(best_frame)
        
        # Đảm bảo shelfId chuẩn xác: nếu AI nhận diện được tagId thì ưu tiên tagId
        detected_tag = res.get("arucoTagId")
        final_shelf_id = detected_tag if detected_tag is not None else self.target_shelf_id
        res["shelfId"] = final_shelf_id
        self.mark_shelf_swept(final_shelf_id)

        res["sweepInfo"] = {
            "framesCollected": len(self.frame_buffer),
            "bestFrameScore": round(best_item["score"], 2),
            "bestFrameSharpness": round(best_item["lap_var"], 2),
            "targetShelfId": self.target_shelf_id,
            "detectedTagId": detected_tag
        }
        res["best_frame"] = best_frame
        return res


if HAS_ROS2:
    class ShelfSweepTelemetryNode(Node):
        def __init__(self):
            super().__init__('shelf_sweep_telemetry_node')

            # Khai báo tham số cấu hình
            self.declare_parameter('model_path', 'best.pt')
            self.declare_parameter('conf_threshold', 0.06)
            self.declare_parameter('robot_code', 'RB001')
            self.declare_parameter('mqtt_broker', '127.0.0.1')
            self.declare_parameter('mqtt_port', 1883)
            self.declare_parameter('enable_mqtt', True)
            self.declare_parameter('auto_sweep', False)
            self.declare_parameter('min_tag_area', 600.0)

            model_path = self.get_parameter('model_path').get_parameter_value().string_value
            conf_threshold = self.get_parameter('conf_threshold').get_parameter_value().double_value
            self.robot_code = self.get_parameter('robot_code').get_parameter_value().string_value
            mqtt_broker = self.get_parameter('mqtt_broker').get_parameter_value().string_value
            mqtt_port = self.get_parameter('mqtt_port').get_parameter_value().integer_value
            enable_mqtt = self.get_parameter('enable_mqtt').get_parameter_value().bool_value
            self.auto_sweep_enabled = self.get_parameter('auto_sweep').get_parameter_value().bool_value
            self.min_tag_area = self.get_parameter('min_tag_area').get_parameter_value().double_value

            self.get_logger().info(f"Khởi động ShelfSweepTelemetryNode V7 [Robot: {self.robot_code}]...")

            # Resource directory
            try:
                from ament_index_python.packages import get_package_share_directory
                resource_dir = get_package_share_directory('smb_ai_camera')
            except Exception:
                resource_dir = os.path.join(current_dir, '..', 'resource')
                if not os.path.exists(resource_dir):
                    resource_dir = None

            # Khởi tạo mô hình AI
            if HAS_VISION_ENGINE:
                self.vision_engine = ShelfVisionEngine(
                    model_path=model_path,
                    conf_threshold=conf_threshold,
                    resource_dir=resource_dir
                )
                self.get_logger().info("Đã nạp thành công 2-Stage ShelfVisionEngine!")
            else:
                self.vision_engine = None
                self.get_logger().error(f"Lỗi nạp ShelfVisionEngine: {IMPORT_ERROR}")

            self.sweep_engine = ShelfSweepTelemetryEngine(self.vision_engine)
            self.bridge = CvBridge()

            # Trạng thái Telemetry hiện tại của Robot
            self.telemetry = {
                "robotCode": self.robot_code,
                "batteryPct": 98,
                "x": 0.0,
                "y": 0.0,
                "heading_rad": 0.0,
                "status": "IDLE",
                "nearestShelf": "Khu vực sạc",
                "currentNodeId": None,
                "timestamp": int(time.time())
            }

            # Kết nối MQTT nếu được bật
            self.mqtt_client = None
            if enable_mqtt and HAS_MQTT:
                try:
                    self.mqtt_client = mqtt.Client(client_id=f"{self.robot_code}_sweep_vision")
                    self.mqtt_client.connect(mqtt_broker, mqtt_port, 60)
                    self.mqtt_client.loop_start()
                    self.get_logger().info(f"Đã kết nối MQTT Broker tại {mqtt_broker}:{mqtt_port}")
                except Exception as e:
                    self.get_logger().warning(f"Không thể kết nối MQTT Broker: {e}. Vẫn tiếp tục chạy chế độ ROS 2.")

            # ROS 2 Subscriptions (Hỗ trợ cả CompressedImage và Image thô)
            self.sub_compressed_image = self.create_subscription(
                CompressedImage, '/camera/image_raw/compressed', self.compressed_image_callback, 10)
            self.sub_raw_image = self.create_subscription(
                Image, '/camera/image_raw', self.raw_image_callback, 10)
            self.sub_odom = self.create_subscription(
                Odometry, '/odom', self.odom_callback, 10)
            self.sub_battery = self.create_subscription(
                BatteryState, '/battery_state', self.battery_callback, 10)
            self.sub_trigger = self.create_subscription(
                String, '/shelf/sweep/trigger', self.trigger_callback, 10)

            # ROS 2 Publishers
            self.pub_analysis = self.create_publisher(String, '/shelf/analysis', 10)
            self.pub_density_report = self.create_publisher(String, '/shelf/density_report', 10)
            self.pub_annotated_compressed = self.create_publisher(CompressedImage, '/shelf/annotated_image/compressed', 10)
            self.pub_annotated_raw = self.create_publisher(Image, '/shelf/annotated_image', 10)
            self.pub_telemetry = self.create_publisher(String, '/robot/telemetry', 10)

            # Timer publish telemetry định kỳ 1.5s
            self.timer_telemetry = self.create_timer(1.5, self.publish_telemetry)
            self.get_logger().info("ShelfSweepTelemetryNode V7 đã sẵn sàng!")

        def odom_callback(self, msg: Odometry):
            """Cập nhật tọa độ X, Y và Heading (rad)."""
            self.telemetry["x"] = round(msg.pose.pose.position.x, 2)
            self.telemetry["y"] = round(msg.pose.pose.position.y, 2)

            q = msg.pose.pose.orientation
            siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
            cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
            yaw_rad = math.atan2(siny_cosp, cosy_cosp)
            self.telemetry["heading_rad"] = round(yaw_rad, 4)

        def battery_callback(self, msg: BatteryState):
            """Cập nhật phần trăm pin."""
            if msg.percentage >= 0:
                self.telemetry["batteryPct"] = int(msg.percentage * (100 if msg.percentage <= 1.0 else 1.0))

        def trigger_callback(self, msg: String):
            """Nhận lệnh kích hoạt quét lia ngang từ Navigation / Task Planner."""
            try:
                data = json.loads(msg.data)
                shelf_id = int(data.get("shelfId", 1))
                duration = float(data.get("duration", 2.0))
                self.get_logger().info(f"Nhận lệnh Sweep lia ngang Kệ #{shelf_id} trong {duration}s")
                self.telemetry["status"] = "SCANNING"
                self.telemetry["nearestShelf"] = f"Kệ {shelf_id}"
                self.sweep_engine.start_sweep(shelf_id=shelf_id, duration_sec=duration)
            except Exception as e:
                self.get_logger().error(f"Lỗi cú pháp lệnh trigger: {e}")

        def compressed_image_callback(self, msg: CompressedImage):
            try:
                np_arr = np.frombuffer(msg.data, np.uint8)
                cv_frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if cv_frame is not None:
                    self.process_frame(cv_frame, msg.header)
            except Exception as e:
                self.get_logger().debug(f"Lỗi giải nén CompressedImage: {e}")

        def raw_image_callback(self, msg: Image):
            try:
                cv_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
                if cv_frame is not None:
                    self.process_frame(cv_frame, msg.header)
            except Exception as e:
                self.get_logger().debug(f"Lỗi chuyển đổi Image: {e}")

        def process_frame(self, cv_frame: np.ndarray, header):
            # 1. Nếu đang trong chu kỳ sweep lia ngang
            if self.sweep_engine.sweep_active:
                result = self.sweep_engine.add_frame_to_sweep(cv_frame)
                if result is not None:
                    self.handle_sweep_completed(result, header)
                return

            # 2. Đã tắt Auto-Sweep: không tự động quét khi chỉ nhìn thấy ArUco tag.
            # Chỉ thực hiện sweep khi nhận lệnh trigger thủ công từ FE qua topic /shelf/sweep/trigger.

        def handle_sweep_completed(self, result: Dict[str, Any], header):
            self.telemetry["status"] = "IDLE"
            best_frame = result.pop("best_frame", None)

            shelf_id = int(result.get("shelfId", self.sweep_engine.target_shelf_id))
            density_pct = float(result.get("densityPercentage", result.get("densityPct", 50.0)))
            
            # Tính toán stockStatus theo chuẩn nghiệp vụ
            raw_status = result.get("stockStatus", "Normal")
            if result.get("isOutOfStock", False) or density_pct < 40.0:
                stock_status = "Out of Stock"
            elif result.get("isLowStock", False) or density_pct < 70.0:
                stock_status = "Low Stock"
            else:
                stock_status = raw_status if raw_status in ("Normal", "Low Stock", "Out of Stock") else "Normal"

            now_ms = int(time.time() * 1000)

            # 1. Publish ROS 2 topic /shelf/analysis
            msg = String()
            msg.data = json.dumps(result, ensure_ascii=False)
            self.pub_analysis.publish(msg)
            self.get_logger().info(
                f"Quét hoàn tất: Kệ #{shelf_id} - Mật độ: {round(density_pct, 1)}% ({stock_status})")

            # 2. Publish ROS 2 topic /shelf/density_report (cho ROS Bridge)
            report_data = {
                "shelfId": shelf_id,
                "densityPct": round(density_pct, 1),
                "stockStatus": stock_status,
                "timestamp": now_ms
            }
            d_msg = String()
            d_msg.data = json.dumps(report_data, ensure_ascii=False)
            self.pub_density_report.publish(d_msg)

            # 3. Publish ảnh HUD lên /shelf/annotated_image
            if best_frame is not None and self.vision_engine is not None:
                try:
                    annotated = self.vision_engine.render_hud_overlay(best_frame, result)
                    if self.pub_annotated_compressed.get_subscription_count() > 0:
                        ret, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        if ret:
                            c_msg = CompressedImage()
                            c_msg.header = header
                            c_msg.format = "jpeg"
                            c_msg.data = buffer.tobytes()
                            self.pub_annotated_compressed.publish(c_msg)

                    if self.pub_annotated_raw.get_subscription_count() > 0:
                        self.pub_annotated_raw.publish(self.bridge.cv2_to_imgmsg(annotated, encoding='bgr8'))
                except Exception as e:
                    self.get_logger().debug(f"Lỗi publish HUD: {e}")

            # 4. Publish kết quả lên MQTT topic smartmarketbot/robot/{robotCode}/shelf_report (Khớp 100% BE)
            if self.mqtt_client is not None:
                report_topic = f"smartmarketbot/robot/{self.robot_code}/shelf_report"
                mqtt_payload = {
                    # Các trường bắt buộc cho Backend .NET (MqttClientService.cs:850):
                    "shelfId": shelf_id,
                    "densityPct": round(density_pct, 1),
                    "stockStatus": stock_status,
                    "timestamp": now_ms,
                    # Metadata mở rộng:
                    "robotCode": self.robot_code,
                    "emptyPct": round(max(0.0, 100.0 - density_pct), 1),
                    "totalObjects": result.get("totalObjects", len(result.get("detectedProducts", []))),
                    "totalEmptySlots": result.get("totalEmptySlots", len(result.get("emptySlots", []))),
                    # Tương thích ngược với định dạng cũ:
                    "densityPercentage": round(density_pct, 1),
                    "emptyPercentage": round(max(0.0, 100.0 - density_pct), 1),
                    "isOutOfStock": stock_status == "Out of Stock",
                    "isLowStock": stock_status == "Low Stock"
                }
                # Target canonical DB robotCode (RB0001)
                target_code = "RB0001" if self.robot_code in ("RB001", "RB0001") else self.robot_code
                canonical_topic = f"smartmarketbot/robot/{target_code}/shelf_report"
                mqtt_payload["robotCode"] = target_code
                self.mqtt_client.publish(canonical_topic, json.dumps(mqtt_payload))
                self.get_logger().info(f"Đã bắn báo cáo kệ lên MQTT duy nhất 1 lần: {canonical_topic} -> Mật độ: {round(density_pct, 1)}%")

        def publish_telemetry(self):
            """Publish telemetry định kỳ lên cả ROS 2 và MQTT (Khớp 100% BE & Staff Map)."""
            self.telemetry["timestamp"] = int(time.time())

            # Chuẩn hóa payload theo đúng IncomingRobotPayload của Backend .NET
            telemetry_payload = {
                "Battery": int(self.telemetry.get("batteryPct", 100)),
                "Status": str(self.telemetry.get("status", "IDLE")),
                "XCoord": float(self.telemetry.get("x", 0.0)),
                "YCoord": float(self.telemetry.get("y", 0.0)),
                "HeadingRad": float(self.telemetry.get("heading_rad", 0.0)),
                "CurrentNodeId": self.telemetry.get("currentNodeId", None),
                "Location": self.telemetry.get("nearestShelf", "Khu vực kệ"),
                "IsOnline": True,
                "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                # Tương thích với Staff HUD:
                "robotCode": self.robot_code,
                "batteryPct": int(self.telemetry.get("batteryPct", 100)),
                "x": float(self.telemetry.get("x", 0.0)),
                "y": float(self.telemetry.get("y", 0.0)),
                "heading": round(math.degrees(self.telemetry.get("heading_rad", 0.0)), 1),
                "nearestShelf": self.telemetry.get("nearestShelf", "")
            }

            # ROS 2
            t_msg = String()
            t_msg.data = json.dumps(telemetry_payload, ensure_ascii=False)
            self.pub_telemetry.publish(t_msg)

            # MQTT cho Backend .NET & Staff Map HUD
            if self.mqtt_client is not None:
                telemetry_topic = f"smartmarketbot/robot/{self.robot_code}/telemetry"
                self.mqtt_client.publish(telemetry_topic, t_msg.data)


def main(args=None):
    if not HAS_ROS2:
        print("Môi trường hiện tại không có ROS 2 (rclpy). Chạy demo mô phỏng sweep...")
        engine = ShelfVisionEngine(model_path=os.path.join(current_dir, 'best.pt'))
        sweep = ShelfSweepTelemetryEngine(engine)
        print("Engine Sweep & Telemetry V7 đã sẵn sàng tích hợp!")
        return

    rclpy.init(args=args)
    node = ShelfSweepTelemetryNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.mqtt_client:
            node.mqtt_client.loop_stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
