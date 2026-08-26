# 🤖 TÀI LIỆU BÀN GIAO MÔ HÌNH AI VISION CHO ĐỘI NGŨ ROS 2 / RASPBERRY PI

Tài liệu này hướng dẫn đội ngũ **ROS 2 & Raspberry Pi AI Camera (Sony IMX500)** tích hợp mô hình phát hiện sản phẩm và mật độ kệ hàng vào hệ thống robot SuperMarketBot.

---

## 1. 📦 Danh Sách Tệp Trong Gói Bàn Giao

| Tệp | Định dạng | Mục đích sử dụng |
|---|---|---|
| **`best.pt`** | PyTorch Weights | Dành cho môi trường ROS 2 có cài sẵn Python `ultralytics` trên Pi / Laptop |
| **`best.onnx`** | ONNX Model (opset 20) | Dành cho bộ tăng tốc AI (NPU/Sony IMX500) hoặc `onnxruntime` trên Pi |
| **`classes.json`** | JSON Metadata | Bảng ánh xạ ID và Tên class nhận diện |
| **`labels.txt`** | Text file | Danh sách nhãn cho bộ đọc C++/Python |
| **`shelf_vision_node.py`** | ROS 2 Python Node | Mã nguồn ROS 2 Node mẫu nhận topic camera và xuất kết quả mật độ |

---

## 2. 🏷️ Danh Sách Nhãn Nhận Diện (Classes)

| Class ID | Tên Nhãn (`class_name`) | Mô Tả | Kệ Tương Ứng |
|:---:|---|---|:---:|
| **`0`** | `chao_an_lien` | Gói cháo ăn liền Gấu Đỏ | **Kệ 4** (ShelfID: 4) |
| **`1`** | `empty_slot` | Khoảng trống / Vị trí hết hàng trên kệ | Toàn bộ các kệ |
| **`2`** | `ly_mi_life_cup` | Ly mì Life Cup / Cốc mì lẩu thái | **Kệ 4** (ShelfID: 4) |

---

## 3. 📡 Đặc Tả Giao Tiếp ROS 2 (Topics)

### 🔹 Subscribed Topics (Đầu vào từ Robot):
- **`/camera/image_raw`** (`sensor_msgs/msg/Image`): Luồng hình ảnh từ Camera của Robot (RGB/BGR).

### 🔹 Published Topics (Đầu ra):
- **`/shelf/analysis`** (`std_msgs/msg/String`): Chuỗi JSON chứa toàn bộ kết quả phân tích mật độ kệ.
- **`/shelf/annotated_image`** (`sensor_msgs/msg/Image`): *(Tùy chọn)* Khung hình đã được vẽ bounding box để hiển thị lên màn hình Kiosk / RViz.

---

## 4. 📋 Cấu Trúc Payload JSON Bàn Giao Cho Backend & MQTT

Khi robot dừng trước một kệ hàng (ví dụ Kệ 4) và hoàn tất quét, ROS 2 Node / MQTT Publisher sẽ gửi payload JSON theo đúng chuẩn Backend sau:

```json
{
  "shelfId": 4,
  "shelfCategory": "Kệ 4 - Mì Ăn Liền & Đóng Gói",
  "densityPct": 85.5,
  "densityPercentage": 85.5,
  "emptyPercentage": 14.5,
  "stockStatus": "Well Stocked",
  "isOutOfStock": false,
  "isLowStock": false,
  "totalObjects": 6,
  "totalEmptySlots": 0,
  "inferenceTimeMs": 45.2,
  "detectedObjects": [
    {
      "label": "ly_mi_life_cup",
      "confidence": 0.94,
      "box": [120, 80, 260, 320],
      "isEmptySlot": false
    },
    {
      "label": "chao_an_lien",
      "confidence": 0.91,
      "box": [300, 110, 450, 290],
      "isEmptySlot": false
    }
  ],
  "timestamp": 1724654400000
}
```

### Quy ước Trạng thái Kho (`stockStatus`):
- **`Well Stocked`**: Mật độ $\ge 70\%$ (Hàng đầy đủ).
- **`Normal`**: Mật độ từ $35\% \to 69\%$ (Mức bình thường).
- **`Low Stock`**: Mật độ $< 35\%$ hoặc phát hiện $\ge 2$ khoảng trống `empty_slot`.
- **`Out of Stock`**: Không phát hiện sản phẩm nào trên kệ ($0\%$).

---

## 5. 🚀 Hướng Dẫn Chạy Thử ROS 2 Node Trên Robot

```bash
# 1. Cài đặt thư viện phụ trợ trên ROS 2 Workspace
pip install ultralytics opencv-python cv-bridge

# 2. Chạy node vision trực tiếp
python3 shelf_vision_node.py --ros-args -p model_path:=best.pt -p conf_threshold:=0.25 -p shelf_id:=4

# 3. Xem kết quả trả về từ topic
ros2 topic echo /shelf/analysis
```
