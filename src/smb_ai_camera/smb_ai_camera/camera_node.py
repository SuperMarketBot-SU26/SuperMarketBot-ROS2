#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray, Detection2D, ObjectHypothesisWithPose
from cv_bridge import CvBridge
import cv2
import numpy as np

class AiCameraNode(Node):
    def __init__(self):
        super().__init__('smb_ai_camera_node')
        
        self.declare_parameter('fps', 30)
        self.declare_parameter('resolution_width', 640)
        self.declare_parameter('resolution_height', 480)
        
        self.image_pub = self.create_publisher(Image, 'camera/image_raw', 10)
        self.detection_pub = self.create_publisher(Detection2DArray, 'camera/detections', 10)
        
        self.bridge = CvBridge()
        
        # Placeholder for Picamera2 setup (must run on Pi OS natively)
        # self.picam2 = Picamera2()
        # ... setup stream and AI models ...
        
        self.timer = self.create_timer(1.0 / self.get_parameter('fps').value, self.timer_callback)
        self.get_logger().info('AI Camera node started (Native OS Mode)')

    def timer_callback(self):
        # Stub for capturing frame and detections
        # In a real scenario, we read from Picamera2's request/metadata
        # frame = self.picam2.capture_array()
        
        # For now, create a dummy black image
        width = self.get_parameter('resolution_width').value
        height = self.get_parameter('resolution_height').value
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        
        # Publish Image
        img_msg = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
        img_msg.header.stamp = self.get_clock().now().to_msg()
        img_msg.header.frame_id = 'camera_link'
        self.image_pub.publish(img_msg)
        
        # Publish Detections (Stub)
        det_array = Detection2DArray()
        det_array.header = img_msg.header
        self.detection_pub.publish(det_array)


def main(args=None):
    rclpy.init(args=args)
    node = AiCameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()

if __name__ == '__main__':
    main()
