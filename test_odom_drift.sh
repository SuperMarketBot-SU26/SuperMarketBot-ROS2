#!/usr/bin/env bash
# test_odom_drift.sh — Monitor odom drift in real-time.
#
# Usage:
#   ./test_odom_drift.sh --sample [N]  # collect N samples, print stats, exit (default N=100)
#   ./test_odom_drift.sh --live        # watch odom in real-time
#   ./test_odom_drift.sh --reset       # reset ESP32 odom counters
#   ./test_odom_drift.sh --plot        # ASCII plot of position over time
#
# What it shows:
#   - position.x from /odom_relay over time (the accumulated linear displacement)
#   - reported vs actual distance for WHEEL_DIAM_M calibration
#
# Calibration workflow:
#   1. ./test_odom_drift.sh --reset
#   2. Drive exactly 5 meters on hard flat floor
#   3. ./test_odom_drift.sh --sample 200
#   4. Note "Final position.x" — that is the reported distance
#   5. Compare: reported_distance vs tape_measure_distance
#      → reported > actual  → WHEEL_DIAM_M too large
#      → reported < actual  → WHEEL_DIAM_M too small
#      → factor = actual_m / reported_m
#      → new WHEEL_DIAM_M = old_diameter * factor

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_DISTRO="${ROS_DISTRO:-lyrical}"

# Source ROS so ros2 run/launch works
source /opt/ros/${ROS_DISTRO}/setup.bash 2>/dev/null || {
    echo "[test_odom_drift] ERROR: failed to source /opt/ros/${ROS_DISTRO}/setup.bash"
    exit 1
}

# Source workspace so local packages are visible
if [[ -f "$SCRIPT_DIR/install/setup.bash" ]]; then
    source "$SCRIPT_DIR/install/setup.bash"
elif [[ -f "$SCRIPT_DIR/../install/setup.bash" ]]; then
    source "$SCRIPT_DIR/../install/setup.bash"
fi

# ---- Parse args -------------------------------------------------------
MODE="${1:-live}"

# ---- Helpers ----------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

header() {
    printf "\n${BOLD}%s${RESET}\n" "$1"
}

die() {
    echo -e "${RED}[ERROR] $1${RESET}" >&2
    exit 1
}

# Check topic exists
check_topic() {
    if ! ros2 topic list 2>/dev/null | grep -q "^${1}$"; then
        die "Topic '${1}' not found. Is the robot running and publishing odom?"
    fi
}

# Reset odom on ESP32
reset_esp32_odom() {
    header "Resetting ESP32 odom counters..."

    # Method 1: ros2 service call (if supervisor exposes a reset service)
    if ros2 service list 2>/dev/null | grep -q 'supervisor/reset_odom'; then
        echo -e "${CYAN}Calling /supervisor/reset_odom service...${RESET}"
        ros2 service call /supervisor/reset_odom std_srvs/srv/Trigger {} 2>/dev/null
        echo -e "${GREEN}Done.${RESET}"
        return 0
    fi

    # Method 2: WebSocket reset (if WebManager is running)
    if command -v wscat >/dev/null 2>&1; then
        echo -e "${CYAN}Sending WebSocket odom reset...${RESET}"
        echo "  (Adjust WebSocket command format to match your WebUI protocol)"
    fi

    # Method 3: manual instruction
    echo -e "${YELLOW}No automated reset found. To reset odom:${RESET}"
    echo "  - Press 'Reset Odom' button in WebUI, OR"
    echo "  - Send via Serial Monitor: odom_reset"
    echo "  - Then re-run this script with --sample or --live"
    return 0
}

# Sample mode: collect N samples, print stats
sample_mode() {
    local N="${2:-100}"
    check_topic "/odom_relay"

    header "Sampling /odom_relay ($N samples)..."
    echo "  Robot should already be at the start position."

    local tmpfile
    tmpfile=$(mktemp)
    trap "rm -f '$tmpfile'" RETURN

    # ros2 topic echo outputs YAML. Extract only pose.pose.position.x
    # by looking for "x:" lines whose previous line contains "position:".
    # This avoids matching orientation.x, twist.linear.x, etc.
    # ros2 topic echo (lyrical) has --once but NOT --num.
    # Use --field to extract just pose.pose.position.x directly.
    # Collect by calling --once in a loop, bounded by a timeout.
    local start_time count=0
    start_time=$(date +%s)
    while true; do
        if [[ $(($(date +%s) - start_time)) -gt 60 ]]; then
            die "Timeout after 60s — collected only $count samples"
        fi
        val=$(ros2 topic echo /odom_relay --field pose.pose.position.x --once 2>/dev/null | tr -d ' ')
        if [[ "$val" =~ ^-?[0-9]+\.?[0-9]*$ ]]; then
            echo "$val" >> "$tmpfile"
            count=$((count + 1))
        fi
        [[ $count -ge $N ]] && break
        sleep 0.05
    done

    if [[ ! -s "$tmpfile" ]]; then
        die "No data collected from /odom_relay. Is the robot publishing?"
    fi

    local count
    count=$(wc -l < "$tmpfile")
    echo -e "${GREEN}Collected $count samples.${RESET}"
    echo ""

    # Compute stats with awk
    awk '
    BEGIN {
        min=1e9; max=-1e9; sum=0
    }
    {
        if ($1 != "" && $1+0 == $1) {
            if ($1 < min) min = $1
            if ($1 > max) max = $1
            sum += $1; n++
        }
    }
    END {
        if (n == 0) { print "  No numeric data found in samples."; exit 1 }
        mean = sum / n

        printf "  Position X (m):  min=%+.4f  max=%+.4f  mean=%+.4f\n", min, max, mean
        printf "\n  Final position.x (reported distance) = %.4f m\n", max

        printf "\n  To calibrate WHEEL_DIAM_M:\n"
        printf "    1. Measure actual distance with a tape measure\n"
        printf "    2. factor = actual_m / reported_m\n"
        printf "    3. New WHEEL_DIAM_M = old_diameter_mm * factor\n"
        printf "\n  Example: if tape = 5.00m and reported = %.4fm\n", max
        if (max > 0.001) {
            printf "    factor = %.4f\n", 5.0 / max
        } else {
            printf "    (reported distance too small — did you drive forward?)\n"
        }
    }
    ' "$tmpfile"
}

# Live mode: watch odom in real-time
live_mode() {
    check_topic "/odom_relay"

    header "Live /odom_relay monitor — press Ctrl-C to stop"
    echo "  Watching pose.pose.position.x from /odom_relay..."
    echo "  ──────────────────────────────────────────────────────"

    ros2 topic echo /odom_relay --field pose.pose.position.x 2>/dev/null \
        | while read -r val; do
            val=$(echo "$val" | tr -d ' ')
            [[ -z "$val" || "$val" == "~" ]] && continue
            t=$(date +%H:%M:%S)
            printf "%s  x=%+10.4f m\n" "$t" "$val"
        done
}

# Plot mode: ASCII plot of position over time
plot_mode() {
    check_topic "/odom_relay"

    header "ASCII odom position plot (last 60 samples)"
    echo "  X position (m) over time"
    echo "  ─────────────────────────────────────────"

    local tmpfile
    tmpfile=$(mktemp)
    trap "rm -f '$tmpfile'" RETURN

    local start_time count=0
    start_time=$(date +%s)
    while true; do
        if [[ $(($(date +%s) - start_time)) -gt 30 ]]; then
            break
        fi
        val=$(ros2 topic echo /odom_relay --field pose.pose.position.x --once 2>/dev/null | tr -d ' ')
        if [[ "$val" =~ ^-?[0-9]+\.?[0-9]*$ ]]; then
            echo "$val" >> "$tmpfile"
            count=$((count + 1))
        fi
        [[ $count -ge 60 ]] && break
        sleep 0.5
    done

    if [[ ! -s "$tmpfile" ]]; then
        die "No odom data collected. Is the robot running and driving?"
    fi

    awk '
    BEGIN { min=1e9; max=-1e9 }
    { if ($1+0 == $1 && $1 != "") { if ($1 < min) min=$1; if ($1 > max) max=$1; a[NR]=$1 } }
    END {
        range = max - min
        if (range < 0.001) range = 0.001
        width = 60
        print ""
        printf "  min=%+.4f  max=%+.4f  range=%.4f m\n", min, max, range
        print ""
        for (i = 1; i <= NR; i++) {
            col = int((a[i] - min) / range * (width - 1)) + 1
            line = ""
            for (j = 1; j <= width; j++) {
                if (j == col) line = line "*"
                else line = line " "
            }
            printf "  [%4d] %s  %.4f m\n", i, line, a[i]
        }
    }
    ' "$tmpfile"

    echo ""
    local final
    final=$(tail -1 "$tmpfile")
    printf "  Final position: %.4f m\n" "$final"
}

# ---- Main ------------------------------------------------------------
case "$MODE" in
    --help|-h)
        echo "Usage: $0 [--live|--sample [N]|--reset|--plot]"
        echo ""
        echo "  --live          Watch odom in real-time (default)"
        echo "  --sample [N]    Collect N samples, print stats, exit (default N=100)"
        echo "  --reset         Reset ESP32 odom counters"
        echo "  --plot          ASCII plot of position over time"
        echo ""
        echo "Examples:"
        echo "  $0 --reset                    # reset odom before test"
        echo "  $0 --sample 200              # collect 200 samples"
        echo "  $0 --plot                    # show position history as ASCII plot"
        echo "  $0 --live | head -30         # live but limit to 30 lines"
        exit 0
        ;;
    --sample)
        sample_mode "$@"
        ;;
    --reset)
        reset_esp32_odom
        ;;
    --plot)
        plot_mode
        ;;
    --live|"")
        live_mode
        ;;
    *)
        die "Unknown argument: $MODE. Use --help for usage."
        ;;
esac
