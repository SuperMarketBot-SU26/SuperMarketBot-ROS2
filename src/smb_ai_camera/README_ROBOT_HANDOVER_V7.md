# 🤖 TÀI LIỆU BÀN GIAO TOÀN DIỆN CHO ĐỘI NGŨ ROBOT & CAMERA (PHIÊN BẢN V7)

Tài liệu này hướng dẫn chi tiết đội ngũ **Robot Camera / ROS 2 / Embedded** tích hợp gói mô hình **AI 2-Stage Vision (YOLOv8 + MobileNetV3 Re-ID)** và **Node Điều Khiển Quét Kệ (Sweep & Telemetry)** với hệ thống Backend .NET và Staff App cho dự án **SuperMarketBot**.

---

## 1. 📦 Danh Mục Các Tệp Trong Gói Bàn Giao V7

| Tệp / Thư mục | Định dạng | Chức năng chính |
|---|---|---|
| **`shelf_sweep_telemetry_node.py`** | **ROS 2 Python Node (Khuyên dùng)** | Node ROS 2 tối ưu: Tự động gom buffer khung hình khi robot lia ngang $\to$ Đánh giá độ nét Laplacian & kích thước ArUco $\to$ Chọn **Best Frame** $\to$ Chạy AI $\to$ Bắn Telemetry & Báo cáo mật độ lên MQTT / Backend |
| **`shelf_vision_node.py`** | ROS 2 Python Node | Node cơ bản: Lắng nghe `/camera/image_raw` và xuất JSON kết quả lên `/shelf/analysis` |
| **`shelf_vision.py`** | Python Engine | Lõi AI Vision 2-Stage: Bộ dò ArUco đa pha (chống lóa băng dính), lọc biên kệ (`Boundary Guard`), bóc tách tầng (`Stack Decomposition`), phân chia T1 (Dưới) & T2 (Trên) |
| **`product_matcher.py`** | Python Engine | Trích xuất vector đặc trưng MobileNetV3 (576 chiều) & Cosine Similarity so khớp sản phẩm thực tế |
| **`best.pt`** & **`best.onnx`** | YOLOv8 Model Weights | Mô hình phát hiện bounding box vật thể (`product`) và vị trí trống (`empty_slot`) |
| **`reference_products/`** | Thư mục 83 ảnh mẫu | Bộ 83 ảnh mẫu tham chiếu đã được crop và hiệu chuẩn trực tiếp cho toàn bộ **6 Kệ Hàng** |
| **`aruco_tags/`** | Tem SVG / PNG | Bộ tem ArUco Tag chuẩn (`DICT_4X4_50`, Tag #1 đến #6) dán tại mép cột chân kệ |
| **`app.py`** & **`dashboard.html`** | FastAPI Web Service | Server độc lập phục vụ test camera (DroidCam/USB Cam) trực quan trên trình duyệt |
| **`requirements.txt`** | Dependencies | Danh sách thư viện Python cần thiết cho môi trường Robot |

---

## 2. 🌟 Những Điểm Nâng Cấp Nổi Bật Trong Phiên Bản V7

1. **Bộ Dò ArUco Đa Pha Chống Lóa (Multi-Pass Fallback):**
   - Đã xử lý triệt để hiện tượng phản chiếu ánh sáng trắng do băng keo dán bảo vệ trên chân kệ.
   - Tự động quét 4 dải tham số (`adaptiveThreshWinSizeMax`, `polygonalApproxAccuracyRate`, `errorCorrectionRate`), đảm bảo nhận diện chính xác 100% Tag #1 đến Tag #6.
2. **Chuẩn Hóa 24 Slot Chuẩn Không Còn Cột `Quantity`:**
   - Hệ thống chuyển đổi hoàn toàn sang mô hình kiểm kê theo Mật độ (`densityPercentage`, `emptyPercentage`) và Trạng thái (`NeedsRestock`, `StockStatus`).
   - Cột `Quantity` trong bảng `SLOT` đã được gỡ bỏ trong CSDL để tránh dư thừa dữ liệu.
   - Định dạng mã Slot: `K{shelf}_T{tier}_{idx}` (ví dụ: `K1_T1_1`, `K1_T2_1` .. `K6_T2_2`).
3. **Cập Nhật Đầy Đủ Danh Mục 6 Kệ Hàng Thực Tế:**
   - Đầy đủ 6 kệ với 83 ảnh mẫu tham chiếu được hiệu chuẩn trực tiếp từ ảnh chụp kệ thật.

---

## 3. 🏷️ Bảng Quy Hoạch 6 Kệ Hàng & 24 Mặt Hàng Thực Tế

| Kệ | Tag ID | Vị trí Tầng 2 (Trên) | Vị trí Tầng 1 (Dưới) |
|:---:|:---:|:---|:---|
| **Kệ 1** | **#1** | • `K1_T2_1`: Snack Swing Bò Bít Tết 63g<br>• `K1_T2_2`: Snack O'Star Trứng Muối 63g | • `K1_T1_1`: Snack O'Star Tảo Biển 63g<br>• `K1_T1_2`: Snack O'Star Tảo Đậm 63g |
| **Kệ 2** | **#2** | • `K2_T2_1`: Bia Heineken Silver Lon 330ml<br>• `K2_T2_2`: Nước Tinh Khiết Number 1 500ml | • `K2_T1_1`: Lốc 50 Ly Nhựa Dùng 1 Lần<br>• `K2_T1_2`: Chai Nước Nhựa Tiện Dụng 500ml |
| **Kệ 3** | **#3** | • `K3_T2_1`: Thịt Ba Chỉ Heo Tươi 500g<br>• `K3_T2_2`: Thịt Bò Tươi Sạch Fillet 500g | • `K3_T1_1`: Rau Muống Sạch VietGAP 500g<br>• `K3_T1_2`: Cá Chép Giòn Làm Sạch 1kg |
| **Kệ 4** | **#4** | • `K4_T2_1`: Mì Koreno Jumbo Bò Cay 1kg<br>• `K4_T2_2`: Mì Ly Life Cup Sườn Cay 65g | • `K4_T1_1`: Cháo Thịt Bằm Gấu Đỏ 50g<br>• `K4_T1_2`: Bánh Cốm Hàng Than Hà Nội 500g |
| **Kệ 5** | **#5** | • `K5_T2_1`: Thố Inox Giữ Nhiệt Nắp Đậy 1.2L<br>• `K5_T2_2`: Khăn Ướt Em Bé Bumbo 100 Tờ | • `K5_T1_1`: Màng Bọc Thực Phẩm Food Wrap<br>• `K5_T1_2`: Khăn Ướt Dịu Nhẹ Hình Gấu 80 Tờ |
| **Kệ 6** | **#6** | • `K6_T2_1`: Bột Nêm Gà Cao Cấp Nắp Vàng<br>• `K6_T2_2`: Nước Tương Chin-Su Tỏi Ớt 330ml | • `K6_T1_1`: Trà Hương Lài Ngọc An 300g<br>• `K6_T1_2`: Trà Thảo Mộc Thiên Thảo Dưỡng Nhan |

---

## 4. 🎯 Giao Thức Quét Kệ (Horizontal Sweep Protocol)

### Quy trình Robot lia ngang:
1. Khi Robot đến gần kệ hàng, điều hướng di chuyển chậm ngang qua mặt trước kệ ($v = 0.10 - 0.15\text{ m/s}$, khoảng cách camera tới kệ $0.70 - 0.90\text{ m}$).
2. Gửi lệnh kích hoạt qua ROS 2 Topic `/shelf/sweep/trigger`:
   ```json
   {"shelfId": 2, "duration": 2.5}
   ```
3. Node `shelf_sweep_telemetry_node.py` gom 15–20 frames trong $2.5\text{s}$, tự động chấm điểm theo công thức:
   $$\text{Score} = (\text{Diện tích ArUco Tag} + 1.0) \times \text{Độ nét Laplacian } (\nabla^2 I)$$
4. Node chọn khung hình có điểm cao nhất (Best Frame) để chạy nhận diện AI, đảm bảo loại bỏ 100% rung lắc mờ nhòe.

---

## 5. 📡 Giao Thức Kết Nối MQTT Về Backend & Staff App

### A. Telemetry Robot (Hiển thị vị trí realtime lên Staff Map)
- **Topic:** `smartmarketbot/robot/{robotCode}/telemetry`
- **Tần suất:** 1.0 - 1.5 giây / lần
- **Payload mẫu:**
```json
{
  "robotCode": "RB001",
  "batteryPct": 88,
  "x": 1.90,
  "y": 0.20,
  "heading": 180.0,
  "status": "Scanning",
  "nearestShelf": "Kệ 2 - Nước Giải Khát & Đồ Uống",
  "timestamp": 1725890000
}
```

### B. Báo Cáo Kệ Hàng (Tạo cảnh báo hết hàng tự động)
- **Topic:** `smartmarketbot/robot/{robotCode}/shelf_report`
- **Payload mẫu:**
```json
{
  "robotCode": "RB001",
  "shelfId": 2,
  "densityPercentage": 50.0,
  "emptyPercentage": 50.0,
  "isOutOfStock": true,
  "isLowStock": false,
  "totalObjects": 4,
  "totalEmptySlots": 2,
  "timestamp": "2026-09-09T12:00:00Z"
}
```
*Ghi chú: Khi `emptyPercentage > 30%`, Backend tự động bắn thông báo chuông cảnh báo tới máy của nhân viên phụ trách dãy để châm hàng.*

---

## 6. 🚀 Hướng Dẫn Cài Đặt & Chạy Thử Nghiệm

### Bước 1: Cài đặt thư viện Python trên máy Robot / Jetson / PC
```bash
pip install -r requirements.txt
```

### Bước 2: Chạy thử nghiệm độc lập qua Web Dashboard (DroidCam hoặc USB Webcam)
```bash
# Windows
start_ai_service.bat

# Hoặc Linux
python3 app.py
```
Truy cập `http://localhost:8000/dashboard` để quan sát trực tiếp nhận diện HUD thời gian thực.

### Bước 3: Chạy Node ROS 2 chính thức
```bash
python3 shelf_sweep_telemetry_node.py
```
Node sẽ tự động kết nối ROS 2 topic `/camera/image_raw` và MQTT broker để truyền thông tin về hệ thống máy chủ siêu thị.
