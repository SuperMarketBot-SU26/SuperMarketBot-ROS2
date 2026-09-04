#!/bin/bash
echo "🚀 Đang tự động kết nối và tắt Agent cũ trên Pi 5..."
ssh -t snake@snake.local "sudo pkill -9 -f start_agent.sh; sudo pkill -9 -f robot_agent_server.py; sudo pkill -9 -f smb.launch.py; sudo pkill -9 -f slam_toolbox; sudo systemctl stop robot_agent.service 2>/dev/null"

echo "📦 Đang đồng bộ TOÀN BỘ code mới sang Pi 5..."
rsync -avz --progress --exclude='build/' --exclude='install/' --exclude='log/' --exclude='.data/' --exclude='.git/' /home/nhatkhoa1124/ros2_ws/ snake@snake.local:~/ros2_ws/

echo "🔥 Đang khởi động lại Agent Server bằng systemd..."
ssh -t snake@snake.local "sudo systemctl daemon-reload && sudo systemctl enable robot_agent.service && sudo systemctl restart robot_agent.service"

echo "✅ HOÀN TẤT! Bây giờ hãy ra Giao diện Web, F5 lại trang và bấm nút AMCL nhé!"
