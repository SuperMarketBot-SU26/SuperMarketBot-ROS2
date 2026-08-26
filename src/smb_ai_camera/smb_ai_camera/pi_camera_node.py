#!/usr/bin/env python3
"""
SmartMarketBot — Pi Camera ROS2 Publisher Node (Task #8)
Publish camera frames from Raspberry Pi 5 to /camera/image_raw and /camera/image_raw/compressed.
Supports both V4L2 device (/dev/video0) and Picamera2 hardware pipeline.
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CompressedImage, CameraInfo
import cv2
import numpy as np
import time

try:
    from cv_bridge import CvBridge
    HAS_CV_BRIDGE = True
except ImportError:
    HAS_CV_BRIDGE = False


class PiCameraNode(Node):
    def __init__(self):
        super().__init__('pi_camera_node')

        # Parameters
        self.declare_parameter('device_id', 0)
        self.declare_parameter('width', 1280)
        self.declare_parameter('height', 720)
        self.declare_parameter('fps', 15)
        self.declare_parameter('frame_id', 'camera_optical_frame')
        self.declare_parameter('use_picamera2', False)

        self.device_id = self.get_parameter('device_id').get_parameter_value().integer_value
        self.width = self.get_parameter('width').get_parameter_value().integer_value
        self.height = self.get_parameter('height').get_parameter_value().integer_value
        self.fps = self.get_parameter('fps').get_parameter_value().integer_value
        self.frame_id = self.get_parameter('frame_id').get_parameter_value().string_value
        self.use_picamera2 = self.get_parameter('use_picamera2').get_parameter_value().bool_value

        # Publishers
        self.image_pub = self.create_publisher(Image, '/camera/image_raw', 10)
        self.compressed_pub = self.create_publisher(CompressedImage, '/camera/image_raw/compressed', 10)
        self.info_pub = self.create_publisher(CameraInfo, '/camera/camera_info', 10)

        self.bridge = CvBridge() if HAS_CV_BRIDGE else None

        # Initialize Camera
        self.cap = None
        self.picam2 = None
        self._init_camera()

        timer_period = 1.0 / max(1, self.fps)
        self.timer = self.create_timer(timer_period, self.capture_and_publish)
        self.get_logger().info(f"📷 Pi Camera Node started ({self.width}x{self.height} @ {self.fps} FPS, frame={self.frame_id})")

    def _init_camera(self):
        if self.use_picamera2:
            try:
                from picamera2 import Picamera2
                self.picam2 = Picamera2()
                config = self.picam2.create_preview_configuration(main={"size": (self.width, self.height), "format": "RGB888"})
                self.picam2.configure(config)
                self.picam2.start()
                self.get_logger().info("✅ Picamera2 hardware pipeline initialized successfully.")
                return
            except Exception as e:
                self.get_logger().warning(f"Picamera2 init failed ({e}), falling back to OpenCV V4L2 auto-probing...")

        # OpenCV V4L2 Auto-Probing
        # On Pi 5, /dev/video0 is often a hardware codec, and the actual camera might be video1, video2, or video4.
        # We must verify that cap.read() actually returns a frame.
        devices_to_probe = [self.device_id, 0, 1, 2, 4, 8]
        
        for dev_id in devices_to_probe:
            self.get_logger().info(f"Probing /dev/video{dev_id}...")
            self.cap = cv2.VideoCapture(dev_id, cv2.CAP_V4L2)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)

            if self.cap.isOpened():
                # Verify that it actually returns a frame
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    self.get_logger().info(f"✅ OpenCV VideoCapture found WORKING camera on /dev/video{dev_id}")
                    self.device_id = dev_id
                    return
                else:
                    self.get_logger().warning(f"Device /dev/video{dev_id} opened, but returned no frames.")
            self.cap.release()

        self.cap = None
        self.get_logger().error("❌ Failed to find ANY working video device that returns frames!")

    def capture_and_publish(self):
        frame = None
        if self.picam2:
            try:
                frame = self.picam2.capture_array()
                # Picamera2 RGB -> BGR for OpenCV standard
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            except Exception as e:
                self.get_logger().warning(f"Picamera2 capture error: {e}")
        elif self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if not ret or frame is None:
                return

        if frame is None:
            return

        now = self.get_clock().now().to_msg()

        # 1. Publish Raw Image
        if self.bridge:
            try:
                img_msg = self.bridge.cv2_to_imgmsg(frame, encoding='bgr8')
                img_msg.header.stamp = now
                img_msg.header.frame_id = self.frame_id
                self.image_pub.publish(img_msg)
            except Exception as e:
                self.get_logger().error(f"CvBridge error: {e}")
        else:
            # Pure manual ROS2 Image without cv_bridge
            img_msg = Image()
            img_msg.header.stamp = now
            img_msg.header.frame_id = self.frame_id
            img_msg.height = frame.shape[0]
            img_msg.width = frame.shape[1]
            img_msg.encoding = 'bgr8'
            img_msg.is_bigendian = 0
            img_msg.step = frame.shape[1] * 3
            img_msg.data = frame.tobytes()
            self.image_pub.publish(img_msg)

        # 2. Publish Compressed Image (JPEG for fast web/mobile streaming)
        try:
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            comp_msg = CompressedImage()
            comp_msg.header.stamp = now
            comp_msg.header.frame_id = self.frame_id
            comp_msg.format = 'jpeg'
            comp_msg.data = buffer.tobytes()
            self.compressed_pub.publish(comp_msg)
        except Exception as e:
            self.get_logger().debug(f"Compression error: {e}")

        # 3. Publish Camera Info
        info_msg = CameraInfo()
        info_msg.header.stamp = now
        info_msg.header.frame_id = self.frame_id
        info_msg.width = self.width
        info_msg.height = self.height
        self.info_pub.publish(info_msg)

    def destroy_node(self):
        if self.cap and self.cap.isOpened():
            self.cap.release()
        if self.picam2:
            self.picam2.stop()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PiCameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
