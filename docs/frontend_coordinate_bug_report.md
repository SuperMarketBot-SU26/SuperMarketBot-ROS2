# CRITICAL BUG: Map Editor Coordinate Mismatch

**To:** Frontend Development Team
**File:** `/public/robot-map-editor.html`

## The Problem
The current Web Map Editor is rendering and saving coordinates using raw HTML Canvas pixels, completely ignoring the ROS 2 SLAM metadata. 
Because ROS 2 and HTML Canvas have fundamentally opposite coordinate systems, any waypoint placed in the admin portal will send the robot to the wrong location (or into a wall).

### The Differences
1. **Origin (0,0):** In HTML Canvas, `(0,0)` is the **Top-Left** of the image. In ROS 2, `(0,0)` is determined by the YAML `origin` array (usually the **Bottom-Left**).
2. **Y-Axis:** In HTML Canvas, Y goes **DOWN**. In ROS 2, Y goes **UP**.
3. **Scale:** The current editor hardcodes `SCALE = 64` pixels/meter. In ROS 2, scale is dictated by the YAML `resolution` (usually `0.05` meters/pixel).

*Good News:* The Backend is already correctly extracting `resolution`, `originX`, and `originY` from the ROS 2 map and sending them in the `API.getMap` response (`MapFloorplanDto`). You just need to use them!

---

## The Mathematical Fix

You need to replace your hardcoded `SCALE` logic with translation functions that convert between **Canvas Pixels (px, py)** and **ROS 2 Real-World Meters (ros_x, ros_y)**.

### Step 1: Store the Map Metadata
When you fetch the map via `API.getMap`, save these values into global state:
```javascript
let mapResolution = 0.05;
let mapOriginX = 0;
let mapOriginY = 0;
let imgWidthPixels = 0;
let imgHeightPixels = 0;

// When the map loads:
currentMap = await API.getMap(floorId);
mapResolution = currentMap.resolution || 0.05;
mapOriginX = currentMap.originX || 0;
mapOriginY = currentMap.originY || 0;

// Calculate pixel dimensions of the image
imgWidthPixels = Math.round(currentMap.widthMeters / mapResolution);
imgHeightPixels = Math.round(currentMap.heightMeters / mapResolution);
```

### Step 2: Implement Conversion Functions
Add these utility functions to convert between Pixels and ROS 2 Coordinates. 

```javascript
/**
 * Converts a Canvas Pixel (px, py) to a ROS 2 Coordinate (ros_x, ros_y)
 * Use this when the admin clicks the map to ADD a waypoint/node.
 */
function pixelsToRos(px, py) {
    // Invert the Y axis (Canvas Top-Left vs ROS 2 Bottom-Left)
    const ros_grid_y = (imgHeightPixels - 1) - py;
    
    return {
        x: mapOriginX + (px * mapResolution),
        y: mapOriginY + (ros_grid_y * mapResolution)
    };
}

/**
 * Converts a ROS 2 Coordinate (ros_x, ros_y) to a Canvas Pixel (px, py)
 * Use this when you need to DRAW nodes/robots loaded from the Database.
 */
function rosToPixels(ros_x, ros_y) {
    const px = (ros_x - mapOriginX) / mapResolution;
    const ros_grid_y = (ros_y - mapOriginY) / mapResolution;
    
    // Invert the Y axis back for Canvas
    const py = (imgHeightPixels - 1) - ros_grid_y;
    
    return { x: px, y: py };
}
```

### Step 3: Apply to Mouse Events and Rendering
1. **On Mouse Click (Adding a Node):** Right now, `screenToWorld` gives you the raw pixel coordinate `(px, py)` of the mouse click on the image. You must pass that through `pixelsToRos(px, py)` before saving `newNode.x` and `newNode.y` to the arrays and database.
2. **On Render (Drawing Nodes & Robot):** When looping through `nodes` or rendering the Robot's `(robotX, robotY)` telemetry, you must pass those database coordinates through `rosToPixels(ros_x, ros_y)` to get the `(px, py)` needed for the Canvas `arc()` and `rect()` functions.
3. Remove the hardcoded `const SCALE = 64;` completely. All drawing should be scaled natively by `zoom`.
