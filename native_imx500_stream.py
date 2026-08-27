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

try:
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    print("⚠️ WARNING: ultralytics is not installed. AI inference will be disabled. (Run: pip install ultralytics)")
    HAS_YOLO = False

import time
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

# Load AI Model
model_path = os.path.expanduser('~/ros2_ws/ROS2_Vision_Handover_Package/best.pt')
conf_threshold = 0.25
# --- ArUco Setup ---
try:
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    aruco_params = cv2.aruco.DetectorParameters()
    try:
        # OpenCV 4.7+
        aruco_detector = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)
    except AttributeError:
        aruco_detector = None # Fallback to older API
except AttributeError:
    aruco_dict = cv2.aruco.Dictionary_get(cv2.aruco.DICT_4X4_50)
    aruco_params = cv2.aruco.DetectorParameters_create()
    aruco_detector = None

shelf_mapping = {
    1: "Kệ 1 - Nước Giải Khát",
    2: "Kệ 2 - Đồ Hộp",
    3: "Kệ 3 - Gia Vị",
    4: "Kệ 4 - Mì Ăn Liền & Đóng Gói"
}

current_shelf_id = -1
current_shelf_category = "Unknown Shelf (Đưa ArUco vào camera)"

model = None
if HAS_YOLO:
    if os.path.exists(model_path):
        print(f"🧠 Loading YOLO model from {model_path}...")
        model = YOLO(model_path)
    else:
        print(f"⚠️ YOLO model not found at {model_path}. AI disabled.")

last_inference_time = 0.0
cached_objects = []

print("🎥 Starting IMX500 Camera Stream with YOLO & ArUco (~15 FPS)...")
try:
    while ros.is_connected:
        start_time = time.time()
        
        # Capture from IMX500 (Natively BGR in numpy)
        frame = picam2.capture_array()
        
        # --- ARUCO DETECTION (Running every frame) ---
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if aruco_detector is not None:
            corners, ids, rejected = aruco_detector.detectMarkers(gray)
        else:
            corners, ids, rejected = cv2.aruco.detectMarkers(gray, aruco_dict, parameters=aruco_params)
            
        if ids is not None and len(ids) > 0:
            # Update current shelf ID if valid
            detected_id = int(ids.ravel()[0])
            if detected_id in shelf_mapping:
                current_shelf_id = detected_id
                current_shelf_category = shelf_mapping[current_shelf_id]
            # Draw green bounding box around ArUco marker
            cv2.aruco.drawDetectedMarkers(frame, corners, ids, (0, 255, 0))
            # Draw name above marker
            if len(corners) > 0:
                cx = int(corners[0][0][0][0])
                cy = int(corners[0][0][0][1])
                cv2.putText(frame, f"Locked: {current_shelf_category}", (cx, max(10, cy - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        
        # --- AI INFERENCE (Throttled to max 20 FPS to save CPU, but depends on model speed) ---
        if model is not None and (start_time - last_inference_time) >= 0.05:
            last_inference_time = start_time
            inf_start_t = time.time()
            
            # Run YOLO
            results = model(frame, conf=conf_threshold, verbose=False)[0]
            
            # Process payload
            h, w = frame.shape[:2]
            total_frame_area = float(h * w)
            total_bbox_area = 0.0
            detected_objects = []
            
            for box in results.boxes:
                cls_id = int(box.cls[0].item())
                class_name = model.names.get(cls_id, f"obj_{cls_id}")
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
                
            # --- Cross-Class NMS: Remove empty_slot boxes that are significantly overlapped by products ---
            raw_products = [o for o in detected_objects if not o["isEmptySlot"]]
            raw_empties  = [o for o in detected_objects if o["isEmptySlot"]]
            
            def _is_empty_suppressed(empty_box, products):
                empty_area = float((empty_box[2] - empty_box[0]) * (empty_box[3] - empty_box[1]))
                if empty_area <= 0: return True
                total_covered = 0.0
                for prod in products:
                    ix1, iy1 = max(empty_box[0], prod["box"][0]), max(empty_box[1], prod["box"][1])
                    ix2, iy2 = min(empty_box[2], prod["box"][2]), min(empty_box[3], prod["box"][3])
                    if ix2 > ix1 and iy2 > iy1:
                        inter = float((ix2 - ix1) * (iy2 - iy1))
                        if inter / empty_area > 0.60: return True
                        total_covered += inter
                return (total_covered / empty_area) > 0.70
                
            filtered_empties = [e for e in raw_empties if not _is_empty_suppressed(e["box"], raw_products)]
            final_objects = raw_products + filtered_empties
            cached_objects = final_objects # Update the cache so the drawing only draws valid boxes
            
            total_product_area = sum(float((p["box"][2] - p["box"][0]) * (p["box"][3] - p["box"][1])) for p in raw_products)
            total_empty_area = sum(float((e["box"][2] - e["box"][0]) * (e["box"][3] - e["box"][1])) for e in filtered_empties)
            
            if total_product_area + total_empty_area > 0:
                raw_density_pct = (total_product_area / (total_product_area + total_empty_area)) * 100.0
            else:
                raw_density_pct = 0.0
                
            num_products = len(raw_products)
            num_empty = len(filtered_empties)
            
            if num_products == 0:
                density_pct = 0.0
                stock_status = "Out of Stock"
            elif num_products >= 4 and num_empty == 0:
                # If there are many products and no empty slots seen, it's very full
                density_pct = max(80.0, min(100.0, 75.0 + num_products * 2.0))
                stock_status = "Well Stocked"
            else:
                density_pct = round(raw_density_pct, 1)
                if density_pct >= 70.0:
                    stock_status = "Well Stocked"
                elif density_pct >= 40.0:
                    stock_status = "Normal"
                else:
                    stock_status = "Low Stock"
                    
            density_pct = round(density_pct, 1)
                
            inf_time_ms = round((time.time() - inf_start_t) * 1000, 1)
            payload = {
                "shelfId": current_shelf_id,
                "shelfCategory": current_shelf_category,
                "densityPct": density_pct,
                "densityPercentage": density_pct,
                "emptyPercentage": round(max(0.0, 100.0 - density_pct), 1),
                "stockStatus": stock_status,
                "isOutOfStock": (stock_status == "Out of Stock"),
                "isLowStock": (stock_status == "Low Stock"),
                "totalObjects": num_products,
                "totalEmptySlots": num_empty,
                "inferenceTimeMs": round((time.time() - inf_start_t) * 1000, 1),
                "detectedObjects": detected_objects,
                "timestamp": int(time.time() * 1000)
            }
            
            # Publish JSON to ROS 2 topic
            analysis_topic.publish(roslibpy.Message({'data': json.dumps(payload, ensure_ascii=False)}))
        
        # --- DRAW CACHED BOUNDING BOXES ON EVERY FRAME ---
        for obj in cached_objects:
            x1, y1, x2, y2 = obj["box"]
            color = (0, 0, 255) if obj["isEmptySlot"] else (255, 0, 0) # Red for empty, Blue for product
            # Draw box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            # Draw label
            label_text = f"{obj['label']} {obj['confidence']:.2f}"
            cv2.putText(frame, label_text, (x1, max(y1 - 5, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

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
