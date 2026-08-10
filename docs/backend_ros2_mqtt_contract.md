# SuperMarketBot MQTT Contract
**Between .NET Backend and ROS 2 Robot (smb_mqtt_bridge)**

> [!WARNING]
> **Action Required for Backend Team:** 
> An audit of the .NET Backend found a command mismatch. `NavigationController.cs` correctly uses `"NAVIGATE_WAYPOINTS"`, but `NavigationCommandService.cs` (line 38) and `RobotService.cs` (lines 106 & 144) incorrectly send `"navigate"`. Because the robot strictly expects `"NAVIGATE_WAYPOINTS"`, these commands will be ignored. Please run a Find & Replace in those files to change `"navigate"` to `"NAVIGATE_WAYPOINTS"`.

This document defines the exact payloads and topics required for the .NET Backend to fully control the robot's navigation without knowing any internal ROS 2 details.

---

## 1. Global Message Format (Double-Encoding)
All commands sent to the robot **MUST** be wrapped in this outer JSON envelope. 
The `payload` field must be a **Stringified JSON object**, not a nested JSON object.

```json
{
    "command": "<COMMAND_NAME>",
    "payload": "<JSON_STRINGIFIED_PAYLOAD>",
    "timestamp": "2026-08-10T15:00:00Z"
}
```

---

## 2. Inbound Commands (Backend -> Robot)
**Topic:** `smartmarketbot/robot/{robotCode}/command`

### 2.1 Navigate Waypoints
Sends a sequence of waypoints for the robot to visit sequentially. To go to a single point, just send an array with 1 waypoint.
- **command:** `NAVIGATE_WAYPOINTS`
- **inner payload format:**
```json
{
  "missionId": "string (optional, used for tracking)",
  "waypoints": [
    {
      "name": "string (optional, e.g., 'Aisle 4')",
      "role": "ad | photo | guide_stop | rest (optional)",
      "x": 1.5,
      "y": -0.2,
      "yaw": 1.57,
      "nodeId": "string (optional)",
      "dwellTimeSeconds": 30,
      "mustCompletePlaylist": false,
      "playlist": ["video1.mp4", "video2.mp4"]
    }
  ]
}
```

### 2.2 Cancel Navigation
Instantly cancels the active navigation mission.
- **command:** `CANCEL_NAV`
- **inner payload format:**
```json
{
  "reason": "string (optional)"
}
```

### 2.3 Emergency Stop (E-Stop)
Halts the robot immediately and engages the physical/software E-Stop logic.
- **command:** `ESTOP`
- **inner payload format:**
```json
{
  "reason": "string (optional)"
}
```

### 2.4 Pause / Resume
Pauses the current mission in place, or resumes it from where it left off.
- **command:** `PAUSE_NAV` (Payload: `{}`)
- **command:** `RESUME_NAV` (Payload: `{}`)

### 2.5 Set Speed
*(Informational only, triggers a log on the robot. Actual speed is governed by Nav2).*
- **command:** `SET_SPEED`
- **inner payload format:**
```json
{
  "speed": 0.5
}
```

---

## 3. Outbound Updates (Robot -> Backend)

### 3.1 Telemetry (Real-time Health & Location)
Published twice a second (2 Hz).
**Topic:** `smartmarketbot/robot/{robotCode}/telemetry`
**Payload:**
```json
{
    "Battery": 85,
    "Location": null,
    "Status": "IDLE | ESTOP | PAUSED | NAVIGATING",
    "CurrentNodeId": "string (if available)",
    "Mode": "NAV | IDLE",
    "IsOnline": true,
    "XCoord": 1.52,
    "YCoord": -0.21,
    "Timestamp": "2026-08-10T15:00:00Z",
    "HeadingRad": 1.57,
    "Estop": false
}
```

### 3.2 Navigation Status (Event-Driven)
Published only when the mission state changes.
**Topic:** `smartmarketbot/robot/{robotCode}/navigation_status`
**Payload:**
```json
{
    "status": "NAVIGATING | MOVING | ARRIVED | PLAYLIST_PLAYING | PLAYLIST_COMPLETE | COMPLETED | ERROR | CANCELLED | PAUSED",
    "timestamp": "2026-08-10T15:00:00Z",
    "missionId": "string (if provided in command)",
    "waypoint": "string (current waypoint name)",
    "waypointIndex": 0,
    "role": "ad",
    "playlist": ["video1.mp4"],
    "dwellTimeSeconds": 30,
    "error": "string (only if status is ERROR)"
}
```

### 3.3 Logs
**Topic:** `smartmarketbot/robot/{robotCode}/log`
**Payload:**
```json
{
    "level": "INFO | WARN | ERROR",
    "message": "string",
    "node": "smb_mqtt_bridge",
    "timestamp": "2026-08-10T15:00:00Z"
}
```
