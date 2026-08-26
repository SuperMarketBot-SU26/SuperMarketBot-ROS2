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
import json
import os
try:
    from picamera2 import Picamera2
except ImportError:
    print("❌ ERROR: python3-picamera2 is not installed! Run: sudo apt install python3-picamera2")
    exit(1)
import roslibpy
import numpy as np

print("🔌 Connecting to ROS 2 Docker WebSocket (ws://localhost:9090)...")
ros = roslibpy.Ros(host='localhost', port=9090)
ros.run()

if not ros.is_connected:
    print("❌ Failed to connect to rosbridge. Make sure Docker is running!")
    exit(1)

print("✅ Connected to ROS 2! Initializing IMX500 via picamera2...")
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"size": (640, 360), "format": "RGB888"})
picam2.configure(config)
picam2.start()

image_topic = roslibpy.Topic(ros, '/camera/image_raw/compressed', 'sensor_msgs/msg/CompressedImage', queue_length=1, queue_size=1)
analysis_topic = roslibpy.Topic(ros, '/shelf/analysis', 'std_msgs/msg/String')

# --- HSV Configuration ---
hsv_lower = np.array([0, 50, 50])
hsv_upper = np.array([30, 255, 255])
shelf_id = 4

def update_hsv(msg):
    global hsv_lower, hsv_upper
    try:
        data = json.loads(msg['data'])
        hsv_lower = np.array([data.get('hMin', 0), data.get('sMin', 0), data.get('vMin', 0)])
        hsv_upper = np.array([data.get('hMax', 179), data.get('sMax', 255), data.get('vMax', 255)])
        print(f"🔄 HSV Updated: Min {hsv_lower} -> Max {hsv_upper}")
    except Exception as e:
        print(f"Failed to parse HSV config: {e}")

hsv_topic = roslibpy.Topic(ros, '/shelf/hsv_config', 'std_msgs/msg/String')
hsv_topic.subscribe(update_hsv)

last_inference_time = 0.0

print("🎥 Starting IMX500 Camera Stream (Color Detection Mode) ~15 FPS...")
try:
    while ros.is_connected:
        start_time = time.time()
        
        # Capture from IMX500 (Natively BGR in numpy)
        frame = picam2.capture_array()
        
        # --- OPENCV COLOR DETECTION (Running smoothly at ~15 FPS) ---
        inf_start_t = time.time()
        
        # Convert to HSV
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        # Create mask for Cardboard color
        mask = cv2.inRange(hsv, hsv_lower, hsv_upper)
        
        # Count pixels
        total_pixels = mask.shape[0] * mask.shape[1]
        cardboard_pixels = cv2.countNonZero(mask)
        
        # Density calculation: Cardboard = Empty space
        # So Density = 100 - (Cardboard % )
        # Assume 100% cardboard = 0% density, but realistically we cap it
        empty_ratio = cardboard_pixels / total_pixels
        raw_density_pct = 100.0 - (empty_ratio * 100.0)
        
        density_pct = round(max(0.0, min(100.0, raw_density_pct)), 1)
        empty_pct = round(100.0 - density_pct, 1)
        
        # Stock Status logic
        if density_pct >= 70.0:
            stock_status = "Well Stocked"
        elif density_pct >= 35.0:
            stock_status = "Normal"
        elif density_pct > 10.0:
            stock_status = "Low Stock"
        else:
            stock_status = "Out of Stock"
            
        payload = {
            "shelfId": shelf_id,
            "shelfCategory": "Kệ 4 - Mì Ăn Liền & Đóng Gói (Bìa Carton Mode)",
            "densityPct": density_pct,
            "densityPercentage": density_pct,
            "emptyPercentage": empty_pct,
            "stockStatus": stock_status,
            "isOutOfStock": (stock_status == "Out of Stock"),
            "isLowStock": (stock_status == "Low Stock"),
            "totalObjects": 0,
            "totalEmptySlots": int(empty_ratio * 10), # Fake number for UI based on ratio
            "inferenceTimeMs": round((time.time() - inf_start_t) * 1000, 2),
            "detectedObjects": [],
            "timestamp": int(time.time() * 1000)
        }
        
        # Publish JSON to ROS 2 topic (throttled to 5 Hz to save network)
        if (start_time - last_inference_time) >= 0.2:
            last_inference_time = start_time
            analysis_topic.publish(roslibpy.Message({'data': json.dumps(payload, ensure_ascii=False)}))
        
        # Convert mask to 3 channels so we can stream it directly!
        frame = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

        # --- COMPRESS AND PUBLISH VIDEO STREAM (MASK) ---
        # The frame published will be the black/white mask
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
        
        if ret:
            img_base64 = base64.b64encode(buffer).decode('utf-8')
            msg = {
                'header': {
                    'stamp': {'sec': int(time.time()), 'nanosec': int((time.time() % 1) * 1e9)},
                    'frame_id': 'camera_optical_frame'
                },
                'format': 'jpeg',
                'data': img_base64
            }
            image_topic.publish(roslibpy.Message(msg))
            
        elapsed = time.time() - start_time
        time.sleep(max(0, (1.0 / 15.0) - elapsed))

except KeyboardInterrupt:
    print("\n🛑 Stopping...")
finally:
    picam2.stop()
    image_topic.unadvertise()
    analysis_topic.unadvertise()
    ros.terminate()
