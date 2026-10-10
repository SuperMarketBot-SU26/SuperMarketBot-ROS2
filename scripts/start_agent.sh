#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${WS_DIR}"

# Tự động cấp quyền thực thi cho start_pi5_robot.sh nếu chưa có
chmod +x "${SCRIPT_DIR}/start_pi5_robot.sh"

echo "Khởi động Robot Agent Server ở chế độ nền (port 5000)..."
nohup python3 "${SCRIPT_DIR}/robot_agent_server.py" > agent_server.log 2>&1 &
echo "Xong! Agent đang chạy, bạn có thể điều khiển từ giao diện Web."
