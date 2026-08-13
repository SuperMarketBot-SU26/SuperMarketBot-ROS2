"""MQTT Bridge for SuperMarketBot — Backend ↔ Nav2 waypoint navigation.

Receives advertising mission commands from the SuperMarketBot-BE backend
over MQTT (HiveMQ Cloud) and orchestrates autonomous waypoint navigation
via Nav2's FollowWaypoints action. Reports navigation progress back to
the backend so the frontend dashboard and Android tablet stay in sync.

Architecture
------------
- **MQTT inbound** (backend → robot):
  Subscribes to ``smartmarketbot/robot/{robotCode}/command``.
  The backend double-encodes payloads: the outer JSON has ``command`` +
  ``payload`` (a JSON *string*) + ``timestamp``. We parse the outer JSON,
  then ``json.loads()`` the inner ``payload`` field.

- **Nav2 integration**:
  Uses ``nav2_simple_commander.BasicNavigator`` (same pattern as
  ``waypoint_follower.py``) to send waypoints and monitor progress.

- **MQTT outbound** (robot → backend):
  Publishes status to ``smartmarketbot/robot/{robotCode}/navigation_status``.
  The backend forwards these to the frontend via SignalR, and to the
  Android tablet for ad playback triggering.

Audio / ad playback
-------------------
Audio plays on the **Android tablet**, not on the robot. The bridge
reports ``ARRIVED`` + ``PLAYLIST_PLAYING`` + ``PLAYLIST_COMPLETE`` status
with playlist data included. The backend forwards this to the tablet via
SignalR's ``AdPlaybackUpdate`` method. The bridge manages dwell timing
independently of actual tablet playback.

Threading model
---------------
- paho-mqtt runs its network loop in a dedicated thread (``loop_start()``).
- MQTT callbacks post commands to a thread-safe ``queue.Queue``.
- A ROS 2 timer (10 Hz) drains the queue and dispatches commands.
- Nav2 navigation runs in a separate thread to avoid blocking the ROS
  executor (so status updates and new commands can still be processed).
"""

import json
import math
import queue
import ssl
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import rclpy
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus
from smb_msgs.srv import SupervisorCmd
from std_msgs.msg import Bool, String
from sensor_msgs.msg import BatteryState
import tf2_ros
from tf2_ros import TransformException


def _yaw_to_quat(yaw: float):
    """Convert a 2-D yaw angle (radians) to a quaternion (x, y, z, w)."""
    half = yaw * 0.5
    return (0.0, 0.0, math.sin(half), math.cos(half))


def _utc_iso():
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class MqttBridge(Node):
    """ROS 2 node bridging MQTT commands to Nav2 waypoint navigation."""

    def __init__(self):
        super().__init__('smb_mqtt_bridge')

        # ---- Parameters ----
        self.declare_parameter('mqtt_host', '')
        self.declare_parameter('mqtt_port', 8883)
        self.declare_parameter('mqtt_username', '')
        self.declare_parameter('mqtt_password', '')
        self.declare_parameter('mqtt_use_tls', True)
        self.declare_parameter('robot_code', 'RB001')

        self._mqtt_host = self.get_parameter('mqtt_host').value
        self._mqtt_port = self.get_parameter('mqtt_port').value
        self._mqtt_username = self.get_parameter('mqtt_username').value
        self._mqtt_password = self.get_parameter('mqtt_password').value
        self._mqtt_use_tls = self.get_parameter('mqtt_use_tls').value
        self._robot_code = self.get_parameter('robot_code').value

        # ---- MQTT topics ----
        self._topic_command = f'smartmarketbot/robot/{self._robot_code}/command'
        self._topic_nav_status = f'smartmarketbot/robot/{self._robot_code}/navigation_status'
        self._topic_telemetry = f'smartmarketbot/robot/{self._robot_code}/telemetry'
        self._topic_log = f'smartmarketbot/robot/{self._robot_code}/log'

        # ---- State ----
        self._command_queue = queue.Queue(maxsize=64)
        self._navigator = None  # Initialized lazily after Nav2 is ready
        self._nav_thread = None
        self._navigating = False
        self._cancel_requested = False
        self._pause_requested = False
        self._paused_waypoints = []  # Remaining waypoints for resume
        self._paused_waypoint_data = []  # Remaining waypoint metadata for resume
        self._paused_mission_id = None
        self._paused_start_index = 0  # Global index offset for resumed navigation
        self._mqtt_connected = False

        # ---- Telemetry State ----
        self._latest_x = None
        self._latest_y = None
        self._latest_heading = None
        self._latest_battery = None
        self._latest_mode = None
        self._latest_estop = None
        self._current_node_id = None

        # ---- Action Clients ----
        self._nav_to_pose_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')

        # ---- Supervisor service client ----
        self._supervisor_client = self.create_client(
            SupervisorCmd, '/supervisor/cmd')

        from rclpy.callback_groups import ReentrantCallbackGroup
        self._cb_group = ReentrantCallbackGroup()
        
        # ---- TF2 Listener for Robot Pose ----
        self._tf_buffer = tf2_ros.Buffer()
        # In ROS 2 python, pass spin_thread=True to use an isolated thread for TF
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self, spin_thread=True)

        self.create_subscription(BatteryState, '/battery_state', self._on_battery_state, 10, callback_group=self._cb_group)
        self.create_subscription(String, '/supervisor/state', self._on_supervisor_state, 10)
        self.create_subscription(Bool, '/emergency_stop', self._on_emergency_stop, 10)

        # ---- MQTT client setup ----
        self._mqtt_client = mqtt.Client(
            client_id=f'smb_ros2_bridge_{self._robot_code}',
            protocol=mqtt.MQTTv311,
        )
        if self._mqtt_username:
            self._mqtt_client.username_pw_set(
                self._mqtt_username, self._mqtt_password)
        if self._mqtt_use_tls:
            self._mqtt_client.tls_set(
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS,
            )

        self._mqtt_client.on_connect = self._on_mqtt_connect
        self._mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self._mqtt_client.on_message = self._on_mqtt_message
        self._mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

        # ---- Start MQTT connection ----
        if self._mqtt_host:
            self.get_logger().info(
                f'Connecting to MQTT broker {self._mqtt_host}:{self._mqtt_port} '
                f'(TLS={self._mqtt_use_tls}, robot={self._robot_code})')
            try:
                self._mqtt_client.connect_async(
                    self._mqtt_host, self._mqtt_port, keepalive=60)
                self._mqtt_client.loop_start()
            except Exception as e:
                self.get_logger().error(f'MQTT connect_async failed: {e}')
        else:
            self.get_logger().warning(
                'mqtt_host is empty — MQTT bridge running in offline mode. '
                'Set mqtt_host parameter to connect to a broker.')

        # ---- ROS 2 timer to drain the command queue (10 Hz) ----
        self._cmd_timer = self.create_timer(0.1, self._process_command_queue, callback_group=self._cb_group)

        # ---- ROS 2 timer for Telemetry publishing (2 Hz) ----
        self._telemetry_timer = self.create_timer(0.5, self._publish_telemetry, callback_group=self._cb_group)

        self.get_logger().info(
            f'smb_mqtt_bridge initialized '
            f'(command topic: {self._topic_command})')

    # ======================================================================
    # ROS 2 Subscriptions & Telemetry
    # ======================================================================

    def _update_pose_from_tf(self):
        """Update robot pose from TF (map -> base_link)."""
        try:
            now = rclpy.time.Time()
            trans = self._tf_buffer.lookup_transform(
                'map',
                'base_link',
                now,
                timeout=Duration(seconds=0.1)
            )
            self._latest_x = trans.transform.translation.x
            self._latest_y = trans.transform.translation.y
            
            q = trans.transform.rotation
            siny_cosp = 2 * (q.w * q.z + q.x * q.y)
            cosy_cosp = 1 - 2 * (q.y * q.y + q.z * q.z)
            self._latest_heading = math.atan2(siny_cosp, cosy_cosp)
        except Exception as ex:
            # If TF is not available yet (e.g. SLAM not started), keep values as null
            self.get_logger().error(f"TF Lookup failed with {type(ex).__name__}: {ex}")
            pass

    def _on_battery_state(self, msg: BatteryState):
        """Update battery state."""
        self._latest_battery = int(msg.percentage * 100) if not math.isnan(msg.percentage) else None

    def _on_supervisor_state(self, msg: String):
        """Update supervisor state (Mode)."""
        self._latest_mode = msg.data.upper()

    def _on_emergency_stop(self, msg: Bool):
        """Update emergency stop state."""
        self._latest_estop = msg.data

    def _publish_telemetry(self):
        """Publish real-time telemetry to the backend."""
        # Query latest TF before publishing
        self._update_pose_from_tf()

        # Derive Status
        status_str = "IDLE"
        if self._latest_estop:
            status_str = "ESTOP"
        elif self._navigating:
            if self._pause_requested:
                status_str = "PAUSED"
            else:
                status_str = "NAVIGATING"

        payload = {
            "Battery": self._latest_battery,
            "Location": None,  # BE can infer location if needed, or leave null
            "Status": status_str,
            "CurrentNodeId": self._current_node_id,
            "Mode": self._latest_mode,
            "IsOnline": True,
            "XCoord": self._latest_x,
            "YCoord": self._latest_y,
            "Timestamp": _utc_iso(),
            "HeadingRad": self._latest_heading,
            "Estop": self._latest_estop
        }
        self._mqtt_publish(self._topic_telemetry, payload)

    # ======================================================================
    # MQTT callbacks (called from paho-mqtt's network thread)
    # ======================================================================

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        """Called when MQTT connection is established."""
        if rc == 0:
            self._mqtt_connected = True
            self.get_logger().info(
                f'Connected to MQTT broker {self._mqtt_host}:{self._mqtt_port}')
            # Subscribe to command topic
            client.subscribe(self._topic_command, qos=1)
            self.get_logger().info(f'Subscribed to {self._topic_command}')
            # Publish a log to announce we're online
            self._publish_log('MQTT bridge online', level='INFO')
        else:
            self.get_logger().error(
                f'MQTT connection failed with code {rc}: '
                f'{mqtt.connack_string(rc)}')

    def _on_mqtt_disconnect(self, client, userdata, rc):
        """Called when MQTT connection is lost."""
        self._mqtt_connected = False
        if rc == 0:
            self.get_logger().info('MQTT disconnected cleanly.')
        else:
            self.get_logger().warning(
                f'MQTT disconnected unexpectedly (rc={rc}). '
                'paho-mqtt will auto-reconnect.')

    def _on_mqtt_message(self, client, userdata, msg):
        """Called when an MQTT message is received. Posts to command queue."""
        try:
            payload_str = msg.payload.decode('utf-8')
            self.get_logger().debug(
                f'MQTT message on {msg.topic}: {payload_str[:200]}...')
            # Enqueue for processing on the ROS timer thread
            self._command_queue.put_nowait(payload_str)
        except queue.Full:
            self.get_logger().warning(
                'Command queue full — dropping MQTT message.')
        except Exception as e:
            self.get_logger().error(f'Error handling MQTT message: {e}')

    # ======================================================================
    # Command processing (called from ROS 2 timer — main thread)
    # ======================================================================

    def _process_command_queue(self):
        """Drain the command queue and dispatch each command."""
        while not self._command_queue.empty():
            try:
                payload_str = self._command_queue.get_nowait()
                self._dispatch_command(payload_str)
            except queue.Empty:
                break
            except Exception as e:
                self.get_logger().error(f'Error processing command: {e}')

    def _dispatch_command(self, payload_str: str):
        """Parse the double-encoded MQTT payload and dispatch by command type.

        The backend's MqttClientService.PublishCommandAsync wraps every
        command in an outer envelope::

            {
                "command": "NAVIGATE_WAYPOINTS",
                "payload": "<JSON-stringified inner payload>",
                "timestamp": "2026-08-05T20:23:48"
            }

        We must: (1) parse the outer JSON, (2) read the ``command`` field,
        (3) ``json.loads(outer['payload'])`` to get the inner data.
        """
        try:
            outer = json.loads(payload_str)
        except json.JSONDecodeError as e:
            self.get_logger().error(f'Invalid outer JSON: {e}')
            return

        command = outer.get('command', '').upper()
        inner_str = outer.get('payload', '{}')
        timestamp = outer.get('timestamp', '')

        self.get_logger().info(
            f'Received command: {command} (ts={timestamp})')

        # Parse the inner payload (double-encoded)
        try:
            inner = json.loads(inner_str) if isinstance(inner_str, str) else inner_str
        except json.JSONDecodeError as e:
            self.get_logger().error(
                f'Invalid inner JSON payload for {command}: {e}')
            return

        # Dispatch
        if command == 'NAVIGATE_WAYPOINTS':
            self._handle_navigate_waypoints(inner)
        elif command == 'CANCEL_NAV':
            self._handle_cancel_nav(inner)
        elif command == 'ESTOP':
            self._handle_estop(inner)
        elif command == 'PAUSE_NAV':
            self._handle_pause_nav(inner)
        elif command == 'RESUME_NAV':
            self._handle_resume_nav(inner)
        elif command == 'SET_SPEED':
            self._handle_set_speed(inner)
        else:
            self.get_logger().warning(f'Unknown command: {command}')

    # ======================================================================
    # Command handlers
    # ======================================================================

    def _handle_navigate_waypoints(self, payload: dict):
        """Start waypoint navigation from a NAVIGATE_WAYPOINTS command."""
        mission_id = payload.get('missionId', '')
        waypoints_data = payload.get('waypoints', [])

        if not waypoints_data:
            self.get_logger().error('NAVIGATE_WAYPOINTS: empty waypoints list')
            self._publish_nav_status(
                'ERROR', mission_id=mission_id,
                error_msg='Empty waypoints list')
            return

        if self._navigating:
            self.get_logger().warning(
                'NAVIGATE_WAYPOINTS received while already navigating — '
                'cancelling current navigation first.')
            self._cancel_requested = True
            # Wait briefly for the nav thread to notice
            time.sleep(0.5)

        # Clear any paused state
        self._paused_waypoints = []
        self._paused_waypoint_data = []
        self._paused_mission_id = None
        self._paused_start_index = 0

        self.get_logger().info(
            f'Starting navigation: mission={mission_id}, '
            f'{len(waypoints_data)} waypoint(s)')

        for i, wp in enumerate(waypoints_data):
            name = wp.get('name', f'Waypoint {i}')
            role = wp.get('role', None)
            self.get_logger().info(
                f'  [{i}] {name} → ({wp.get("x", 0):.2f}, '
                f'{wp.get("y", 0):.2f}, yaw={wp.get("yaw", 0):.2f}) '
                f'role={role}')

        # Convert to PoseStamped array
        goal_poses = self._waypoints_to_poses(waypoints_data)
        if not goal_poses:
            self.get_logger().error(
                'NAVIGATE_WAYPOINTS: failed to convert waypoints to poses')
            self._publish_nav_status(
                'FAILED', mission_id=mission_id,
                error='Failed to convert waypoints')
            return

        # Start navigation in a separate thread
        self._cancel_requested = False
        self._pause_requested = False
        self._nav_thread = threading.Thread(
            target=self._run_navigation,
            args=(goal_poses, waypoints_data, mission_id, 0),
            daemon=True,
            name='nav_worker',
        )
        self._nav_thread.start()

    def _handle_cancel_nav(self, payload: dict):
        """Cancel active navigation."""
        reason = payload.get('reason', 'Cancel requested by backend')
        self.get_logger().info(f'CANCEL_NAV: {reason}')

        if self._navigating:
            self._cancel_requested = True
        else:
            self.get_logger().info('CANCEL_NAV: no active navigation to cancel')

        # Clear any paused state too
        if self._paused_waypoints:
            self._paused_waypoints = []
            self._paused_waypoint_data = []
            self._paused_mission_id = None
            self._paused_start_index = 0
            self.get_logger().info('Cleared paused navigation state.')

    def _handle_estop(self, payload: dict):
        """Emergency stop — cancel navigation and engage supervisor ESTOP."""
        reason = payload.get('reason', 'ESTOP from backend')
        self.get_logger().warning(f'ESTOP: {reason}')

        # Cancel any active navigation
        if self._navigating:
            self._cancel_requested = True

        # Clear paused state
        self._paused_waypoints = []
        self._paused_waypoint_data = []
        self._paused_mission_id = None
        self._paused_start_index = 0

        # Publish emergency stop to the latched topic
        estop_pub = self.create_publisher(Bool, '/emergency_stop', 1)
        msg = Bool()
        msg.data = True
        estop_pub.publish(msg)
        self.get_logger().info('Published /emergency_stop = True')

        # Also call the supervisor service for belt-and-suspenders
        self._call_supervisor('estop')

    def _handle_pause_nav(self, payload: dict):
        """Pause navigation — cancel current Nav2 goal, save remaining waypoints."""
        self.get_logger().info('PAUSE_NAV received')
        if self._navigating:
            self._pause_requested = True
        else:
            self.get_logger().info(
                'PAUSE_NAV: no active navigation to pause')

    def _handle_resume_nav(self, payload: dict):
        """Resume paused navigation from saved waypoints."""
        self.get_logger().info('RESUME_NAV received')

        if self._navigating:
            self.get_logger().warning(
                'RESUME_NAV: already navigating — ignoring')
            return

        if not self._paused_waypoints:
            self.get_logger().warning(
                'RESUME_NAV: no paused navigation to resume')
            return

        goal_poses = self._paused_waypoints
        waypoints_data = self._paused_waypoint_data
        mission_id = self._paused_mission_id
        start_index = self._paused_start_index

        # Clear paused state
        self._paused_waypoints = []
        self._paused_waypoint_data = []
        self._paused_mission_id = None
        self._paused_start_index = 0

        self.get_logger().info(
            f'Resuming navigation: mission={mission_id}, '
            f'{len(goal_poses)} remaining waypoint(s) '
            f'(global index offset: {start_index})')

        self._cancel_requested = False
        self._pause_requested = False
        self._nav_thread = threading.Thread(
            target=self._run_navigation,
            args=(goal_poses, waypoints_data, mission_id, start_index),
            daemon=True,
            name='nav_worker',
        )
        self._nav_thread.start()

    def _handle_set_speed(self, payload: dict):
        """Handle SET_SPEED command — log only (speed is controlled by Nav2 params)."""
        speed = payload.get('speed', None)
        self.get_logger().info(
            f'SET_SPEED: {speed} (informational only — speed is controlled '
            'by Nav2 DWB planner params)')

    # ======================================================================
    # Nav2 navigation (runs in a dedicated thread)
    # ======================================================================

    def _run_navigation(self, goal_poses, waypoints_data, mission_id, start_index):
        """Execute waypoint navigation via Nav2 FollowWaypoints.

        This runs in a separate thread so MQTT commands (cancel, estop)
        can still be processed while navigation is in progress.

        Parameters
        ----------
        goal_poses : list[PoseStamped]
            The Nav2 goal poses to follow.
        waypoints_data : list[dict]
            The original waypoint metadata from the backend (name, role,
            dwellTimeSeconds, playlist, etc.).
        mission_id : str
            The mission identifier from the backend.
        start_index : int
            Global waypoint index offset (nonzero when resuming after pause).
        """
        self._navigating = True

        try:
            # Wait for action server to be ready
            self.get_logger().info('Waiting for Nav2 action server...')
            self._nav_to_pose_client.wait_for_server()
            
            # Tell supervisor we're in NAV mode
            self._call_supervisor('nav')

            # Publish initial status
            self._publish_nav_status(
                'NAVIGATING', mission_id=mission_id,
                waypoint_name=waypoints_data[0].get('name', 'Waypoint 0'),
                waypoint_index=start_index)

            # --- Send all waypoints to Nav2 at once ---
            # We use FollowWaypoints which visits them sequentially.
            # To implement per-waypoint dwell behavior, we navigate
            # one waypoint at a time.
            last_completed_local = -1  # Track progress within this batch

            for local_idx in range(len(goal_poses)):
                if self._cancel_requested:
                    self.get_logger().info('Navigation cancelled by request.')
                    self._publish_nav_status(
                        'CANCELLED', mission_id=mission_id,
                        waypoint_index=global_idx)
                    return

                if self._pause_requested:
                    remaining_poses = goal_poses[local_idx:]
                    remaining_data = waypoints_data[local_idx:]
                    self._paused_waypoints = remaining_poses
                    self._paused_waypoint_data = remaining_data
                    self._paused_mission_id = mission_id
                    self._paused_start_index = start_index + local_idx
                    self.get_logger().info(
                        f'Navigation paused at waypoint {start_index + local_idx}. '
                        f'{len(remaining_poses)} waypoint(s) saved for resume.')
                    self._publish_nav_status(
                        'PAUSED', mission_id=mission_id,
                        waypoint_index=start_index + local_idx)
                    return

                global_idx = start_index + local_idx
                wp_data = waypoints_data[local_idx]
                wp_name = wp_data.get('name', f'Waypoint {global_idx}')
                wp_role = wp_data.get('role', None)

                # Publish MOVING status
                self._publish_nav_status(
                    'MOVING', mission_id=mission_id,
                    waypoint_name=wp_name, waypoint_index=global_idx,
                    role=wp_role)

                # Navigate to this single waypoint using native ActionClient
                self.get_logger().info(
                    f'Navigating to waypoint [{global_idx}] "{wp_name}" '
                    f'(role={wp_role})')
                
                goal_msg = NavigateToPose.Goal()
                goal_msg.pose = goal_poses[local_idx]
                send_goal_future = self._nav_to_pose_client.send_goal_async(goal_msg)
                
                while not send_goal_future.done():
                    if self._cancel_requested or self._pause_requested:
                        return
                    time.sleep(0.1)
                    
                goal_handle = send_goal_future.result()
                if not goal_handle.accepted:
                    self.get_logger().error(f'Goal to {wp_name} was rejected by server')
                    self._publish_nav_status('ERROR', mission_id=mission_id, error_msg='Goal rejected')
                    return
                    
                result_future = goal_handle.get_result_async()

                # Poll until complete or cancelled
                while not result_future.done():
                    if self._cancel_requested:
                        self.get_logger().info(
                            'Cancelling active Nav2 goal...')
                        goal_handle.cancel_goal_async()
                        time.sleep(0.5)
                        self._publish_nav_status(
                            'CANCELLED', mission_id=mission_id)
                        return

                    if self._pause_requested:
                        self.get_logger().info(
                            'Pausing: cancelling active Nav2 goal...')
                        goal_handle.cancel_goal_async()
                        time.sleep(0.5)
                        # Save remaining waypoints (including current one
                        # since we didn't complete it)
                        remaining_poses = goal_poses[local_idx:]
                        remaining_data = waypoints_data[local_idx:]
                        self._paused_waypoints = remaining_poses
                        self._paused_waypoint_data = remaining_data
                        self._paused_mission_id = mission_id
                        self._paused_start_index = start_index + local_idx
                        self.get_logger().info(
                            f'Navigation paused. {len(remaining_poses)} '
                            'waypoint(s) saved for resume.')
                        self._publish_nav_status(
                            'PAUSED', mission_id=mission_id,
                            waypoint_index=start_index + local_idx)
                        return

                    time.sleep(0.2)

                # Check result
                result = result_future.result()
                if result.status == GoalStatus.STATUS_SUCCEEDED:
                    self.get_logger().info(
                        f'Arrived at waypoint [{global_idx}] "{wp_name}"')
                    last_completed_local = local_idx

                    # Publish ARRIVED status with full waypoint data
                    self._publish_nav_status(
                        'ARRIVED', mission_id=mission_id,
                        waypoint_name=wp_name, waypoint_index=global_idx,
                        role=wp_role,
                        playlist=wp_data.get('playlist'),
                        dwell_time=wp_data.get('dwellTimeSeconds'))

                    # Execute role-based dwell behavior
                    self._execute_dwell(wp_data, mission_id, global_idx)

                    # Update current node ID if present
                    if 'nodeId' in wp_data:
                        self._current_node_id = wp_data['nodeId']

                elif result.status == GoalStatus.STATUS_CANCELED:
                    self.get_logger().warning(
                        f'Goal to waypoint [{global_idx}] was canceled.')
                    self._publish_nav_status(
                        'CANCELLED', mission_id=mission_id,
                        waypoint_index=global_idx)
                    return

                elif result.status == GoalStatus.STATUS_ABORTED:
                    self.get_logger().error(
                        f'Goal to waypoint [{global_idx}] was aborted by Nav2.')
                    self._publish_nav_status(
                        'FAILED', mission_id=mission_id,
                        waypoint_index=global_idx,
                        error='Goal aborted by Nav2')
                    return

            # All waypoints completed
            self.get_logger().info(
                f'Mission {mission_id} completed — all '
                f'{len(goal_poses)} waypoint(s) visited.')
            self._publish_nav_status('COMPLETED', mission_id=mission_id, waypoint_index=len(goal_poses) - 1)

        except Exception as e:
            self.get_logger().error(f'Navigation error: {e}')
            self._publish_nav_status(
                'FAILED', mission_id=mission_id,
                error=str(e))
        finally:
            self._navigating = False
            # Return supervisor to IDLE
            self._call_supervisor('idle')

    def _execute_dwell(self, wp_data, mission_id, global_idx):
        """Execute role-based dwell behavior at a waypoint.

        The robot waits at the waypoint while the Android tablet handles
        actual media playback (triggered by the backend forwarding our
        status via SignalR).
        """
        role = wp_data.get('role')
        wp_name = wp_data.get('name', f'Waypoint {global_idx}')

        if role == 'ad':
            dwell = wp_data.get('dwellTimeSeconds', 30)
            must_complete = wp_data.get('mustCompletePlaylist', False)
            playlist = wp_data.get('playlist', [])

            self.get_logger().info(
                f'Ad waypoint "{wp_name}": dwelling {dwell}s '
                f'(playlist: {len(playlist)} item(s), '
                f'mustComplete={must_complete})')

            # Publish PLAYLIST_PLAYING so backend can tell tablet to start
            self._publish_nav_status(
                'PLAYLIST_PLAYING', mission_id=mission_id,
                waypoint_name=wp_name, waypoint_index=global_idx,
                role=role, playlist=playlist,
                dwell_time=dwell)

            # Wait for the dwell time (robot stays still while tablet plays)
            self._interruptible_sleep(dwell)

            # Publish PLAYLIST_COMPLETE
            self._publish_nav_status(
                'PLAYLIST_COMPLETE', mission_id=mission_id,
                waypoint_name=wp_name, waypoint_index=global_idx,
                role=role)

            self.get_logger().info(
                f'Ad dwell complete at "{wp_name}"')

        elif role == 'photo':
            self.get_logger().info(
                f'Photo waypoint "{wp_name}": dwelling 5s')
            self._interruptible_sleep(5)

        elif role == 'guide_stop':
            self.get_logger().info(
                f'Guide stop "{wp_name}": dwelling 10s')
            self._interruptible_sleep(10)

        elif role == 'rest':
            self.get_logger().info(
                f'Rest waypoint "{wp_name}": dwelling 5s')
            self._interruptible_sleep(5)

        elif role is not None and role != '':
            self.get_logger().warning(
                f'Unknown role "{role}" at waypoint "{wp_name}" '
                '— continuing immediately')

    def _interruptible_sleep(self, seconds):
        """Sleep for `seconds`, but wake early if cancel/pause is requested."""
        end_time = time.monotonic() + seconds
        while time.monotonic() < end_time:
            if self._cancel_requested or self._pause_requested:
                break
            time.sleep(0.2)

    # ======================================================================
    # Nav2 helpers
    # ======================================================================

    def _wait_for_nav2(self, timeout_sec=30.0) -> bool:
        """Wait for Nav2 lifecycle nodes to become active.

        Uses the same approach as waypoint_follower.py — poll the
        ``/bt_navigator/get_state`` service instead of
        ``BasicNavigator.waitUntilNav2Active()`` to avoid the rclpy
        executor hanging bug.
        """
        self.get_logger().info('Waiting for Nav2 to become active...')
        from lifecycle_msgs.srv import GetState

        check_nodes = [
            'bt_navigator', 'controller_server',
            'planner_server', 'behavior_server',
        ]
        clients = {
            name: self.create_client(GetState, f'/{name}/get_state')
            for name in check_nodes
        }

        deadline = self.get_clock().now() + Duration(seconds=timeout_sec)
        while rclpy.ok() and self.get_clock().now() < deadline:
            all_active = True
            for name, client in clients.items():
                if not client.service_is_ready():
                    all_active = False
                    continue
                future = client.call_async(GetState.Request())
                end_time_future = time.time() + 2.0
                while not future.done() and time.time() < end_time_future:
                    time.sleep(0.1)
                
                if not future.done():
                    all_active = False
                    continue
                
                result = future.result()
                if result is None or result.current_state.label != 'active':
                    all_active = False

            if all_active:
                self.get_logger().info('All Nav2 nodes are active.')
                return True

            self.get_logger().debug('Nav2 not fully active yet, retrying...')
            time.sleep(1.0)

        self.get_logger().error(
            f'Timed out ({timeout_sec}s) waiting for Nav2 to become active.')
        return False

    def _waypoints_to_poses(self, waypoints_data):
        """Convert backend waypoint dicts to PoseStamped list."""
        poses = []
        now_msg = self.get_clock().now().to_msg()
        for wp in waypoints_data:
            try:
                x = float(wp.get('x', 0))
                y = float(wp.get('y', 0))
                yaw = float(wp.get('yaw', 0))
            except (TypeError, ValueError) as e:
                self.get_logger().error(
                    f'Invalid waypoint coordinates: {wp} — {e}')
                continue

            pose = PoseStamped()
            pose.header.frame_id = 'map'
            pose.header.stamp = now_msg
            pose.pose.position.x = x
            pose.pose.position.y = y
            _, _, qz, qw = _yaw_to_quat(yaw)
            pose.pose.orientation.z = qz
            pose.pose.orientation.w = qw
            poses.append(pose)
        return poses

    # ======================================================================
    # MQTT publishing helpers
    # ======================================================================

    def _publish_nav_status(self, status, *, mission_id='',
                            waypoint_name=None, waypoint_index=None,
                            role=None, playlist=None, dwell_time=None,
                            error=None):
        """Publish navigation status to MQTT.

        Format matches the backend's NavigationStatusMessage model exactly.
        """
        msg = {
            'status': status,
            'timestamp': _utc_iso(),
        }
        if mission_id:
            msg['missionId'] = mission_id
        if waypoint_name is not None:
            msg['waypoint'] = waypoint_name
        if waypoint_index is not None:
            msg['waypointIndex'] = waypoint_index
        if role is not None:
            msg['role'] = role
        if playlist is not None:
            msg['playlist'] = playlist
        if dwell_time is not None:
            msg['dwellTimeSeconds'] = dwell_time
        if error is not None:
            msg['error'] = error

        self._mqtt_publish(self._topic_nav_status, msg)
        self.get_logger().info(
            f'Status → {status}'
            + (f' @ "{waypoint_name}"' if waypoint_name else '')
            + (f' [role={role}]' if role else ''))

    def _publish_log(self, message, level='INFO'):
        """Publish a log message to the robot's MQTT log topic."""
        self._mqtt_publish(self._topic_log, {
            'level': level,
            'message': message,
            'node': 'smb_mqtt_bridge',
            'timestamp': _utc_iso(),
        })

    def _mqtt_publish(self, topic, payload_dict):
        """Publish a JSON dict to an MQTT topic (fire-and-forget)."""
        if not self._mqtt_connected:
            self.get_logger().debug(
                f'MQTT not connected — dropping publish to {topic}')
            return
        try:
            payload_str = json.dumps(payload_dict, ensure_ascii=False)
            self._mqtt_client.publish(topic, payload_str, qos=1)
        except Exception as e:
            self.get_logger().error(f'MQTT publish to {topic} failed: {e}')

    # ======================================================================
    # Supervisor interaction
    # ======================================================================

    def _call_supervisor(self, command):
        """Call the supervisor /supervisor/cmd service (non-blocking)."""
        if not self._supervisor_client.service_is_ready():
            self.get_logger().warning(
                f'Supervisor service not available — skipping {command} command')
            return

        request = SupervisorCmd.Request()
        request.command = command
        future = self._supervisor_client.call_async(request)
        future.add_done_callback(
            lambda f: self._on_supervisor_response(command, f))

    def _on_supervisor_response(self, command, future):
        """Log the supervisor service response."""
        try:
            result = future.result()
            if result.success:
                self.get_logger().info(
                    f'Supervisor → {command}: {result.new_state}')
            else:
                self.get_logger().warning(
                    f'Supervisor → {command} failed: {result.message}')
        except Exception as e:
            self.get_logger().error(f'Supervisor call error: {e}')

    # ======================================================================
    # Cleanup
    # ======================================================================

    def destroy_node(self):
        """Clean up MQTT client and navigator on shutdown."""
        self.get_logger().info('Shutting down smb_mqtt_bridge...')
        self._cancel_requested = True

        # Wait for nav thread to finish
        if self._nav_thread and self._nav_thread.is_alive():
            self.get_logger().info('Waiting for navigation thread to stop...')
            self._nav_thread.join(timeout=5.0)

        # Disconnect MQTT
        try:
            self._publish_log('MQTT bridge shutting down', level='INFO')
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()
        except Exception:
            pass

        super().destroy_node()


def main(args=None) -> int:
    rclpy.init(args=args)
    node = MqttBridge()
    
    # Use a dedicated MultiThreadedExecutor instead of the global default executor.
    # This prevents 'Executor is already spinning' crashes because BasicNavigator
    # hardcodes rclpy.spin_until_future_complete() which grabs the global executor.
    from rclpy.executors import MultiThreadedExecutor
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
