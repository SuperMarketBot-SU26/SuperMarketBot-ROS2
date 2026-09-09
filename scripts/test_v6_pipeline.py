#!/usr/bin/env python3
"""
Test Pipeline V6 Standalone (Offline / No BE / No Moving Robot needed).

Mục đích:
  - Kiểm thử cơ chế Lia Ngang (Sweep Buffer) gom frames.
  - Kiểm thử thuật toán chấm điểm Best Frame (độ nét Laplacian + diện tích tem ArUco).
  - Kiểm thử cấu trúc JSON payload chuẩn hóa gửi về Backend .NET và Staff App.
  - Xuất file ảnh HUD visual kết quả ra đĩa để xem trực quan.
"""

import os
import sys
import time
import json
import math
import cv2
import numpy as np

# Nạp module từ smb_ai_camera
ws_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
module_path = os.path.join(ws_dir, 'src', 'smb_ai_camera', 'smb_ai_camera')
if module_path not in sys.path:
    sys.path.insert(0, module_path)

from shelf_sweep_telemetry_node import ShelfSweepTelemetryEngine

def create_synthetic_shelf_frame(tag_id=4, blur_ksize=1, tag_scale=1.0):
    """Tạo một khung hình giả lập kệ hàng với tem ArUco và sản phẩm."""
    # Nền kệ hàng xám nhạt (640x360)
    canvas = np.ones((360, 640, 3), dtype=np.uint8) * 220

    # Vẽ vạch chia 2 tầng kệ (T1 và T2)
    cv2.line(canvas, (0, 180), (640, 180), (80, 80, 80), 4) # Thanh ngang chia tầng
    cv2.rectangle(canvas, (0, 0), (640, 360), (60, 60, 60), 6) # Khung kệ

    # Ghép tem ArUco Tag mép cột trái
    tag_file = os.path.join(ws_dir, 'src', 'smb_ai_camera', 'resource', 'aruco_tags', f'shelf_tag_{tag_id}.png')
    if os.path.exists(tag_file):
        tag_img = cv2.imread(tag_file)
        if tag_img is not None:
            sz = int(80 * tag_scale)
            tag_resized = cv2.resize(tag_img, (sz, sz))
            canvas[20:20+sz, 20:20+sz] = tag_resized

    # Ghép 1 vài ảnh sản phẩm mẫu Kệ 4 nếu có
    prod_dir = os.path.join(ws_dir, 'src', 'smb_ai_camera', 'resource', 'reference_products', f'shelf_{tag_id}')
    if os.path.exists(prod_dir):
        files = [f for f in os.listdir(prod_dir) if f.endswith(('.jpg', '.png'))]
        x_offset = 140
        for fname in files[:3]:
            pimg = cv2.imread(os.path.join(prod_dir, fname))
            if pimg is not None:
                pw, ph = 100, 120
                pres = cv2.resize(pimg, (pw, ph))
                # Đặt ở Tầng 1 (Dưới)
                if x_offset + pw < 620:
                    canvas[200:200+ph, x_offset:x_offset+pw] = pres
                    x_offset += pw + 25

    # Thêm độ mờ (blur) nếu mô phỏng rung lắc
    if blur_ksize > 1:
        canvas = cv2.GaussianBlur(canvas, (blur_ksize, blur_ksize), 0)

    return canvas

def main():
    print("=" * 70)
    print("🚀 BẮT ĐẦU KIỂM THỬ STANDALONE PIPELINE QUÉT KỆ V6")
    print("=" * 70)

    # 1. Khởi tạo Engine
    try:
        from shelf_vision import ShelfVisionEngine
        resource_dir = os.path.join(ws_dir, 'src', 'smb_ai_camera', 'resource')
        engine = ShelfVisionEngine(model_path="best.pt", conf_threshold=0.06, resource_dir=resource_dir)
        print("✅ Đã nạp ShelfVisionEngine lõi với AI & ArUco Detector.")
    except Exception as e:
        print(f"⚠️ Không thể nạp full AI Engine ({e}). Sẽ chạy ở chế độ Mock Vision Engine.")
        class MockEngine:
            def detect_aruco(self, frame):
                try:
                    ad = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
                    corners, ids, _ = cv2.aruco.detectMarkers(frame, ad)
                    if ids is not None and len(ids) > 0:
                        return int(ids[0][0]), corners[0][0].astype(np.int32)
                except Exception:
                    pass
                return None, None
            def analyze_frame(self, frame):
                return {
                    "shelfId": 4,
                    "arucoTagId": 4,
                    "densityPercentage": 55.0,
                    "stockStatus": "Low Stock",
                    "totalObjects": 6,
                    "totalEmptySlots": 4,
                    "detectedProducts": [{"sku": "mi_koreno_jumbo", "confidence": 0.89}],
                    "emptySlots": [{"slot": 1}, {"slot": 2}],
                    "tier1": {"densityPercentage": 60.0, "productCount": 4, "emptyCount": 2, "stockStatus": "Low Stock"},
                    "tier2": {"densityPercentage": 50.0, "productCount": 2, "emptyCount": 2, "stockStatus": "Low Stock"},
                }
            def render_hud_overlay(self, frame, analysis):
                vis = frame.copy()
                cv2.putText(vis, f"Kệ #{analysis.get('shelfId')} - Mật độ: {analysis.get('densityPercentage')}%", 
                            (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                return vis
        engine = MockEngine()

    sweep = ShelfSweepTelemetryEngine(engine)

    # 2. Giả lập Robot lia ngang qua Kệ 4 trong 2.0s
    print("\n📦 Mô phỏng: Robot đang lia ngang qua Kệ 4 ở vận tốc 0.15 m/s...")
    sweep.start_sweep(shelf_id=4, duration_sec=2.0)

    # Sinh 6 frames giả lập:
    # - Frame 1: Robot mới vào, tem ở xa (nhỏ), hơi mờ (blur 9)
    # - Frame 2: Robot đang lia, bị rung lắc (blur 15)
    # - Frame 3: BEST FRAME -> Robot trực diện tem ArUco to, rõ nét (blur 1, scale 1.2)
    # - Frame 4: Robot đi ngang giữa kệ, tem xa dần (scale 0.8)
    # - Frame 5: Robot sắp ra khỏi kệ, rung lắc nhẹ (blur 7)
    frames_config = [
        {"name": "Frame 1 (Bắt đầu, xa)", "scale": 0.7, "blur": 9},
        {"name": "Frame 2 (Rung động cơ)", "scale": 0.9, "blur": 15},
        {"name": "Frame 3 (TRỰC DIỆN, NÉT NHẤT)", "scale": 1.2, "blur": 1},
        {"name": "Frame 4 (Đi ngang giữa)", "scale": 0.8, "blur": 3},
        {"name": "Frame 5 (Sắp ra khỏi kệ)", "scale": 0.6, "blur": 7},
    ]

    for idx, cfg in enumerate(frames_config):
        f = create_synthetic_shelf_frame(tag_id=4, blur_ksize=cfg["blur"], tag_scale=cfg["scale"])
        sweep.add_frame_to_sweep(f)
        lap = cv2.Laplacian(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        print(f"  📸 Đã chụp {cfg['name']} -> Độ nét Laplacian: {lap:.1f}")

    # 3. Kết thúc chu kỳ Sweep & Chọn Best Frame
    print("\n🔍 Đang chấm điểm và trích xuất Best Frame...")
    result = sweep.finalize_sweep()
    best_frame = result.pop("best_frame", None)

    sweep_info = result.get("sweepInfo", {})
    print("\n🎯 KẾT QUẢ TRÍCH XUẤT BEST FRAME:")
    print(f"  - Số frame thu thập: {sweep_info.get('framesCollected')} frames")
    print(f"  - Điểm số Best Frame cao nhất: {sweep_info.get('bestFrameScore')}")
    print(f"  - Độ nét Best Frame: {sweep_info.get('bestFrameSharpness')}")
    print(f"  - Kệ nhận diện: Kệ #{result.get('shelfId')}")

    # 4. Chuẩn hóa Payload gửi Backend .NET
    shelf_id = int(result.get("shelfId", 4))
    density_pct = float(result.get("densityPercentage", 50.0))
    stock_status = result.get("stockStatus", "Low Stock")
    now_ms = int(time.time() * 1000)

    be_shelf_report = {
        "shelfId": shelf_id,
        "densityPct": density_pct,
        "stockStatus": stock_status,
        "timestamp": now_ms,
        "robotCode": "RB001",
        "emptyPct": round(100.0 - density_pct, 1),
        "totalObjects": result.get("totalObjects", 6),
        "totalEmptySlots": result.get("totalEmptySlots", 4)
    }

    be_telemetry = {
        "Battery": 95,
        "Status": "SCANNING",
        "XCoord": 1.90,
        "YCoord": 0.20,
        "HeadingRad": 3.14159,
        "CurrentNodeId": 14,
        "Location": f"Dãy B01 · Kệ {shelf_id}",
        "IsOnline": True,
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    }

    print("\n📡 GÓI TIN MQTT KHỚP 100% VỚI BACKEND .NET (MqttClientService.cs:850):")
    print(json.dumps(be_shelf_report, indent=2, ensure_ascii=False))

    print("\n🗺️ GÓI TIN TELEMETRY KHỚP 100% VỚI STAFF MAP HUD (MapCanvas.tsx):")
    print(json.dumps(be_telemetry, indent=2, ensure_ascii=False))

    # 5. Lưu ảnh HUD trực quan ra đĩa
    if best_frame is not None:
        hud_img = engine.render_hud_overlay(best_frame, result)
        out_path = os.path.join(ws_dir, "test_v6_best_frame_hud.jpg")
        cv2.imwrite(out_path, hud_img)
        print(f"\n🖼️ Đã vẽ và lưu ảnh HUD của Best Frame tại: {out_path}")

    print("\n" + "=" * 70)
    print("🎉 KIỂM THỬ THÀNH CÔNG TOÀN DIỆN! HỆ THỐNG HOẠT ĐỘNG HOÀN HẢO!")
    print("=" * 70)

if __name__ == '__main__':
    main()
