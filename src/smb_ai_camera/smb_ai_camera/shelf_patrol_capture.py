#!/usr/bin/env python3
"""
SmartMarketBot — Shelf Patrol & OOS Capture Node (Task #8 & Task #12)
Listens for robot ARRIVED at shelf waypoint -> captures camera frame -> uploads to Backend AI Vision.
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
import cv2
import json
import time
import urllib.request
import urllib.parse
import mimetypes
import uuid
import os

try:
    from cv_bridge import CvBridge
    HAS_CV_BRIDGE = True
except ImportError:
    HAS_CV_BRIDGE = False


class ShelfPatrolCaptureNode(Node):
    def __init__(self):
        super().__init__('shelf_patrol_capture')

        # Parameters
        self.declare_parameter('backend_url', 'http://127.0.0.1:5000')
        self.declare_parameter('robot_code', 'RB001')
        self.declare_parameter('settle_delay_sec', 0.5)

        self.backend_url = self.get_parameter('backend_url').get_parameter_value().string_value.rstrip('/')
        self.robot_code = self.get_parameter('robot_code').get_parameter_value().string_value
        self.settle_delay_sec = self.get_parameter('settle_delay_sec').get_parameter_value().double_value

        self.bridge = CvBridge() if HAS_CV_BRIDGE else None
        self.latest_cv_frame = None
        self._last_processed_arrival_key = None

        # Subscriptions
        self.image_sub = self.create_subscription(Image, '/camera/image_raw', self.image_callback, 10)

        self.get_logger().info(f"📸 Shelf Patrol Capture Node active (Backend: {self.backend_url}, Robot: {self.robot_code})")

    def image_callback(self, msg: Image):
        if self.bridge:
            try:
                self.latest_cv_frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            except Exception as e:
                self.get_logger().debug(f"CvBridge error: {e}")
        else:
            # Parse raw image buffer
            try:
                np_arr = np.frombuffer(msg.data, dtype=np.uint8)
                self.latest_cv_frame = np_arr.reshape((msg.height, msg.width, 3))
            except Exception:
                pass

    def on_robot_arrived(self, mission_id: str, waypoint_index: int, node_id: int, shelf_id: int = 0):
        """Called when robot reaches a shelf waypoint in Patrol flow."""
        arrival_key = f"{mission_id}_{waypoint_index}_{node_id}"
        if self._last_processed_arrival_key == arrival_key:
            return
        self._last_processed_arrival_key = arrival_key

        self.get_logger().info(f"🎯 Robot ARRIVED at Shelf {shelf_id} (Node {node_id}). Settling {self.settle_delay_sec}s for stable capture...")
        time.sleep(self.settle_delay_sec)

        if self.latest_cv_frame is None:
            self.get_logger().error("❌ No camera frame available to capture!")
            return

        # Encode frame to JPEG
        ret, buffer = cv2.imencode('.jpg', self.latest_cv_frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ret:
            self.get_logger().error("❌ JPEG encoding failed!")
            return

        jpg_bytes = buffer.tobytes()
        self.get_logger().info(f"📷 Captured frame ({len(jpg_bytes)} bytes). Uploading to Backend AI Vision...")

        self._upload_shelf_scan(mission_id, waypoint_index, node_id, shelf_id, jpg_bytes)

    def _upload_shelf_scan(self, mission_id: str, waypoint_index: int, node_id: int, shelf_id: int, jpg_bytes: bytes):
        endpoint = f"{self.backend_url}/api/v1/shelf-patrol/analyze-slot"
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"

        body = []
        # Form field: ShelfId
        body.extend([
            f"--{boundary}".encode('utf-8'),
            b'Content-Disposition: form-data; name="ShelfId"',
            b'',
            str(shelf_id).encode('utf-8')
        ])
        # Form field: NodeId
        body.extend([
            f"--{boundary}".encode('utf-8'),
            b'Content-Disposition: form-data; name="NodeId"',
            b'',
            str(node_id).encode('utf-8')
        ])
        # Form field: RobotCode
        body.extend([
            f"--{boundary}".encode('utf-8'),
            b'Content-Disposition: form-data; name="RobotCode"',
            b'',
            self.robot_code.encode('utf-8')
        ])
        # File field: Image
        filename = f"patrol_node_{node_id}_{int(time.time())}.jpg"
        body.extend([
            f"--{boundary}".encode('utf-8'),
            f'Content-Disposition: form-data; name="Image"; filename="{filename}"'.encode('utf-8'),
            b'Content-Type: image/jpeg',
            b'',
            jpg_bytes
        ])
        body.append(f"--{boundary}--".encode('utf-8'))
        body.append(b'')

        payload_bytes = b'\r\n'.join(body)

        req = urllib.request.Request(endpoint, data=payload_bytes, method='POST')
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        req.add_header('ngrok-skip-browser-warning', 'true')

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                resp_data = json.loads(response.read().decode('utf-8'))
                self.get_logger().info(f"✅ Shelf Scan AI Analysis completed: {resp_data}")
        except Exception as e:
            self.get_logger().warn(f"⚠️ Upload to {endpoint} failed ({e}). Retrying locally buffered...")


def main(args=None):
    rclpy.init(args=args)
    node = ShelfPatrolCaptureNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
