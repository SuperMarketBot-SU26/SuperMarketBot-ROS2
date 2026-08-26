import cv2
import numpy as np

# Sử dụng chuẩn DICT_4X4_50 (4x4 pixels, 50 mã)
# Đây là chuẩn đơn giản nhất, giúp camera dễ dàng nhận diện từ xa.
try:
    # OpenCV 4.7+
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
except AttributeError:
    # Cũ hơn
    aruco_dict = cv2.aruco.Dictionary_get(cv2.aruco.DICT_4X4_50)

# Kích thước ảnh xuất ra (pixels)
img_size = 400

# Tạo mã cho Kệ 1
img_1 = np.zeros((img_size, img_size), dtype=np.uint8)
try:
    # OpenCV 4.7+
    img_1 = cv2.aruco.generateImageMarker(aruco_dict, 1, img_size, img_1, 1)
except AttributeError:
    # Cũ hơn
    img_1 = cv2.aruco.drawMarker(aruco_dict, 1, img_size, img_1, 1)
cv2.imwrite("aruco_ke_1.png", img_1)
print("✅ Đã tạo mã ArUco cho Kệ 1: aruco_ke_1.png")

# Tạo mã cho Kệ 4
img_4 = np.zeros((img_size, img_size), dtype=np.uint8)
try:
    img_4 = cv2.aruco.generateImageMarker(aruco_dict, 4, img_size, img_4, 1)
except AttributeError:
    img_4 = cv2.aruco.drawMarker(aruco_dict, 4, img_size, img_4, 1)
cv2.imwrite("aruco_ke_4.png", img_4)
print("✅ Đã tạo mã ArUco cho Kệ 4: aruco_ke_4.png")

print("\n🎉 Xong! Bạn hãy in 2 file này ra giấy và dán lên kệ tương ứng nhé.")
