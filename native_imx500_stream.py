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
import sys

# Thêm đường dẫn tới thư mục chứa code AI V5
ai_module_path = os.path.expanduser('~/ros2_ws/src/smb_ai_camera/smb_ai_camera')
if ai_module_path not in sys.path:
    sys.path.insert(0, ai_module_path)

try:
    from picamera2 import Picamera2
except ImportError:
    print("❌ ERROR: python3-picamera2 is not installed! Run: sudo apt install python3-picamera2")
    exit(1)
import roslibpy

try:
    from shelf_vision import ShelfVisionEngine
    HAS_VISION_ENGINE = True
except ImportError as e:
    print(f"⚠️ WARNING: Could not import ShelfVisionEngine. AI inference will be disabled. Error: {e}")
    HAS_VISION_ENGINE = False

print("🔌 Connecting to ROS 2 Docker WebSocket (ws://localhost:9090)...")
ros = roslibpy.Ros(host='localhost', port=9090)
ros.run()

# Wait up to 10 seconds for rosbridge to start
timeout = 10
start_wait = time.time()
while not ros.is_connected and (time.time() - start_wait) < timeout:
    time.sleep(0.5)

if not ros.is_connected:
    print("❌ Failed to connect to rosbridge after 10s. Exiting so systemd can restart us...")
    exit(1)

print("✅ Connected to ROS 2! Initializing IMX500 via picamera2...")
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"size": (640, 360), "format": "RGB888"})
picam2.configure(config)
picam2.start()

image_topic = roslibpy.Topic(ros, '/camera/image_raw/compressed', 'sensor_msgs/msg/CompressedImage', queue_length=1, queue_size=1)
analysis_topic = roslibpy.Topic(ros, '/shelf/analysis', 'std_msgs/msg/String')

engine = None
if HAS_VISION_ENGINE:
    model_path = os.path.expanduser('~/ros2_ws/src/smb_ai_camera/resource/models/best.pt')
    resource_dir = os.path.expanduser('~/ros2_ws/src/smb_ai_camera/resource')
    print(f"🧠 Loading ShelfVisionEngine V5 with model {model_path}...")
    engine = ShelfVisionEngine(model_path=model_path, conf_threshold=0.25, resource_dir=resource_dir)

last_inference_time = 0.0
cached_payload = None
cached_frame = None

print("🎥 Starting IMX500 Camera Stream with YOLO & ArUco (~15 FPS)...")
try:
    while ros.is_connected:
        start_time = time.time()
        
        # Capture from IMX500 (Natively BGR in numpy)
        frame = picam2.capture_array()
        
        # --- AI INFERENCE (Throttled to max 20 FPS to save CPU, but depends on model speed) ---
        if engine is not None and (start_time - last_inference_time) >= 0.05:
            last_inference_time = start_time
            
            # Analyze frame
            res = engine.analyze_frame(frame)
            res["timestamp"] = int(time.time() * 1000)
            
            # Publish JSON to ROS 2 topic
            analysis_topic.publish(roslibpy.Message({'data': json.dumps(res, ensure_ascii=False)}))
            
            # Update cache for rendering
            cached_payload = res

        # --- DRAW CACHED BOUNDING BOXES ON EVERY FRAME ---
        if engine is not None and cached_payload is not None:
            try:
                frame = engine.render_hud_overlay(frame, cached_payload)
            except Exception as e:
                print(f"HUD render error: {e}")

        # --- COMPRESS AND PUBLISH VIDEO STREAM ---
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
