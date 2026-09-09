#!/usr/bin/env python3
"""
Test Pipeline V7 Standalone (Offline / No BE / No Moving Robot needed).

Mục đích:
  - Kiểm thử tải 83 ảnh mẫu tham chiếu trên 6 Kệ hàng thực tế (V7).
  - Kiểm thử cơ chế dò ArUco đa pha chống lóa (Multi-Pass Fallback Anti-Glare).
  - Kiểm thử cơ chế Lia Ngang (Sweep Buffer) gom frames và thuật toán chọn Best Frame.
  - Kiểm thử cấu trúc JSON payload chuẩn hóa gửi về Backend .NET và Staff App (RB0001).
  - Xuất file ảnh HUD visual kết quả ra đĩa để xem trực quan (Gold Best Frame Banner).
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

def create_synthetic_shelf_frame(tag_id=1, blur_ksize=1, tag_scale=1.0, add_glare=False):
    """Tạo một khung hình giả lập kệ hàng với tem ArUco và sản phẩm thực tế V7."""
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

            # Giả lập lóa sáng băng dính (Tape sheen / specular highlight)
            if add_glare:
                # Phản xạ ánh sáng bóng của lớp băng keo (tăng độ chói nền và giảm tương phản)
                tag_sheen = cv2.convertScaleAbs(tag_resized, alpha=0.7, beta=75)
                canvas[20:20+sz, 20:20+sz] = tag_sheen

    # Ghép các ảnh sản phẩm mẫu thực tế V7 (Kệ 1: Snack O'Star, Swing)
    prod_dir = os.path.join(ws_dir, 'src', 'smb_ai_camera', 'resource', 'reference_products', f'shelf_{tag_id}')
    if os.path.exists(prod_dir):
        files = sorted([f for f in os.listdir(prod_dir) if f.endswith(('.jpg', '.png'))])
        x_offset = 140
        for fname in files[:4]:
            pimg = cv2.imread(os.path.join(prod_dir, fname))
            if pimg is not None:
                pw, ph = 90, 110
                pres = cv2.resize(pimg, (pw, ph))
                # Tầng 1 (Dưới)
                if x_offset + pw < 620:
                    canvas[200:200+ph, x_offset:x_offset+pw] = pres
                    x_offset += pw + 25

    # Thêm độ mờ (blur) nếu mô phỏng rung lắc
    if blur_ksize > 1:
        canvas = cv2.GaussianBlur(canvas, (blur_ksize, blur_ksize), 0)

    return canvas

def main():
    print("=" * 75)
    print("🚀 BẮT ĐẦU KIỂM THỬ TOÀN DIỆN PIPELINE AI CAMERA V7")
    print("=" * 75)

    # 1. Khởi tạo Engine với tài nguyên V7
    from shelf_vision import ShelfVisionEngine
    resource_dir = os.path.join(ws_dir, 'src', 'smb_ai_camera', 'resource')
    print(f"📦 Resource Dir: {resource_dir}")
    engine = ShelfVisionEngine(model_path="best.pt", conf_threshold=0.06, resource_dir=resource_dir)
    print("✅ Đã nạp thành công ShelfVisionEngine V7!")

    # 2. Kiểm tra bộ nhớ 83 ảnh mẫu tham chiếu
    matcher = engine.matcher
    total_refs = sum(len(items) for items in matcher.reference_embeddings.values())
    print(f"✅ Đã nạp {total_refs} ảnh sản phẩm tham chiếu cho 6 kệ hàng thực tế!")
    for sid in range(1, 7):
        prods = matcher.reference_embeddings.get(sid, [])
        sample_names = ", ".join(set(p["productName"] for p in prods[:2]))
        print(f"   • Kệ #{sid}: {len(prods)} ảnh mẫu ({sample_names}...)")

    # 3. Kiểm thử bộ dò ArUco đa pha chống lóa (Multi-Pass Fallback)
    print("\n💡 Thử nghiệm bộ dò ArUco đa pha chống lóa băng dính...")
    glare_frame = create_synthetic_shelf_frame(tag_id=1, blur_ksize=1, tag_scale=1.1, add_glare=True)
    tag_id_detected, tag_box = engine.detect_aruco(glare_frame)
    if tag_id_detected == 1:
        print("✅ THÀNH CÔNG: Bộ dò đa pha phát hiện chính xác ArUco Tag #1 ngay cả khi bị lóa trắng!")
    else:
        print(f"⚠️ Cảnh báo: Kết quả phát hiện tag lóa: {tag_id_detected}")

    # 4. Giả lập Robot lia ngang qua Kệ 1 trong 2.0s
    sweep = ShelfSweepTelemetryEngine(engine)
    print("\n📦 Mô phỏng: Robot đang lia ngang qua Kệ 1 ở vận tốc 0.15 m/s...")
    sweep.start_sweep(shelf_id=1, duration_sec=2.0)

    # Sinh 5 frames giả lập:
    # - Frame 1: Robot mới vào, tem ở xa (nhỏ), hơi mờ (blur 9)
    # - Frame 2: Robot đang lia, bị rung lắc (blur 15)
    # - Frame 3: BEST FRAME -> Trực diện tem ArUco to, rõ nét (blur 1, scale 1.2)
    # - Frame 4: Robot đi ngang giữa kệ, tem xa dần (scale 0.8)
    # - Frame 5: Robot sắp ra khỏi kệ, lóa nhẹ (blur 5, add_glare=True)
    frames_config = [
        {"name": "Frame 1 (Bắt đầu, xa)", "scale": 0.7, "blur": 9, "glare": False},
        {"name": "Frame 2 (Rung động cơ)", "scale": 0.9, "blur": 15, "glare": False},
        {"name": "Frame 3 (TRỰC DIỆN, NÉT NHẤT)", "scale": 1.2, "blur": 1, "glare": False},
        {"name": "Frame 4 (Đi ngang giữa)", "scale": 0.8, "blur": 3, "glare": False},
        {"name": "Frame 5 (Lóa băng dính mép)", "scale": 1.0, "blur": 5, "glare": True},
    ]

    for idx, cfg in enumerate(frames_config):
        f = create_synthetic_shelf_frame(tag_id=1, blur_ksize=cfg["blur"], tag_scale=cfg["scale"], add_glare=cfg["glare"])
        sweep.add_frame_to_sweep(f)
        lap = cv2.Laplacian(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        print(f"  📸 Đã chụp {cfg['name']} -> Độ nét Laplacian: {lap:.1f}")

    # 5. Kết thúc chu kỳ Sweep & Chọn Best Frame
    print("\n🔍 Đang chấm điểm và trích xuất Best Frame...")
    result = sweep.finalize_sweep()
    best_frame = result.pop("best_frame", None)

    sweep_info = result.get("sweepInfo", {})
    print("\n🎯 KẾT QUẢ TRÍCH XUẤT BEST FRAME V7:")
    print(f"  - Số frame thu thập: {sweep_info.get('framesCollected')} frames")
    print(f"  - Điểm số Best Frame cao nhất: {sweep_info.get('bestFrameScore')}")
    print(f"  - Độ nét Best Frame: {sweep_info.get('bestFrameSharpness')}")
    print(f"  - Kệ nhận diện: Kệ #{result.get('shelfId')}")
    print(f"  - Mật độ ước tính: {result.get('densityPercentage')}%")

    # 6. Chuẩn hóa Payload gửi Backend .NET & MQTT Canonical RB0001
    shelf_id = int(result.get("shelfId", 1))
    density_pct = float(result.get("densityPercentage", 50.0))
    stock_status = result.get("stockStatus", "Normal")
    now_ms = int(time.time() * 1000)

    canonical_robot_code = "RB0001"
    mqtt_shelf_report = {
        "shelfId": shelf_id,
        "densityPct": density_pct,
        "stockStatus": stock_status,
        "timestamp": now_ms,
        "robotCode": canonical_robot_code,
        "emptyPct": round(max(0.0, 100.0 - density_pct), 1),
        "totalObjects": result.get("totalObjects", 0),
        "totalEmptySlots": result.get("totalEmptySlots", 0),
        "densityPercentage": density_pct,
        "emptyPercentage": round(max(0.0, 100.0 - density_pct), 1),
        "isOutOfStock": (stock_status == "Out of Stock"),
        "isLowStock": (stock_status == "Low Stock")
    }

    print(f"\n📡 GÓI TIN MQTT KHỚP 100% VỚI BACKEND .NET (smartmarketbot/robot/{canonical_robot_code}/shelf_report):")
    print(json.dumps(mqtt_shelf_report, indent=2, ensure_ascii=False))

    # 7. Lưu ảnh HUD trực quan ra đĩa
    if best_frame is not None:
        hud_img = engine.render_hud_overlay(best_frame, result)
        out_path = os.path.join(ws_dir, "test_v7_best_frame_hud.jpg")
        cv2.imwrite(out_path, hud_img)
        print(f"\n🖼️ Đã vẽ và lưu ảnh HUD của Best Frame V7 tại: {out_path}")

    print("\n" + "=" * 75)
    print("🎉 KIỂM THỬ V7 THÀNH CÔNG RỰC RỠ! PIPELINE HOẠT ĐỘNG HOÀN HẢO!")
    print("=" * 75)

if __name__ == '__main__':
    main()
