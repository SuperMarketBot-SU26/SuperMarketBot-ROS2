# 🤖 TÀI LIỆU BÀN GIAO MÔ HÌNH AI VISION CHO ĐỘI NGŨ ROBOT & ROS 2 (PHIÊN BẢN V5 - TOÀN DIỆN)

Tài liệu này hướng dẫn đội ngũ **ROS 2 & Robot Navigation / Edge AI** tích hợp và sử dụng toàn diện hệ thống **AI 2-Stage Vision (YOLOv8 Proposal + MobileNetV3 Re-ID Cosine Matching + ArUco Deterministic Tag Locking + Phân Tầng T1/T2)** cho **SuperMarketBot**.

---

## 1. 📦 Danh Sách Tệp Trong Gói Bàn Giao V5

| Tệp / Thư mục | Định dạng | Mục đích sử dụng |
|---|---|---|
| **`best.pt`** | PyTorch Weights (6.2 MB) | Mô hình YOLO đề xuất bounding box hàng hóa (`product`) và khoảng trống (`empty_slot`) |
| **`best.onnx`** | ONNX Model (11.7 MB) | Định dạng ONNX tối ưu cho NPU / TensorRT / OpenVINO / onnxruntime |
| **`shelf_vision.py`** | Python Engine | Bộ xử lý lõi: Lọc biên kệ (`Shelf Boundary Guard`), bóc tách chồng hàng (`Stack Decomposition`), ghép thân chai (`Vertical Fragment Merge`), phân tích 2 tầng (`T1/T2`) |
| **`product_matcher.py`** | Python Engine | Bộ so khớp nhãn hiệu sản phẩm 2-Stage dùng MobileNetV3 trích xuất đặc trưng vector 576 chiều & Cosine Similarity |
| **`reference_products/`** | Thư mục ảnh mẫu (83 ảnh) | Kho ảnh mẫu tham chiếu chuẩn mực cho cả **6 Kệ Hàng (Kệ 1 $\to$ Kệ 6)** |
| **`aruco_tags/`** | Thư mục ảnh tem (SVG/PNG) | Toàn bộ 6 tem ArUco Tag (Dictionary `DICT_4X4_50`, Tag ID: 1 đến 6) dùng để in dán lên cột kệ |
| **`shelf_vision_node.py`** | ROS 2 Python Node | Node chuẩn ROS 2: Subscribe `/camera/image_raw` $\to$ Publish kết quả JSON lên `/shelf/analysis` |
| **`app.py`** & **`dashboard.html`** | FastAPI Microservice | Web Server độc lập cổng 8000: Có Dashboard Web giao diện đồ họa realtime, DroidCam streaming, REST API `/vision/analyze_shelf` |
| **`requirements.txt`** | Dependency file | Danh sách thư viện Python cần cài đặt |

---

## 2. 🏷️ Danh Mục 6 Kệ Hàng & 28 Mặt Hàng SKU Thực Tế

Hệ thống đã nạp sẵn kho tri thức và ảnh mẫu tham chiếu cho toàn bộ 6 danh mục kệ hàng:

| Kệ | Danh Mục | ArUco Tag | Danh Sách Sản Phẩm Thực Tế (SKU Name & ID) |
|:---:|---|:---:|---|
| **Kệ 1** | Đồ Ăn Vặt & Bánh Kẹo Tết | **Tag #1** | `Bánh ChocoPie Orion` (`chocopie`), `Bánh Tét Mini` (`banh_tet`), `Bánh Chưng Mini` (`banh_chung`), `Hũ Đậu Phộng Tinh Nghệ` (`dau_phong`) |
| **Kệ 2** | Nước Giải Khát & Đồ Uống | **Tag #2** | `Bia Heineken Silver` (`heineken`), `Ca Nhựa Uống Nước` (`ca_nhua`), `Bình Nước Giữ Nhiệt` (`binh_nuoc`), `Chai Nước Nhựa` (`chai_nhua`), `Ly Nhựa Dùng 1 Lần` (`ly_nhua`) |
| **Kệ 3** | Thực Phẩm Tươi Sống | **Tag #3** | `Thịt Bò Tươi Sạch` (`thit_bo`), `Thịt Heo Tươi` (`thit_heo`), `Cá Chép Tươi Sống` (`ca_chep`), `Rau Muống Sạch VietGAP` (`rau_muong`) |
| **Kệ 4** | Mì Ăn Liền & Đóng Gói | **Tag #4** | `Mì Koreno Jumbo` (`mi_koreno`), `Cháo Gấu Đỏ` (`chao_gau_do`), `Ly Mì Life Cup` (`ly_mi_life_cup`), `Bánh Cốm Hà Nội` (`banh_com`) |
| **Kệ 5** | Đồ Gia Dụng & Tiện Ích | **Tag #5** | `Khăn Ướt Bumbo` (`khan_uot_bumbo`), `Khăn Ướt Gấu` (`khan_uot_gau`), `Thố Giữ Nhiệt` (`tho_giu_nhiet`), `Màng Bọc Thực Phẩm Food Wrap` (`mang_boc_thuc_pham`) |
| **Kệ 6** | Gia Vị & Trà Siêu Thị | **Tag #6** | `Nước Tương Chin-Su` (`nuoc_tuong_chinsu`), `Nước Tương Maggi` (`nuoc_tuong_maggi`), `Sa Tế Tôm Cay` (`sa_te_cay`), `Muối Ớt Chanh Nha Trang` (`muoi_ot_chanh`), `Dầu Mè Thơm Meizan` (`dau_me_meizan`), `Tiêu Đen Phú Quốc` (`tieu_den_phu_quoc`), `Hũ Muối Ớt Tây Ninh` (`hu_muoi_ot_tay_ninh`), `Hũ Gia Vị Vàng` (`hu_gia_vi_vang`), `Trà Lài Ngọc An` (`tra_ngoc_an`), `Trà Thiên Thảo` (`tra_thien_thao`) |

---

## 3. 🚀 2 Cách Triển Khai Cho Đội Ngũ Robot

### 🔹 CÁCH 1: Chạy trực tiếp dưới dạng ROS 2 Node (Khuyên dùng khi tích hợp vào Robot Launch)

```bash
# 1. Cài đặt môi trường
pip install ultralytics opencv-python cv-bridge torch torchvision

# 2. Khởi chạy node ROS 2
python3 shelf_vision_node.py --ros-args -p model_path:=best.pt -p conf_threshold:=0.06 -p fps_limit:=5.0

# 3. Lắng nghe kết quả phân tích kệ hàng
ros2 topic echo /shelf/analysis
```

* **Subscribed Topic:** `/camera/image_raw` (`sensor_msgs/msg/Image`)
* **Published Topic:** `/shelf/analysis` (`std_msgs/msg/String` - JSON payload)
* **Published HUD Image:** `/shelf/annotated_image` (`sensor_msgs/msg/Image` - Hiển thị lên RViz / màn hình Kiosk)

---

### 🔹 CÁCH 2: Chạy độc lập dưới dạng AI Microservice (REST API + Web Dashboard)

Rất thuận tiện khi Robot chỉ cần chụp ảnh và gọi HTTP POST hoặc cho người vận hành mở giao diện Web kiểm tra:

```bash
# Khởi động Web Server AI Service trên cổng 8000
python app.py
```
- **Web Dashboard trực quan:** Mở trình duyệt `http://<IP_ROBOT>:8000/vision/dashboard` để xem camera vẽ box HUD realtime, trạng thái tồn kho và mật độ từng tầng.
- **REST API Endpoint:** `POST http://<IP_ROBOT>:8000/vision/analyze_shelf` (Gửi multipart form file ảnh, nhận về JSON đầy đủ).

---

## 4. 📋 Cấu Trúc Payload JSON Bàn Giao Cho Backend & MQTT

Khi robot dừng trước kệ hàng và phát hiện nhãn ArUco Tag (hoặc đối sánh sản phẩm), payload JSON sẽ được publish lên MQTT topic `smartmarketbot/robot/{robotCode}/shelf_report`:

```json
{
  "shelfId": 6,
  "shelfCategory": "[TAG #6] Kệ 6 - Gia Vị & Trà",
  "tagDetected": true,
  "arucoTagId": 6,
  "densityPct": 48.6,
  "densityPercentage": 48.6,
  "emptyPercentage": 51.4,
  "stockStatus": "Normal",
  "isOutOfStock": false,
  "isLowStock": false,
  "totalObjects": 10,
  "totalEmptySlots": 4,
  "inferenceTimeMs": 68.5,
  "isMultiTier": true,
  "splitY": 250.0,
  "tier2": {
    "tierId": 2,
    "tierName": "Tầng 2 (Trên)",
    "densityPct": 52.0,
    "stockStatus": "Normal",
    "productCount": 5,
    "emptyCount": 2
  },
  "tier1": {
    "tierId": 1,
    "tierName": "Tầng 1 (Dưới)",
    "densityPct": 45.0,
    "stockStatus": "Normal",
    "productCount": 5,
    "emptyCount": 2
  },
  "detectedProducts": [
    {
      "productId": "nuoc_tuong_chinsu",
      "productName": "Nước Tương Chin-Su",
      "similarity": 0.880,
      "confidence": 0.799,
      "tier": 2,
      "tierName": "Tầng 2 (Trên)",
      "box": [300, 120, 368, 223]
    },
    {
      "productId": "nuoc_tuong_maggi",
      "productName": "Nước Tương Maggi",
      "similarity": 0.926,
      "confidence": 0.789,
      "tier": 2,
      "tierName": "Tầng 2 (Trên)",
      "box": [415, 82, 464, 225]
    }
  ],
  "inventoryCounts": {
    "Nước Tương Chin-Su": 1,
    "Nước Tương Maggi": 1,
    "Sa Tế Tôm Cay": 1,
    "Muối Ớt Chanh Nha Trang": 1,
    "Hũ Gia Vị Vàng": 1,
    "Trà Lài Ngọc An": 1,
    "Trà Thiên Thảo": 1,
    "Dầu Mè Thơm Meizan": 1,
    "Tiêu Đen Phú Quốc": 1,
    "Hũ Muối Ớt Tây Ninh": 1
  },
  "timestamp": 1725350400000
}
```

---

## 5. 🎯 Hướng Dẫn In Tem ArUco Tag

- Tất cả 6 file ảnh tem chuẩn độ nét cao đã được lưu trong thư mục `aruco_tags/`:
  - `tag_1_shelf_1.png` (Kệ 1)
  - `tag_2_shelf_2.png` (Kệ 2)
  - `tag_3_shelf_3.png` (Kệ 3)
  - `tag_4_shelf_4.png` (Kệ 4)
  - `tag_5_shelf_5.png` (Kệ 5)
  - `tag_6_shelf_6.png` (Kệ 6)
- **Kích thước in đề xuất:** In khổ vuông $7 \times 7\text{ cm}$ hoặc $8 \times 8\text{ cm}$, dán lên cột phía bên trái của kệ hàng (ngang tầm quét của camera robot).
