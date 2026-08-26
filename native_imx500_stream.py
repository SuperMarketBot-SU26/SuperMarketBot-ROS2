#!/usr/bin/env python3
"""
Native IMX500 Camera Streamer for Raspberry Pi 5
Bypasses Docker to access native libcamera/picamera2 hardware.
Connects to the ROS 2 network inside Docker via rosbridge WebSockets.

Requirements (Install on Pi OS natively):
    sudo apt install python3-picamera2 python3-opencv
    pip install roslibpy --break-system-packages
"""

import time
import base64
import cv2
try:
    from picamera2 import Picamera2
except ImportError:
    print("❌ ERROR: python3-picamera2 is not installed! Run: sudo apt install python3-picamera2")
    exit(1)
import roslibpy

print("🔌 Connecting to ROS 2 Docker WebSocket (ws://localhost:9090)...")
# Connects to the rosbridge_server running inside your Docker container
ros = roslibpy.Ros(host='localhost', port=9090)
ros.run()

if not ros.is_connected:
    print("❌ Failed to connect to rosbridge. Make sure Docker is running!")
    exit(1)

print("✅ Connected to ROS 2! Initializing IMX500 via picamera2...")
picam2 = Picamera2()
# Reduced resolution to 640x360 to completely eliminate network/websocket lag for the Web UI
config = picam2.create_preview_configuration(main={"size": (640, 360), "format": "RGB888"})
picam2.configure(config)
picam2.start()

# Set queue_length=1 and queue_size=1 to drop old frames instead of buffering them (fixes the 3-5s delay)
image_topic = roslibpy.Topic(ros, '/camera/image_raw/compressed', 'sensor_msgs/msg/CompressedImage', queue_length=1, queue_size=1)

print("🎥 Starting IMX500 Camera Stream to Web UI (~15 FPS)...")
try:
    while ros.is_connected:
        start_time = time.time()
        
        # Capture from IMX500
        frame = picam2.capture_array()
        
        # Picamera2 with format="RGB888" is likely returning BGR natively when cast to numpy. 
        # By doing no conversion, we avoid swapping Red and Blue.
        
        # Compress to JPEG for Web UI with lower quality to reduce payload size
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        
        if ret:
            # rosbridge_suite expects base64 strings for uint8[] arrays
            img_base64 = base64.b64encode(buffer).decode('utf-8')
            
            msg = {
                'header': {
                    'stamp': {
                        'sec': int(time.time()),
                        'nanosec': int((time.time() % 1) * 1e9)
                    },
                    'frame_id': 'camera_optical_frame'
                },
                'format': 'jpeg',
                'data': img_base64
            }
            image_topic.publish(roslibpy.Message(msg))
            
        # Maintain ~15 FPS
        elapsed = time.time() - start_time
        time.sleep(max(0, (1.0 / 15.0) - elapsed))

except KeyboardInterrupt:
    print("\n🛑 Stopping...")
finally:
    picam2.stop()
    image_topic.unadvertise()
    ros.terminate()
