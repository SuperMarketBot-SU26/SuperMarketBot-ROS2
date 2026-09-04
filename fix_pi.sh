#!/bin/bash
echo "Đang sửa lại Service trên Pi 5 để trỏ về đúng thư mục của user snake..."
ssh -t snake@snake.local "sudo sed -i 's/nhatkhoa1124/snake/g' /etc/systemd/system/robot_agent.service && sudo systemctl daemon-reload && sudo systemctl restart robot_agent.service"
echo "Xong! Bây giờ Pi 5 đã chạy đúng bản code mới nhất trong thư mục của snake!"
