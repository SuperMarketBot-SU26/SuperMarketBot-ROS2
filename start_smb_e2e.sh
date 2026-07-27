#!/usr/bin/env bash
# ============================================================================
# start_smb_e2e.sh — Chạy E2E SuperMarketBot chỉ với 1 lệnh
# ----------------------------------------------------------------------------
# Tự động:
#   1. Source ROS2 distro (auto-detect Humble/Lyrical/Kilted/Jazzy)
#   2. Verify ros2 CLI hoạt động
#   3. Verify ESP32 IP có ping được (mặc định 192.168.1.178)
#   4. Khởi 3 process nền (background):
#        - ESP32 ↔ ROS2 bridge (Terminal #1)
#        - rosbridge_server (Terminal #2)
#        - Wait-loop verify topics (thay cho Terminal #3 thủ công)
#   5. Chạy test_robot.sh E2E (nếu tồn tại ~/ros2_ws/test_robot.sh)
#   6. In hướng dẫn mở WebManager
#
# Usage:
#   ./start_smb_e2e.sh                          # dùng IP mặc định 192.168.1.178
#   ./start_smb_e2e.sh 192.168.1.50             # custom ESP IP
#   ESP_IP=192.168.1.50 ./start_smb_e2e.sh      # qua env var
#   ./start_smb_e2e.sh --distro=jazzy           # ép dùng distro cụ thể (vd khi có nhiều distro)
#   ./start_smb_e2e.sh --skip-test              # bỏ chạy test_robot.sh
#   ./start_smb_e2e.sh --no-bridge              # bỏ start ESP32 bridge (debug)
#   ./start_smb_e2e.sh --no-rosbridge           # bỏ start rosbridge (debug)
#
# Stop:
#   ./start_smb_e2e.sh stop                # kill cả 3 process
#   hoặc: kill $(cat /tmp/smb_bridge.pid /tmp/smb_rosbridge.pid)
# ============================================================================

# Lưu ý: KHÔNG dùng `set -euo pipefail` vì:
#   - `set -u` (unbound var): /opt/ros/*/setup.bash có thể tham chiếu biến AMENT_TRACE_SETUP_FILES chưa export → crash
#   - `set -e`: nếu 1 step fail (vd ros2 chưa cài), ta muốn in diagnostic + dừng các step sau thay vì thoát im lặng
# Tuy nhiên ta MUỐN dừng script khi source ROS2 fail (exit code != 0) → dùng explicit `|| exit 1` ở dưới.

# ---------- Config ----------
ESP_IP="${1:-${ESP_IP:-192.168.1.178}}"
ESP_WS_PORT="${ESP_WS_PORT:-81}"
ROSBRIDGE_PORT="${ROSBRIDGE_PORT:-9090}"
ROS_DOMAIN_ID_VALUE="${ROS_DOMAIN_ID:-0}"

# Xử lý CLI flags: --distro=NAME, --skip-test, --no-bridge, --no-rosbridge
SKIP_TEST=false
SKIP_BRIDGE=false
SKIP_ROSBRIDGE=false
ROS_DISTRO_OVERRIDE=""
for arg in "$@"; do
  case "$arg" in
    --distro=*)     ROS_DISTRO_OVERRIDE="${arg#*=}" ;;
    --skip-test)    SKIP_TEST=true ;;
    --no-bridge)    SKIP_BRIDGE=true ;;
    --no-rosbridge) SKIP_ROSBRIDGE=true ;;
  esac
done

# Nếu positional arg đầu tiên không phải IP, có thể là distro cũ positional → bỏ qua (dùng --distro=)
if [[ -n "${ROS_DISTRO_OVERRIDE:-}" ]]; then
  export ROS_DISTRO_OVERRIDE
fi

SMB_HOME_DEFAULT="$HOME/ros2_ws"
SMB_HOME="${SMB_HOME:-$SMB_HOME_DEFAULT}"

BRIDGE_DIR_DEFAULT="$HOME/SuperMarketBot-Android-Robot/SuperMarketBot-IOT/ros2_bridge"
BRIDGE_DIR="${BRIDGE_DIR:-$BRIDGE_DIR_DEFAULT}"

BRIDGE_PID_FILE="/tmp/smb_bridge.pid"
ROSBRIDGE_PID_FILE="/tmp/smb_rosbridge.pid"
LOG_DIR="${HOME}/.smb_logs"
mkdir -p "$LOG_DIR"

# ---------- Banner ----------
print_banner() {
  echo "============================================================"
  echo "  SuperMarketBot E2E Launcher"
  echo "  ESP32 IP   : ${ESP_IP}"
  echo "  ESP32 WS   : ws://${ESP_IP}:${ESP_WS_PORT}"
  echo "  Rosbridge  : ws://0.0.0.0:${ROSBRIDGE_PORT}"
  echo "  Domain ID  : ${ROS_DOMAIN_ID_VALUE}"
  echo "  ros2_ws    : ${SMB_HOME}"
  echo "  bridge dir : ${BRIDGE_DIR}"
  echo "============================================================"
}

# ---------- Stop mode ----------
if [[ "${1:-}" == "stop" ]]; then
  echo "[STOP] Killing SuperMarketBot E2E processes..."
  for pf in "$BRIDGE_PID_FILE" "$ROSBRIDGE_PID_FILE"; do
    if [[ -f "$pf" ]]; then
      pid="$(cat "$pf")"
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" && echo "[STOP] Killed PID $pid ($pf)"
      else
        echo "[STOP] PID $pid ($pf) already dead"
      fi
      rm -f "$pf"
    fi
  done
  # cleanup any stragglers
  pkill -f "esp32_ros2_bridge.py" 2>/dev/null || true
  pkill -f "rosbridge_websocket"   2>/dev/null || true
  exit 0
fi

print_banner

# ---------- 1. Auto-detect ROS2 distro ----------
echo "[1/6] Auto-detecting ROS2 distro..."

# Tìm các distro HỢP LỆ (chỉ nhận distros chính thức)
# Bỏ qua "lyrical", "foxy" (EOL) và các folder lạ
VALID_DISTROS="humble iron jazzy rolling kilted ardent bouncy crystal dashing eloquent foxy galactic geotic humble Hawksbill iron Irwini jazzy Jalisco"
ROSDISTRO_FILE="/etc/rosdistro"

ROS_SETUP=""
ROS_DISTRO=""

# List tất cả setup.bash tìm được
echo "  Found in /opt/ros/:"
for d in /opt/ros/*/setup.bash; do
  if [[ -f "$d" ]]; then
    distro="$(basename "$(dirname "$d")")"
    echo "    - $distro"
  fi
done

# Ưu tiên distro theo biến ROS_DISTRO nếu user export
if [[ -n "${ROS_DISTRO_OVERRIDE:-}" ]] && [[ -f "/opt/ros/${ROS_DISTRO_OVERRIDE}/setup.bash" ]]; then
  ROS_DISTRO="$ROS_DISTRO_OVERRIDE"
  ROS_SETUP="/opt/ros/${ROS_DISTRO}/setup.bash"
else
  # Auto-pick: ưu tiên theo platform Ubuntu
  # Ubuntu 26.04+ → lyrical (chính thức từ May 2026, theo REP 2000)
  # Ubuntu 24.04 → kilted > jazzy > rolling
  # Ubuntu 22.04 → humble (LTS)
  # Ubuntu 20.04 → foxy (EOL)
  for preferred in lyrical kilted jazzy rolling humble iron; do
    if [[ -f "/opt/ros/${preferred}/setup.bash" ]]; then
      ROS_DISTRO="$preferred"
      ROS_SETUP="/opt/ros/${preferred}/setup.bash"
      break
    fi
  done
fi

if [[ -z "$ROS_SETUP" ]]; then
  echo ""
  echo "[ERROR] Không tìm thấy ROS2 distro HỢP LỆ trong /opt/ros/"
  echo "        Cần một trong: lyrical (Ubuntu 26.04+), kilted/jazzy (Ubuntu 24.04), humble (Ubuntu 22.04), rolling"
  echo "        Cài đặt:"
  echo "          Ubuntu 26.04: sudo apt install ros-lyrical-desktop   # chính thức từ May 2026"
  echo "          Ubuntu 24.04: sudo apt install ros-jazzy-desktop    # hoặc ros-kilted-desktop"
  echo "          Ubuntu 22.04: sudo apt install ros-humble-desktop"
  echo ""
  echo "        Nếu bạn đang ở WSL/Docker và cần cài nhanh, dùng:"
  echo "          sudo apt update && sudo apt install -y ros-humble-desktop"
  echo ""
  echo "[FATAL] Không thể tiếp tục. Dừng script."
  exit 1
fi

echo ""
echo "  → Selected: $ROS_DISTRO ($ROS_SETUP)"

# Source với error handling
# Lưu ý: KHÔNG dùng `set -u` ở đây vì setup.bash có thể tham chiếu unbound var
if ! source "$ROS_SETUP" 2>/tmp/smb_source_err.log; then
  echo "[ERROR] Không thể source $ROS_SETUP"
  echo "        Error log:"
  cat /tmp/smb_source_err.log | sed 's/^/          /'
  echo ""
  echo "[FATAL] Dừng script."
  exit 1
fi

export ROS_DOMAIN_ID="$ROS_DOMAIN_ID_VALUE"
echo "[OK]   Sourced $ROS_DISTRO (ROS_DOMAIN_ID=$ROS_DOMAIN_ID)"

# ---------- 2. Verify ros2 CLI ----------
echo "[2/6] Verifying ros2 CLI..."
if ! command -v ros2 >/dev/null 2>&1; then
  echo "[ERROR] 'ros2' không có trong PATH sau khi source $ROS_SETUP"
  echo "        Distro đã source: $ROS_DISTRO"
  echo "        PATH hiện tại: $PATH"
  echo ""
  echo "        Có thể distro $ROS_DISTRO không có 'ros-humble-ros-base' package."
  echo "        Cài bổ sung:"
  echo "          sudo apt install ros-${ROS_DISTRO}-ros-base"
  echo "          sudo apt install ros-${ROS_DISTRO}-rosbridge-server"
  echo ""
  echo "[FATAL] Dừng script."
  exit 1
fi
echo "[OK]   $(ros2 --version 2>&1 | head -n1)"

# ---------- 3. Ping ESP32 ----------
echo "[3/6] Pinging ESP32 (${ESP_IP})..."
if timeout 3 ping -c 1 -W 2 "$ESP_IP" >/dev/null 2>&1; then
  echo "[OK]   ESP32 reachable"
else
  echo "[WARN] ESP32 ${ESP_IP} KHÔNG ping được!"
  echo "        - Đã cắm nguồn + WiFi OK chưa?"
  echo "        - Đã đúng IP chưa? (xem Serial Monitor ESP32 lúc boot)"
  echo "        - Vẫn tiếp tục chạy, có thể ESP32 sẽ reconnect sau..."
fi

# ---------- 4. Cleanup old processes ----------
echo "[4/6] Cleaning up old SMB processes..."
for pf in "$BRIDGE_PID_FILE" "$ROSBRIDGE_PID_FILE"; do
  if [[ -f "$pf" ]]; then
    pid="$(cat "$pf")"
    kill "$pid" 2>/dev/null || true
    rm -f "$pf"
  fi
done
pkill -f "esp32_ros2_bridge.py" 2>/dev/null || true
pkill -f "rosbridge_websocket"   2>/dev/null || true
sleep 1

# ---------- 5. Start ESP32 ↔ ROS2 bridge ----------
echo "[5/6] Starting ESP32 ↔ ROS2 bridge (background)..."
BRIDGE_LOG="$LOG_DIR/smb_bridge.log"
if $SKIP_BRIDGE; then
  echo "[SKIP] --no-bridge flag → bỏ qua"
elif [[ -d "$BRIDGE_DIR" ]]; then
  cd "$BRIDGE_DIR"
  nohup python3 esp32_ros2_bridge.py \
      --ros-args -p esp32_ip:="$ESP_IP" \
      >"$BRIDGE_LOG" 2>&1 &
  echo $! > "$BRIDGE_PID_FILE"
  echo "[OK]   PID $(cat "$BRIDGE_PID_FILE") — log: $BRIDGE_LOG"
else
  echo "[WARN] Không tìm thấy bridge script ở $BRIDGE_DIR — bỏ qua."
  echo "        Đặt script ở: $BRIDGE_DIR/esp32_ros2_bridge.py"
fi

# ---------- 6. Start rosbridge_server ----------
echo "[6/6] Starting rosbridge_server (background)..."
ROSBRIDGE_LOG="$LOG_DIR/smb_rosbridge.log"
if $SKIP_ROSBRIDGE; then
  echo "[SKIP] --no-rosbridge flag → bỏ qua"
else
  nohup ros2 launch rosbridge_server rosbridge_websocket_launch.xml \
      >"$ROSBRIDGE_LOG" 2>&1 &
  echo $! > "$ROSBRIDGE_PID_FILE"
  echo "[OK]   PID $(cat "$ROSBRIDGE_PID_FILE") — log: $ROSBRIDGE_LOG"
fi

# ---------- Wait for topics ----------
echo
echo "[WAIT] Đợi các topic xuất hiện (tối đa 30s)..."
TOPICS_OK=false
for i in $(seq 1 30); do
  if ros2 topic list 2>/dev/null | grep -qE "/scan|/odom"; then
    TOPICS_OK=true
    echo "[OK]   Topics đã sẵn sàng sau ${i}s"
    break
  fi
  sleep 1
done

if ! $TOPICS_OK; then
  echo "[WARN] Topics chưa xuất hiện sau 30s. Check logs:"
  echo "       $BRIDGE_LOG"
  echo "       $ROSBRIDGE_LOG"
fi

# ---------- Show running topics ----------
echo
echo "[TOPICS] Danh sách topic đang hoạt động:"
ros2 topic list 2>/dev/null | sed 's/^/  /' || echo "  (ros2 topic list thất bại)"

echo
echo "[TOPICS] Rate check:"
echo "  /scan:    $(ros2 topic hz /scan    --window 5 2>/dev/null | tail -1 || echo 'N/A')"
echo "  /odom:    $(ros2 topic hz /odom    --window 5 2>/dev/null | tail -1 || echo 'N/A')"
echo "  /battery: $(ros2 topic hz /battery --window 5 2>/dev/null | tail -1 || echo 'N/A')"

# ---------- Run test_robot.sh ----------
echo
if $SKIP_TEST; then
  echo "[TEST] Bỏ qua: --skip-test flag"
elif [[ -x "$SMB_HOME/test_robot.sh" ]]; then
  echo "[TEST] Chạy test_robot.sh..."
  cd "$SMB_HOME" && ./test_robot.sh
  TEST_RC=$?
  if [[ $TEST_RC -eq 0 ]]; then
    echo "[TEST] ✅ test_robot.sh PASSED"
  else
    echo "[TEST] ❌ test_robot.sh FAILED (rc=$TEST_RC) — xem log ở trên"
  fi
else
  echo "[TEST] Bỏ qua: không tìm thấy $SMB_HOME/test_robot.sh (chmod +x để enable)"
fi

# ---------- Final instructions ----------
cat <<EOF

============================================================
  ✅ SuperMarketBot E2E đã khởi động
============================================================

  📡 ESP32 WS     : ws://${ESP_IP}:${ESP_WS_PORT}
  🌉 Rosbridge WS : ws://<ubuntu_ip>:${ROSBRIDGE_PORT}
  📋 Logs:
    - bridge    : ${BRIDGE_LOG}
    - rosbridge : ${ROSBRIDGE_LOG}

  🌐 Bước tiếp theo: Mở WebManager (Chrome)
    - Mở file index.html (SuperMarketBot-Android-Robot/WebManager/)
    - Hoặc truy cập URL đã deploy (vd http://localhost:8080)

  🛑 Dừng hệ thống:
    ./start_smb_e2e.sh stop
    hoặc: kill \$(cat ${BRIDGE_PID_FILE} ${ROSBRIDGE_PID_FILE})

  🔁 Xem log real-time:
    tail -f ${BRIDGE_LOG}
    tail -f ${ROSBRIDGE_LOG}
============================================================
EOF