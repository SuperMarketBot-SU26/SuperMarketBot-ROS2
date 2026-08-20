# SuperMarketBot - Hướng dẫn Tích hợp Raspberry Pi AI Camera

Tài liệu này trình bày chi tiết về tính khả thi, kiến trúc hệ thống và quy trình làm việc nhóm để tích hợp **Raspberry Pi AI Camera (Sony IMX500)** vào hệ thống SuperMarketBot nhằm giải quyết các bài toán nhận diện khuôn mặt và phát hiện khoảng trống kệ hàng (Out-of-Stock).

## 1. Khả năng đáp ứng phần cứng (Độ khả thi cao & Plug-and-Play)
- **Kết nối vật lý**: Raspberry Pi 5 được trang bị hai cổng MIPI CSI-2. Cáp ribbon của AI Camera cắm trực tiếp vào một trong hai cổng này và có thể luồn dễ dàng qua khe hở cáp trên vỏ case công nghiệp của Pi 5 mà không cần adapter hay sửa đổi phần cứng.
- **Tối ưu tài nguyên**: AI Camera tích hợp sẵn chip xử lý NPU (Sony IMX500). Toàn bộ quá trình chạy mô hình AI diễn ra trực tiếp trên camera, giúp giải phóng hoàn toàn CPU của Pi 5. Điều này ngăn ngừa tình trạng quá nhiệt và đảm bảo hệ thống điều hướng ROS 2 của robot luôn hoạt động mượt mà.

## 2. Kiến trúc Phần mềm (Standalone Systemd Service)
**Đề xuất:** Chạy hệ thống AI Camera dưới dạng một **Systemd Application độc lập (viết bằng Python)** thay vì nhúng vào ROS 2.

### Tại sao chọn Systemd thay vì ROS 2?
- **Độ ổn định cao**: Mục đích chính của camera là phân tích dữ liệu kệ hàng và gửi về Backend. Việc tách biệt tiến trình này giúp đảm bảo rằng nếu script xử lý hình ảnh bị lỗi, nó cũng không làm crash hệ thống điều hướng SLAM/AMCL của robot.
- **Tiết kiệm băng thông**: Thay vì truyền video dung lượng lớn qua Wi-Fi của siêu thị, hệ thống dùng thư viện `Picamera2` để trích xuất trực tiếp dữ liệu siêu nhẹ (Metadata như Bounding Box) từ chip IMX500.
- **Đầu ra (Output)**: Script Python sẽ định dạng metadata này thành một chuỗi JSON chuẩn (ví dụ: `{"shelf": 2, "empty_space": "30%", "missing_items": ["Product A"]}`) và gửi về Backend qua giao thức MQTT hoặc HTTP.

## 3. Quy trình làm việc nhóm & Phân chia công việc (Workflow)
Để tránh việc chờ đợi lẫn nhau, quá trình tích hợp được chia thành hai mảng rõ ràng với điểm bàn giao (handoff) cụ thể.

### Vai trò A: Kỹ sư Computer Vision / ML (Làm việc trên PC/GPU)
*Thành viên này chỉ tập trung vào việc huấn luyện và chuyển đổi mô hình.*
1. **Huấn luyện mô hình**: Thu thập dữ liệu kệ hàng và huấn luyện một mô hình nhận diện vật thể nhẹ (khuyến nghị **YOLOv8n** hoặc **YOLO11n**).
2. **Lượng tử hóa & Biên dịch (Bước quan trọng)**: Chip IMX500 không đọc được file `.pt` của PyTorch. Mô hình bắt buộc phải được lượng tử hóa (Quantized) xuống định dạng INT8 bằng bộ công cụ **Model Compression Toolkit (MCT)** và biên dịch bằng **IMX500 Converter** trên PC.
3. **Bàn giao**: Đóng gói thư mục sau khi biên dịch thành file nén (ví dụ: `packerOut.zip`) kèm theo file `labels.txt` (ánh xạ ID sang tên sản phẩm) và chuyển cho Kỹ sư Hardware.

### Vai trò B: Kỹ sư Pi Integration (Làm việc trên Raspberry Pi)
*Bạn tập trung vào tích hợp phần cứng, cài đặt OS driver và giao tiếp với Backend.*
1. **Thiết lập OS**: Lắp đặt camera và cài đặt driver firmware bằng lệnh `sudo apt install imx500-all`.
2. **Đóng gói mô hình**: Nhận file `packerOut.zip` từ đồng đội và chạy lệnh sau trên Pi:
   ```bash
   imx500-package -i packerOut.zip -o output_dir
   ```
   Lệnh này sẽ tạo ra file **`.rpk`** cuối cùng mà firmware của camera yêu cầu.
3. **Xây dựng Data Pipeline**: Viết script Python sử dụng `Picamera2` để tải file `.rpk`, đọc dữ liệu tensor output, chuyển đổi thành JSON và gửi về Server.
4. **Mẹo (Phát triển song song)**: *Không cần chờ mô hình YOLO của đồng đội*. Bạn có thể tải ngay mô hình **MobileNet SSD .rpk** có sẵn của Raspberry Pi để lập trình và kiểm thử toàn bộ luồng gửi JSON/MQTT của mình. Khi đồng đội huấn luyện xong mô hình YOLO, bạn chỉ việc thay file `.rpk` mới vào là hệ thống sẽ chạy ngay lập tức.
