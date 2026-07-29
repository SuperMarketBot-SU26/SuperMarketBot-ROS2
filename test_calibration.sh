#!/usr/bin/env bash
# test_calibration.sh — Wheel-encoder + WHEEL_BASE_M calibration for SmartMarketBot.
#
# This script guides you through measuring actual hardware dimensions and computing
# the correct Config.h values. It does NOT upload firmware — you do that manually.
#
# Hardware dimensions needed:
#   WHEEL_DIAM_M   — wheel diameter at the rolling surface (NOT the rubber hub)
#   WHEEL_BASE_M   — center-to-center distance between left and right wheels
#   ENC_PPR         — encoder pulses per revolution (count edges as appropriate)
#
# After measuring, this script prints the corrected Config.h values to set.
#
# Usage:
#   ./test_calibration.sh                    # interactive guided calibration
#   ./test_calibration.sh --measure          # measure actual WHEEL_DIAM_M from odom drift
#   ./test_calibration.sh --compute DIAM PPR  # compute Config.h values from known inputs
#
# Requires:
#   - ESP32 firmware flashed with current Config.h values
#   - ROS2 bringup running (smb_robot_bringup)
#   - Robot on flat hard floor with 5+ meter clear path
#   - Tape measure / caliper

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_DISTRO="${ROS_DISTRO:-lyrical}"

# Source ROS so ros2 run/launch works
source /opt/ros/${ROS_DISTRO}/setup.bash 2>/dev/null || {
    echo "[test_calibration] ERROR: failed to source /opt/ros/${ROS_DISTRO}/setup.bash"
    exit 1
}

# Source workspace
if [[ -f "$SCRIPT_DIR/install/setup.bash" ]]; then
    source "$SCRIPT_DIR/install/setup.bash"
elif [[ -f "$SCRIPT_DIR/../install/setup.bash" ]]; then
    source "$SCRIPT_DIR/../install/setup.bash"
fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; BLUE='\033[0;34m'; RESET='\033[0m'

BANNER="
${BOLD}╔═══════════════════════════════════════════════════════════════╗
║       SmartMarketBot — Wheel Encoder Calibration Wizard            ║
╚═══════════════════════════════════════════════════════════════════════╝${RESET}

This script helps you measure and compute the correct Config.h values
for WHEEL_DIAM_M, WHEEL_BASE_M, and ENC_PPR to minimize odom drift.

${YELLOW}WARNING:${RESET} This script does NOT upload firmware. You must edit
Config.h manually after running this script, then flash the ESP32.
"

# ---- Helpers ----------------------------------------------------------
ask() {
    local prompt="$1"
    local default="${2:-}"
    local var="$3"
    local opts="$4"

    while true; do
        if [[ -n "$default" ]]; then
            printf "  ${CYAN}%s${RESET} [%s]: " "$prompt" "$default"
        else
            printf "  ${CYAN}%s${RESET}: " "$prompt"
        fi
        read -r ans
        ans="${ans:-$default}"
        if [[ -n "$opts" ]]; then
            if [[ "$opts" == *" $ans "* ]] || [[ "$opts" == "$ans" ]]; then
                eval "$var='$ans'"
                return 0
            else
                echo -e "${RED}  Invalid option. Choose from: $opts${RESET}"
            fi
        else
            if [[ -n "$ans" ]]; then
                eval "$var='$ans'"
                return 0
            fi
        fi
    done
}

ask_float() {
    local prompt="$1"
    local default="$2"
    local var="$3"

    while true; do
        if [[ -n "$default" ]]; then
            printf "  ${CYAN}%s${RESET} [%.4f]: " "$prompt" "$default"
        else
            printf "  ${CYAN}%s${RESET}: " "$prompt"
        fi
        read -r ans
        ans="${ans:-$default}"
        if [[ "$ans" =~ ^[0-9]+\.?[0-9]*$ ]] || [[ "$ans" =~ ^[0-9]*\.[0-9]+$ ]]; then
            eval "$var='$ans'"
            return 0
        else
            echo -e "${RED}  Invalid number.${RESET}"
        fi
    done
}

ask_int() {
    local prompt="$1"
    local default="$2"
    local var="$3"

    while true; do
        if [[ -n "$default" ]]; then
            printf "  ${CYAN}%s${RESET} [%d]: " "$prompt" "$default"
        else
            printf "  ${CYAN}%s${RESET}: " "$prompt"
        fi
        read -r ans
        ans="${ans:-$default}"
        if [[ "$ans" =~ ^[0-9]+$ ]]; then
            eval "$var='$ans'"
            return 0
        else
            echo -e "${RED}  Invalid integer.${RESET}"
        fi
    done
}

banner() {
    echo -e "$BANNER"
}

section() {
    echo ""
    echo -e "${BOLD}━━━ $1 ━━━${RESET}"
}

print_result() {
    local cfg="$1"
    echo ""
    echo -e "${GREEN}${BOLD}✓ Calibration complete!${RESET}"
    echo ""
    echo "Edit these values in ${BLUE}Config.h${RESET}:"
    echo ""
    echo -e "  ${CYAN}${cfg}${RESET}"
    echo ""
    echo "Then flash the ESP32 with the updated firmware."
}

die() {
    echo -e "${RED}[ERROR] $1${RESET}" >&2
    exit 1
}

# ---- Mode: interactive (default) ------------------------------------
mode_interactive() {
    banner

    # ── Step 1: Encoder PPR ─────────────────────────────────────
    section "Step 1 of 4 — Encoder PPR"
    echo ""
    echo "  Count the slots/teeth on your encoder disc."
    echo "  The disc is mounted on the motor shaft — remove the wheel to see it."
    echo ""
    echo "  Common types:"
    echo "    • 20-slot disc, count RISING edges only  → ENC_PPR = 20"
    echo "    • 20-slot disc, count BOTH edges (quadrature) → ENC_PPR = 40"
    echo "    • Other slot count → enter that number"
    echo ""
    echo "  To verify: look at Odometry.h line 15 comment:"
    echo "    'Mỗi encoder có đĩa 20 khe chữ U → ENC_PPR = 20'"
    echo ""
    ask_int "Encoder disc slot count (e.g. 20)" 20 "DISC_COUNT"
    ask "Count encoder edges" rising "EDGE_MODE" " both rising"
    case "$EDGE_MODE" in
        rising)   ENC_PPR=$DISC_COUNT ;;
        both)     ENC_PPR=$((DISC_COUNT * 2)) ;;
    esac
    echo ""
    echo -e "  → ENC_PPR = ${CYAN}$ENC_PPR${RESET}"
    echo -e "  → Using ${CYAN}RISING${RESET} edges → matches Odometry.h ISR: attachInterrupt(..., RISING)"

    # ── Step 2: Wheel diameter ──────────────────────────────────
    section "Step 2 of 4 — Wheel Diameter"
    echo ""
    echo "  Measure the wheel at the ROLLING SURFACE (the rubber that touches floor)."
    echo "  Use a caliper for accuracy. Measure at least 2x and average."
    echo ""
    echo "  Current Config.h value: WHEEL_DIAM_M = $(grep 'WHEEL_DIAM_M' "$SCRIPT_DIR"/../SuperMarketBot-IOT/ESP32-S3/SuperMarketBot-IOT/Config.h 2>/dev/null | grep define | awk '{print $3}' || echo 'unknown')"
    echo ""
    ask_float "Measured wheel diameter (mm)" 65.0 "DIAM_MM"
    echo ""
    echo -e "  → WHEEL_DIAM_M = ${CYAN}$(awk "BEGIN {printf \"%.4f\", $DIAM_MM / 1000.0}")${RESET}"
    echo -e "  → WHEEL_CIRC_M = π × ${DIAM_MM}mm = ${CYAN}$(awk "BEGIN {printf \"%.4f\", 3.14159265 * $DIAM_MM / 1000.0}")${RESET} m"

    # ── Step 3: Wheel base ───────────────────────────────────────
    section "Step 3 of 4 — Wheel Base"
    echo ""
    echo "  Measure the center-to-center distance between the left and right wheel axles."
    echo "  Measure across the chassis body (not along the floor)."
    echo ""
    echo "  Current Config.h value: WHEEL_BASE_M = $(grep 'WHEEL_BASE_M' "$SCRIPT_DIR"/../SuperMarketBot-IOT/ESP32-S3/SuperMarketBot-IOT/Config.h 2>/dev/null | grep define | head -1 | awk '{print $3}' || echo 'unknown')"
    echo ""
    ask_float "Measured wheel base (mm)" 365.0 "BASE_MM"
    echo ""
    echo -e "  → WHEEL_BASE_M = ${CYAN}$(awk "BEGIN {printf \"%.4f\", $BASE_MM / 1000.0}")${RESET} m"

    # ── Step 4: Verify with odom drift test ──────────────────────
    section "Step 4 of 4 — Odom Drift Test"
    echo ""
    echo "  This is the definitive calibration check."
    echo ""
    echo "  Test procedure:"
    echo "    1. Place robot at start of a 5+ meter flat path (no carpet)"
    echo "    2. In another terminal: ${CYAN}./test_odom_drift.sh --sample 200${RESET}"
    echo "    3. Drive forward ~5 meters at constant speed (use teleop 'i' key)"
    echo "    4. After driving, note the 'Final position.x' from test_odom_drift.sh"
    echo "    5. Measure actual distance with tape measure"
    echo ""
    ask_float "Reported distance from ros2 topic (m)" "" "REPORTED_M"
    ask_float "Actual distance measured with tape (m)" "" "ACTUAL_M"
    echo ""

    # ── Compute correction ─────────────────────────────────────────
    local circ_new circ_corr
    local circ_old d_new
    circ_old=$(awk "BEGIN {printf \"%.6f\", 3.14159265 * $DIAM_MM / 1000.0}")
    d_new=$(awk "BEGIN {printf \"%.6f\", $DIAM_MM / 1000.0}")

    if [[ -n "$REPORTED_M" && "$REPORTED_M" != "0" ]]; then
        circ_corr=$(awk "BEGIN {printf \"%.6f\", $circ_old * $ACTUAL_M / $REPORTED_M}")
        d_new=$(awk "BEGIN {printf \"%.6f\", $circ_corr / 3.14159265}")
        local error_pct
        error_pct=$(awk "BEGIN {printf \"%.2f\", ($REPORTED_M - $ACTUAL_M) / $ACTUAL_M * 100.0}")
        echo "  Drift analysis:"
        echo "    Reported: $REPORTED_M m | Actual: $ACTUAL_M m | Error: $error_pct%"
        echo ""
        if (( $(echo "$error_pct > 0" | bc -l) )); then
            echo -e "  ${YELLOW}WHEEL_DIAM_M is too LARGE → robot overshoots.${RESET}"
        else
            echo -e "  ${YELLOW}WHEEL_DIAM_M is too SMALL → robot undershoots.${RESET}"
        fi
        echo ""
        echo "  Corrected values (based on drift test):"
    else
        echo "  Using measured dimensions (no drift test):"
    fi

    local cfg
    cfg="#define ENC_PPR       ${ENC_PPR}.0f        // encoder pulses/revolution (was $([[ -n "$DISC_COUNT" ]] && echo $DISC_COUNT || echo '?'))
#define WHEEL_DIAM_M  ${d_new}f  // wheel diameter (mm): $(awk "BEGIN {printf \"%.1f\", $DIAM_MM}") → corrected to $(awk "BEGIN {printf \"%.2f\", $d_new * 1000.0}")mm
#define WHEEL_BASE_M  $(awk "BEGIN {printf \"%.4f\", $BASE_MM / 1000.0}")f  // wheel base center-to-center (mm): measured"

    print_result "$cfg"

    echo "  To also verify heading accuracy:"
    echo "    1. Mark a starting direction (point robot at a fixed reference)"
    echo "    2. Drive in a square: forward 2m → turn 90° → forward 2m → turn 90°"
    echo "    3. After 4 turns (360°) the heading should return to 0°"
    echo "    4. Any heading error suggests WHEEL_BASE_M is wrong"
}

# ---- Mode: measure (odom drift test) -------------------------------
mode_measure() {
    echo -e "${BOLD}Odom Drift Measurement${RESET}"
    echo ""
    echo "Place robot at start. Drive exactly 5 meters forward."
    echo "Then enter the results."
    echo ""

    ask_float "Reported distance from ros2 topic echo /odom_relay position.x (m)" "" "REPORTED_M"
    ask_float "Actual distance measured with tape (m)" "" "ACTUAL_M"

    if [[ -z "$REPORTED_M" || "$REPORTED_M" == "0" ]]; then
        die "Reported distance required."
    fi

    local factor d_corr
    factor=$(awk "BEGIN {printf \"%.6f\", $ACTUAL_M / $REPORTED_M}")
    d_corr=$(awk "BEGIN {printf \"%.4f\", $(( $(grep 'WHEEL_DIAM_M' "$SCRIPT_DIR"/../SuperMarketBot-IOT/ESP32-S3/SuperMarketBot-IOT/Config.h 2>/dev/null | grep define | awk '{print $3}') * 1000 | bc -l | head -c -3 )) / 1000.0 * $factor}")
    d_corr=$(awk "BEGIN {printf \"%.4f\", 0.065 * $factor}")

    local error_pct
    error_pct=$(awk "BEGIN {printf \"%.2f\", ($REPORTED_M - $ACTUAL_M) / $ACTUAL_M * 100.0}")

    echo ""
    echo -e "Drift rate: ${CYAN}${error_pct}%${RESET} per meter"
    echo -e "Correction factor: ${CYAN}${factor}${RESET}"
    echo ""
    echo "New WHEEL_DIAM_M = old_diameter × $factor = $(awk "BEGIN {printf \"%.4f\", 0.065 * $factor}") m ($(awk "BEGIN {printf \"%.1f\", 0.065 * $factor * 1000.0}") mm)"
    echo ""
    echo "To update Config.h:"
    echo -e "  ${CYAN}#define WHEEL_DIAM_M  $(awk "BEGIN {printf \"%.4f\", 0.065 * $factor}")f${RESET}"
}

# ---- Mode: compute (from known inputs) -----------------------------
mode_compute() {
    local diam_mm="$1"
    local enc_ppr="$2"

    if [[ -z "$diam_mm" || -z "$enc_ppr" ]]; then
        echo "Usage: $0 --compute DIAM_MM ENC_PPR"
        echo "  DIAM_MM  — wheel diameter in millimeters"
        echo "  ENC_PPR  — encoder pulses per revolution"
        exit 1
    fi

    local circ d
    circ=$(awk "BEGIN {printf \"%.4f\", 3.14159265 * $diam_mm / 1000.0}")
    d=$(awk "BEGIN {printf \"%.4f\", $diam_mm / 1000.0}")

    local cfg
    cfg="#define ENC_PPR       ${enc_ppr}.0f        // encoder pulses/revolution
#define WHEEL_DIAM_M  ${d}f  // wheel diameter: measured ${diam_mm}mm
#define WHEEL_CIRC_M  (PI * WHEEL_DIAM_M)  // auto-computed"

    print_result "$cfg"
}

# ---- Main ------------------------------------------------------------
MODE="${1:-interactive}"
shift 2>/dev/null || true

case "$MODE" in
    --help|-h)
        echo "Usage: $0 [--interactive|--measure|--compute DIAM ENC_PPR|--help]"
        echo ""
        echo "  --interactive (default)  Guided calibration wizard"
        echo "  --measure               Run odom drift test, compute correction"
        echo "  --compute DIAM ENC_PPR  Compute Config.h values from known inputs"
        exit 0
        ;;
    --measure|-m)
        mode_measure
        ;;
    --compute|-c)
        mode_compute "$1" "$2"
        ;;
    --interactive|-i|"")
        mode_interactive
        ;;
    *)
        echo "Unknown mode: $MODE"
        echo "Use: $0 --help"
        exit 1
        ;;
esac
