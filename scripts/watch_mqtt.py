#!/usr/bin/env python3
"""
watch_mqtt.py — Lắng nghe và hiển thị đẹp mắt các payload MQTT gửi đến / phản hồi từ Robot.
Chạy trực tiếp trên máy:
    python3 /home/nhatkhoa1124/ros2_ws/scripts/watch_mqtt.py
"""

import json
import ssl
import sys
from datetime import datetime
import paho.mqtt.client as mqtt

# Cấu hình EMQX Cloud (Trùng với Backend & Robot)
MQTT_HOST = "l07702d7.ala.asia-southeast1.emqxsl.com"
MQTT_PORT = 8883
MQTT_USER = "Smartmarketbot"
MQTT_PASS = "Passsep490"

TOPICS = [
    ("smartmarketbot/robot/+/command", 1),            # Lệnh từ Backend -> Robot
    ("smartmarketbot/robot/+/navigation_status", 1),  # Phản hồi từ Robot -> Backend
]

# ANSI Colors
C_RESET = "\033[0m"
C_BOLD  = "\033[1m"
C_CYAN  = "\033[36m"
C_GREEN = "\033[32m"
C_YELLOW= "\033[33m"
C_BLUE  = "\033[34m"
C_MAGENTA="\033[35m"
C_RED   = "\033[31m"

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"{C_GREEN}✅ Đã kết nối thành công tới HiveMQ Broker!{C_RESET}")
        print(f"{C_CYAN}📡 Đang lắng nghe các kênh:{C_RESET}")
        for t, q in TOPICS:
            client.subscribe(t, qos=q)
            print(f"   • {t}")
        print(f"{C_YELLOW}Chờ nhận lệnh từ Backend / WebUI... (Nhấn Ctrl+C để thoát){C_RESET}\n" + "-"*75)
    else:
        print(f"{C_RED}❌ Kết nối thất bại, mã lỗi rc = {rc}{C_RESET}")

def on_message(client, userdata, msg):
    now = datetime.now().strftime("%H:%M:%S")
    topic = msg.topic
    raw_payload = msg.payload.decode("utf-8", errors="replace")

    print(f"\n{C_BOLD}{C_BLUE}[{now}] TOPIC: {topic}{C_RESET}")

    try:
        data = json.loads(raw_payload)
    except Exception:
        print(f"Raw payload (không phải JSON): {raw_payload}")
        return

    # Kiểm tra nếu là kênh command (Backend gửi đến Robot)
    if "command" in topic:
        cmd_type = data.get("command", "UNKNOWN")
        ts = data.get("timestamp", "")
        print(f"⚡ {C_BOLD}{C_YELLOW}LỆNH (COMMAND): {cmd_type}{C_RESET} (Gửi lúc: {ts})")

        inner_payload = data.get("payload", {})
        if isinstance(inner_payload, str):
            try:
                inner_payload = json.loads(inner_payload)
            except Exception:
                pass

        if cmd_type == "NAVIGATE_WAYPOINTS" and isinstance(inner_payload, dict):
            mission_id = inner_payload.get("missionId", "N/A")
            waypoints = inner_payload.get("waypoints", [])
            print(f"📋 {C_BOLD}Mission ID:{C_RESET} {mission_id} | Tổng số waypoints: {len(waypoints)}")
            print(f"{'#':<4} {'NodeId':<8} {'Tên Node':<20} {'X (m)':<10} {'Y (m)':<10} {'Role':<8} {'Dwell':<6}")
            print("-" * 70)
            for idx, wp in enumerate(waypoints):
                node_id = str(wp.get("nodeId", "-"))
                name = str(wp.get("name", wp.get("nodeName", f"Node {idx+1}")))
                x = f"{wp.get('x', wp.get('xCoord', 0.0)):.2f}"
                y = f"{wp.get('y', wp.get('yCoord', 0.0)):.2f}"
                role = str(wp.get("role", wp.get("nodeRole", "ad")))
                dwell = str(wp.get("dwellTimeSeconds", wp.get("dwellTime", 0)))
                print(f"{idx+1:<4} {node_id:<8} {name:<20} {x:<10} {y:<10} {role:<8} {dwell:<6}")
        else:
            print(f"{C_CYAN}Nội dung chi tiết (Payload):{C_RESET}")
            print(json.dumps(inner_payload, indent=2, ensure_ascii=False))

    # Kiểm tra nếu là kênh status (Robot phản hồi)
    elif "navigation_status" in topic:
        status = data.get("status", "UNKNOWN")
        wp_idx = data.get("waypointIndex", "-")
        wp_name = data.get("waypointName", "")
        color = C_GREEN if status in ("ARRIVED", "COMPLETED") else (C_RED if status == "ERROR" else C_CYAN)
        print(f"🤖 {C_BOLD}{color}ROBOT TRẠNG THÁI: {status}{C_RESET} (Waypoint #{wp_idx} - {wp_name})")
        print(json.dumps(data, indent=2, ensure_ascii=False))

    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))

    print("-" * 75)

def main():
    client = mqtt.Client(client_id="smb_command_watcher")
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"{C_CYAN}Đang kết nối tới HiveMQ Cloud: {MQTT_HOST}...{C_RESET}")
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_forever()
    except KeyboardInterrupt:
        print(f"\n{C_YELLOW}Đã dừng theo dõi MQTT.{C_RESET}")
    except Exception as e:
        print(f"\n{C_RED}Lỗi kết nối: {e}{C_RESET}")

if __name__ == "__main__":
    main()
