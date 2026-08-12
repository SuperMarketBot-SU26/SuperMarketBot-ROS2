# Bàn giao xử lý robot đi sai waypoint và map SLAM bị bể

**Ngày cập nhật:** 12/08/2026

**Phạm vi:** `SuperMarketBot-ROS2` + firmware `SuperMarketBot-IOT`

**Trạng thái:** Đã sửa code và kiểm tra tĩnh; chưa hiệu chuẩn/chạy xác nhận trên robot thật.

## 1. Hiện tượng

- Robot không đi đúng waypoint trên map Linux/RViz.
- Khi robot di chuyển hoặc quay, tường bị xoay, tách đôi hoặc chồng lên nhau.
- LaserScan có thể xuất hiện lệch xa so với thân robot.
- Đây thường là lỗi của chuỗi `encoder/IMU -> odometry -> TF -> SLAM`, không phải
  riêng tọa độ waypoint.

## 2. Các nguyên nhân tìm thấy trong repository

### 2.1 Xung đột chân ESP32-S3

Firmware dùng GPIO43/44 cho hai tín hiệu encoder trái/phải. Đây đồng thời là
chân UART0 mặc định của ESP32-S3. Nếu micro-ROS hoặc log chạy bằng `Serial0`,
xung serial có thể làm sai số đếm encoder.

Quyết định hiện tại:

- micro-ROS chạy bằng native USB CDC (`/dev/ttyACM*`);
- không dùng `Serial0` khi encoder còn nối GPIO43/44;
- firmware sẽ báo lỗi compile nếu chưa bật **USB CDC On Boot**.

### 2.2 Odometry đã dùng IMU trước khi vào EKF

Trước đây `/odom` lấy pose nội bộ `g_pose`, trong đó heading đã được MPU6050 hỗ
trợ. Pi lại fuse `/odom` cùng `/imu/data`, khiến cùng một gyro có thể bị tính hai
lần và làm covariance/heading không còn độc lập.

Luồng mới:

```text
Encoder -> /odom (wheel-only) ------+
                                      +-> robot_localization EKF
MPU6050 -> /imu/data (gyro_z only) --+       |
                                             +-> /odometry/filtered
                                             +-> TF odom -> base_link
```

- `/odom` publish `g_wheelOdomPose`, chỉ tích phân encoder.
- `/imu/data` publish angular velocity Z; orientation được đánh dấu không có.
- EKF là node duy nhất publish `odom -> base_link` trên robot thật.
- Nav2 dùng `/odometry/filtered`, không dùng `/odom` thô.

### 2.3 Timestamp odom và IMU

Relay cũ thay stamp của từng message bằng thời điểm callback nhận được. Việc này
làm mất quan hệ thời gian thật giữa odom và IMU.

`unified_relay` hiện:

- giữ nguyên stamp nếu firmware đã đồng bộ epoch với micro-ROS agent;
- nếu firmware dùng thời gian từ lúc boot, áp dụng một offset chung cho cả odom
  và IMU;
- không publish TF; TF thuộc quyền của EKF.

### 2.4 LiDAR bị áp dụng hướng quay nhiều lần

YDLIDAR được nối trực tiếp với Pi 5. Cấu hình hiện tại giữ:

```yaml
reversion: false
inverted: false
```

Góc lắp vật lý chỉ được biểu diễn một lần trong URDF tại fixed joint
`base_link -> laser_frame`. Nếu LaserScan vẫn sai hướng khi robot đứng yên, chỉ
điều chỉnh yaw của joint này; không đồng thời bật lại cả `reversion` và
`inverted`.

## 3. Quyết định resolve conflict `slam_toolbox.yaml`

Conflict khi pull chỉ nằm ở hai tham số:

```text
Remote/upstream:  distance=0.2, angle=0.2
Local/stash:      distance=0.5, angle=1.0
```

Giá trị đã chốt:

```yaml
distance_variance_penalty: 0.5
angle_variance_penalty: 1.0
```

Lý do: robot đang có triệu chứng scan bị xoay mạnh trong khu vực ít đặc trưng.
Giá trị góc cũ `0.0001` gần như không phạt sai lệch quay. `1.0` dùng wheel/IMU
odometry làm prior ngắn hạn mạnh hơn trong giai đoạn phục hồi. Loop closure vẫn
có thể sửa drift dài hạn.

Không giảm hai giá trị này chỉ để map trông “nhạy” hơn trước khi có log audit và
kết quả hiệu chuẩn odometry.

Các tham số liên quan đã chốt cùng lúc:

```yaml
minimum_travel_distance: 0.05
minimum_travel_heading: 0.035
minimum_time_interval: 0.10
link_scan_max_distance: 1.5
correlation_search_space_dimension: 0.5
threads: 2
transform_tolerance: 0.30
scan_queue_size: 5
```

## 4. Tham số phần cứng bắt buộc xác nhận

Hiện firmware đặt:

```text
WHEEL_DIAM_M = 0.065 m
WHEEL_BASE_M = 0.22 m
ENC_PPR      = 960
```

`ENC_PPR=960` chỉ đúng nếu đĩa 20 khe nằm trên trục motor trước hộp số 1:48.
Nếu đĩa nằm trên trục bánh xe, giá trị phải gần `20`.

Repository hiện đọc hai tín hiệu encoder vật lý trái/phải; encoder bánh sau là
alias của bánh trước cùng bên. Nếu robot thực tế có bốn encoder độc lập thì cần
xác nhận lại wiring và dành thêm GPIO trước khi đổi thuật toán.

## 5. Quy trình kiểm tra an toàn trên Pi 5

Luôn có người đứng cạnh E-stop. Không gửi goal/`cmd_vel` trong bước audit.

### Terminal 1 — build và khởi động không Nav2

```bash
docker run -it --rm \
  --name supermarket-bot-ros2 \
  -v ~/ros2_ws:/ros2_ws \
  --network host \
  --privileged \
  supermarket-bot-ros2:latest \
  bash -c "cd /ros2_ws && source /opt/ros/lyrical/setup.bash && ./start_pi5_robot.sh --build --no-nav2"
```

### Terminal 2 — audit robot đứng yên trong 10 giây

```bash
docker exec -it supermarket-bot-ros2 bash
cd /ros2_ws
source /opt/ros/lyrical/setup.bash
source install/setup.bash
bash diagnose_mapping.sh 10
```

Kỳ vọng:

- `/scan`, `/odom`, `/odom_relay`, `/imu/data`, `/imu_relay`: xấp xỉ 50 Hz;
  riêng X3 có thể khoảng 7–10 Hz.
- `/odometry/filtered`: xấp xỉ 30 Hz.
- stamp age dưới 0.5 giây.
- đứng yên 10 giây: odom drift dưới 2 cm và yaw dưới 2 độ.
- gyro Z trung bình gần 0, khuyến nghị tuyệt đối dưới 0.02 rad/s.
- đúng một publisher cho `odom -> base_link`.
- đủ TF `base_link <- laser_frame`, `odom <- base_link`, `map <- odom`.

Nếu audit không đạt thì dừng tại đây, không chạy waypoint.

## 6. Hiệu chuẩn chuyển động vật lý

Chỉ thực hiện sau khi audit đứng yên đạt và khu vực test đã được dọn trống.

1. Nâng bánh khỏi mặt đất, kiểm tra chiều xung và chiều quay hai bên.
2. Đặt xuống sàn, chạy thẳng chậm đúng 1 m; so sánh `/odom` thô.
3. Điều chỉnh `ODOM_CALIB_FACTOR` hoặc `ENC_PPR` cho sai số quãng đường.
4. Quay chậm đúng 360 độ; so sánh yaw `/odom` thô.
5. Điều chỉnh `WHEEL_BASE_M` theo sai số quay.
6. Kiểm tra LaserScan khi đứng yên: vật phía trước phải nằm phía trước
   `base_link` trong RViz.
7. Tạo map mới; không đánh giá bằng map cũ đã bị ghosting.

## 7. Mapping và chạy production

- Giai đoạn tạo map: chạy SLAM Toolbox, tốc độ thấp, tránh quay gấp.
- Khi map đã đạt: lưu map và chuyển sang localization trên saved map.
- Chạy waypoint/production không nên tiếp tục dùng online mapping như nguồn vị
  trí chính, vì loop closure có thể thay đổi hệ tọa độ map trong lúc robot đang
  nhận goal.

## 8. Các file liên quan

### ROS 2

- `src/smb_robot_bringup/config/robot/slam_toolbox.yaml`
- `src/smb_robot_bringup/config/robot/ekf_minimal.yaml`
- `src/smb_robot_bringup/config/robot/ydlidar_x3.yaml`
- `src/smb_robot_bringup/params/nav2_params_robot.yaml`
- `src/smb_robot_bringup/launch/smb_robot.launch.py`
- `src/smb_nodes/smb_nodes/unified_relay.py`
- `src/smb_nodes/smb_nodes/mapping_diagnostics.py`
- `diagnose_mapping.sh`

### ESP32-S3

- `SuperMarketBot-IOT/ESP32-S3/SuperMarketBot-IOT/Config.h`
- `SuperMarketBot-IOT/ESP32-S3/SuperMarketBot-IOT/Odometry.h`
- `SuperMarketBot-IOT/ESP32-S3/SuperMarketBot-IOT/MicroRos.h`
- `SuperMarketBot-IOT/ESP32-S3/SuperMarketBot-IOT/LogStream.h`

## 9. Điều kiện xem là hoàn tất

- Audit đứng yên đạt toàn bộ tiêu chí.
- Test 1 m và 360 độ đã được ghi lại, sai số nằm trong mức đội chấp nhận.
- Scan và robot model trùng hướng trong RViz.
- Map mới không còn tường xoay/chồng sau ít nhất một vòng khép kín.
- Robot đi tới waypoint bằng saved map/localization mà không tạo thêm map mới.
