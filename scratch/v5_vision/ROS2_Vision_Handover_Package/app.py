import os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

import base64
import time
import cv2
import numpy as np
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from deepface import DeepFace
    HAS_DEEPFACE = True
except ImportError:
    DeepFace = None
    HAS_DEEPFACE = False
    print("[AI Service] DeepFace not installed. Running in YOLO Vision & Face Mock mode.")

from shelf_vision import ShelfVisionEngine
from droidcam_manager import DroidCamManager

# Initialize YOLO Shelf Vision and DroidCam Manager
shelf_engine = ShelfVisionEngine(model_path="best.pt", conf_threshold=0.06)
droidcam = DroidCamManager(default_source=os.getenv("DROIDCAM_URL", "1"))

# Demo Mode Override: when active, forces density/stock status for demo purposes
demo_override: dict = {"active": False, "mode": None}

@asynccontextmanager
async def lifespan(app: FastAPI):
    if HAS_DEEPFACE:
        print("[AI Service] Warming up DeepFace models (Facenet & OpenCV)...")
        try:
            dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
            DeepFace.represent(
                img_path=dummy_img,
                model_name="Facenet",
                enforce_detection=False,
                detector_backend="opencv"
            )
            print("[AI Service] Warmup completed successfully! Model Facenet is loaded in RAM.")
        except Exception as e:
            print(f"[AI Service] DeepFace Warmup warning: {e}")

    # Start DroidCam capture thread
    droidcam.start()
    yield
    # Shutdown
    droidcam.stop()

app = FastAPI(title="SmartMarketBot AI Vision & Face Service", lifespan=lifespan)

# Mount ArUco static tags directory
tags_dir = os.path.join(os.path.dirname(__file__), "aruco_tags")
if os.path.exists(tags_dir):
    app.mount("/aruco_tags", StaticFiles(directory=tags_dir), name="aruco_tags")

@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "SmartMarketBot AI Vision & Face Service",
        "yolo_active": True,
        "droidcam_connected": droidcam.is_connected,
        "droidcam_source": droidcam.source
    }

# ==========================================
# 1. FACE RECOGNITION ENDPOINTS
# ==========================================
class ImageRequest(BaseModel):
    image_base64: str
    detector_backend: str = "opencv"

def decode_base64_image(image_b64: str) -> np.ndarray:
    try:
        if "," in image_b64:
            image_b64 = image_b64.split(",")[1]
        img_bytes = base64.b64decode(image_b64)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image")
        
        h, w = img.shape[:2]
        max_size = 640
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))
            
        return img
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image data: {str(e)}")

@app.post("/extract-vector")
def extract_vector(request: ImageRequest):
    try:
        if not HAS_DEEPFACE:
            return {
                "status": "success",
                "face_vector": [0.05] * 128
            }

        img = decode_base64_image(request.image_base64)
        representations = DeepFace.represent(
            img_path=img,
            model_name="Facenet",
            enforce_detection=True if request.detector_backend != "skip" else False,
            detector_backend=request.detector_backend
        )
        if not representations:
            return {
                "status": "failed",
                "message": "No face detected in the image",
                "face_vector": []
            }
        
        vector = representations[0]["embedding"]
        return {
            "status": "success",
            "face_vector": vector
        }
    except ValueError as ve:
        return {
            "status": "failed",
            "message": f"No face detected: {str(ve)}",
            "face_vector": []
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/verify")
def verify(request: ImageRequest):
    return {
        "status": "failed",
        "message": "Please use /extract-vector for database matching"
    }

# ==========================================
# 2. YOLO SHELF VISION & DROIDCAM ENDPOINTS
# ==========================================

class DroidCamConfigRequest(BaseModel):
    source: str

@app.post("/vision/droidcam/config")
def set_droidcam_source(req: DroidCamConfigRequest):
    src = req.source.strip()
    droidcam.set_source(src)
    return {
        "status": "success",
        "message": f"DroidCam source updated to: {src}",
        "connected": droidcam.is_connected
    }

@app.get("/vision/droidcam/status")
def get_droidcam_status():
    frame, latest_analysis = droidcam.get_latest_analysis()
    return {
        "connected": droidcam.is_connected,
        "source": droidcam.source,
        "fps": droidcam.fps,
        "latestAnalysis": latest_analysis
    }

@app.post("/vision/analyze")
async def analyze_shelf_image(
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None)
):
    """
    Called by .NET Backend (ShelfScanService) or Client.
    Accepts multipart file or base64 image -> returns YOLO density & shelf classification JSON.
    """
    try:
        img: Optional[np.ndarray] = None
        if file is not None:
            contents = await file.read()
            np_arr = np.frombuffer(contents, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        elif image_base64:
            img = decode_base64_image(image_base64)
        else:
            # Fallback: Capture directly from current DroidCam frame if available
            ret, frame = droidcam.get_latest_frame()
            if ret and frame is not None:
                img = frame
            else:
                raise HTTPException(status_code=400, detail="No image file, image_base64, or active DroidCam stream provided.")

        if img is None:
            raise HTTPException(status_code=400, detail="Unable to decode image.")

        analysis = shelf_engine.analyze_frame(img)
        return analysis

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/vision/droidcam/capture")
def capture_from_droidcam():
    """
    Snapshots the latest live frame from DroidCam, analyzes with YOLO, and returns JSON + annotated base64.
    """
    ret, frame = droidcam.get_latest_frame()
    if not ret or frame is None:
        return {
            "status": "failed",
            "message": "DroidCam is not connected or no frame available.",
            "analysis": None
        }

    analysis = shelf_engine.analyze_frame(frame)
    annotated = shelf_engine.render_hud_overlay(frame, analysis)
    droidcam.update_analysis(annotated, analysis)

    # Encode annotated frame to Base64
    _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
    b64_str = base64.b64encode(buffer).decode('utf-8')

    return {
        "status": "success",
        "analysis": analysis,
        "annotatedImageBase64": f"data:image/jpeg;base64,{b64_str}"
    }

def generate_live_mjpeg():
    """
    Generator streaming continuous annotated JPEG frames from DroidCam with real-time YOLO HUD overlay.
    """
    last_analysis_time = 0
    cached_analysis = {}

    while True:
        ret, frame = droidcam.get_latest_frame()
        if not ret or frame is None:
            # Render a standby frame
            standby = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(standby, "WAITING FOR DROIDCAM STREAM...", (80, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
            cv2.putText(standby, f"Target Source: {droidcam.source}", (80, 280),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
            _, buffer = cv2.imencode('.jpg', standby)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.5)
            continue

        # Run YOLO inference every 100ms (10 FPS inference, 30 FPS video render)
        now = time.time()
        if now - last_analysis_time >= 0.08 or not cached_analysis:
            cached_analysis = shelf_engine.analyze_frame(frame)
            # Apply Demo Override if active
            if demo_override["active"] and demo_override["mode"]:
                cached_analysis = _apply_demo_override(cached_analysis, demo_override["mode"])
            last_analysis_time = now

        annotated = shelf_engine.render_hud_overlay(frame, cached_analysis)
        droidcam.update_analysis(annotated, cached_analysis)

        _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(0.03)

@app.get("/vision/stream")
def get_live_stream():
    return StreamingResponse(
        generate_live_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/vision/dashboard", response_class=HTMLResponse)
def get_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Dashboard file not found</h1>"

@app.get("/aruco/tags", response_class=HTMLResponse)
def get_aruco_tags_page():
    tags_html_path = os.path.join(os.path.dirname(__file__), "aruco_tags", "view_tags.html")
    if os.path.exists(tags_html_path):
        with open(tags_html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>ArUco tags page not found</h1>"

@app.websocket("/ws/shelf-vision-stream")
async def websocket_shelf_stream(websocket: WebSocket):
    """
    WebSocket endpoint for bidirectional real-time video frames from phone camera client.
    """
    await websocket.accept()
    print("[WebSocket] Client connected for Shelf Vision Stream.")
    try:
        while True:
            data = await websocket.receive_text()
            # Expecting base64 image string from client
            if data.startswith("data:image"):
                data = data.split(",")[1]
            img_bytes = base64.b64decode(data)
            np_arr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if frame is not None:
                analysis = shelf_engine.analyze_frame(frame)
                await websocket.send_json(analysis)
    except WebSocketDisconnect:
        print("[WebSocket] Client disconnected.")
    except Exception as e:
        print(f"[WebSocket] Error: {e}")

class CollectDatasetRequest(BaseModel):
    class_name: str
    burst_count: int = 20

@app.post("/vision/dataset/collect")
async def collect_dataset_samples(req: CollectDatasetRequest):
    """
    Captures a burst of images from the active DroidCam stream directly into dataset/raw_images/<class_name>/
    """
    class_name = req.class_name.strip()
    if not class_name:
        raise HTTPException(status_code=400, detail="class_name is required")

    output_dir = os.path.join(os.path.dirname(__file__), "dataset", "raw_images", class_name)
    os.makedirs(output_dir, exist_ok=True)

    saved_files = []
    for i in range(req.burst_count):
        ret, frame = droidcam.get_latest_frame()
        if ret and frame is not None:
            filename = f"{class_name}_{int(time.time()*1000)}_{i}.jpg"
            filepath = os.path.join(output_dir, filename)
            cv2.imwrite(filepath, frame)
            saved_files.append(filename)
            time.sleep(0.08)

    total_in_class = len([f for f in os.listdir(output_dir) if f.endswith(('.jpg', '.png'))])

    return {
        "status": "success",
        "class_name": class_name,
        "captured_count": len(saved_files),
        "total_images_in_class": total_in_class,
        "saved_folder": output_dir
    }

@app.get("/vision/dataset/classes")
def get_dataset_classes():
    from dataset_collector import CLASSES
    return {"classes": CLASSES}

# ==========================================
# 4. DEMO MODE OVERRIDE
# ==========================================
DEMO_PRESETS = {
    "well_stocked": {"densityPct": 92.0, "stockStatus": "Well Stocked", "emptyPercentage": 8.0},
    "normal":       {"densityPct": 55.0, "stockStatus": "Normal",       "emptyPercentage": 45.0},
    "low_stock":    {"densityPct": 22.0, "stockStatus": "Low Stock",    "emptyPercentage": 78.0},
    "out_of_stock": {"densityPct": 0.0,  "stockStatus": "Out of Stock", "emptyPercentage": 100.0},
}

def _apply_demo_override(analysis: dict, mode: str) -> dict:
    preset = DEMO_PRESETS.get(mode)
    if not preset:
        return analysis
    analysis["densityPct"] = preset["densityPct"]
    analysis["densityPercentage"] = preset["densityPct"]
    analysis["emptyPercentage"] = preset["emptyPercentage"]
    analysis["stockStatus"] = preset["stockStatus"]
    analysis["isOutOfStock"] = (preset["stockStatus"] == "Out of Stock")
    analysis["isLowStock"] = (preset["stockStatus"] == "Low Stock")
    analysis["demoMode"] = mode
    return analysis

class DemoOverrideRequest(BaseModel):
    mode: str  # "well_stocked", "normal", "low_stock", "out_of_stock", or "off"

@app.post("/vision/demo/override")
def set_demo_override(req: DemoOverrideRequest):
    mode = req.mode.strip().lower()
    if mode == "off":
        demo_override["active"] = False
        demo_override["mode"] = None
        return {"status": "success", "demoMode": "off", "message": "Demo Mode TẮT — Trở về AI thật"}
    if mode not in DEMO_PRESETS:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Use: {list(DEMO_PRESETS.keys())} or 'off'")
    demo_override["active"] = True
    demo_override["mode"] = mode
    preset = DEMO_PRESETS[mode]
    return {
        "status": "success",
        "demoMode": mode,
        "message": f"Demo Mode BẬT: {preset['stockStatus']} ({preset['densityPct']}%)"
    }

@app.get("/vision/demo/status")
def get_demo_status():
    return {"active": demo_override["active"], "mode": demo_override["mode"]}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
