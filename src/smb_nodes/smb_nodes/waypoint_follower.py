"""Waypoint follower for SuperMarketBot.

Sends a list of PoseStamped goals to Nav2 via the ``/follow_waypoints``
action server and waits for the result. Uses the high-level
``nav2_simple_commander.BasicNavigator`` API rather than raw action calls —
matches the upstream ``example_waypoint_follower.py`` pattern but is
parameterised so the waypoint list can be overridden at launch time without
editing this file.

Run:

    ros2 run smb_nodes waypoint_follower

Waypoints come from the ``waypoints`` ROS parameter, a YAML list of dicts
with ``{x, y, yaw}`` in the ``map`` frame. Default targets stay inside the
sim aisle (the SMB sim world puts shelf rows at x = ±1.5 and walls at
x = ±5, y = ±5 — a 2 m forward / 2 m reverse swap tests goal sequencing and
recovery behavior on a sim-restricted path).

The SMB topic contract uses ``/odom`` (raw, from DiffDrive) for sim and
``/odometry/filtered`` (from robot_localization EKF) for the real robot;
Nav2's params file (not this script) decides which topic to read.

NOTE: This script only sends goals — Nav2 must already be running
(nav2_bringup must have been started with the right params file). When
launched alongside ``smb_sim.launch.py use_nav2:=true``, this works out
of the box. When launched standalone, the user must start Nav2 first.
"""

from typing import List

import rclpy
from geometry_msgs.msg import PoseStamped
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from rclpy.duration import Duration
from rclpy.node import Node


def _yaw_to_quat(yaw: float):
    """Convert a 2D yaw (rad) to a (x, y, z, w) quaternion."""
    half = yaw * 0.5
    return (0.0, 0.0, __import__('math').sin(half), __import__('math').cos(half))


def _parse_waypoint_string(s: str):
    """Parse one waypoint string of the form 'x,y[,yaw]'.

    ROS2 parameter arrays only accept primitives, so we encode each waypoint
    as a single string with comma-separated fields instead of trying to use
    a nested dict (which rclpy rejects at declare_parameter time).
    """
    parts = [p.strip() for p in s.split(',')]
    if len(parts) not in (2, 3):
        raise ValueError(
            f"waypoint {s!r} must be 'x,y' or 'x,y,yaw'; got {len(parts)} fields"
        )
    x = float(parts[0])
    y = float(parts[1])
    yaw = float(parts[2]) if len(parts) == 3 else 0.0
    return {'x': x, 'y': y, 'yaw': yaw}


class WaypointFollower(Node):
    def __init__(self):
        super().__init__('waypoint_follower')

        # Default waypoints: a 2-point demo inside the sim aisle.
        # SMB sim world puts shelf rows at x = ±1.5 and walls at x = ±5,
        # so a 2 m forward / 2 m reverse swap stays inside the navigable area.
        #
        # Each waypoint is one string "x,y[,yaw]". Override via launch file:
        #   ros2 run smb_nodes waypoint_follower --ros-args \
        #     -p waypoints:="['1.0,0.0,0.0', '-1.0,0.0,3.14']"
        self.declare_parameter('waypoints', ['2.0,0.0,0.0', '-2.0,0.0,3.14159'])
        # Hard wall-clock timeout for the whole waypoint sequence (s).
        # Default: 600s = 10 minutes — plenty for a sim demo; tune down
        # for real-time guarantees.
        self.declare_parameter('timeout_sec', 600.0)

        self._navigator = BasicNavigator()
        self._waypoints = self._load_waypoints()
        self._timeout = Duration(seconds=self.get_parameter('timeout_sec').value)
        self.get_logger().info(
            f'Loaded {len(self._waypoints)} waypoint(s); waiting for Nav2 to be active.')

    def _load_waypoints(self) -> List[PoseStamped]:
        """Read the ``waypoints`` param and convert each entry to a PoseStamped."""
        raw = self.get_parameter('waypoints').value
        now_msg = self.get_clock().now().to_msg()
        poses = []
        for i, wp in enumerate(raw):
            try:
                parsed = _parse_waypoint_string(wp)
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    f'waypoints[{i}] is malformed: {wp!r} '
                    f"(expected 'x,y' or 'x,y,yaw')"
                ) from exc
            pose = PoseStamped()
            pose.header.frame_id = 'map'
            pose.header.stamp = now_msg
            pose.pose.position.x = parsed['x']
            pose.pose.position.y = parsed['y']
            qx, qy, qz, qw = _yaw_to_quat(parsed['yaw'])
            pose.pose.orientation.z = qz
            pose.pose.orientation.w = qw
            poses.append(pose)
        return poses

    def run(self) -> int:
        # Block until Nav2 fully active. We do a synchronous poll on
        # /bt_navigator/get_state ourselves instead of calling
        # BasicNavigator.waitUntilNav2Active(): the commander wrapper uses
        # `rclpy.spin_until_future_complete` on a BasicNavigator node that we
        # created INSIDE our own node's `__init__`, and that path hangs in
        # lyrical. The service IS reachable — `/bt_navigator/get_state`
        # returns `active` immediately under `ros2 service call` — so we
        # just call it directly through our node's executor. ~10ms per check.
        self.get_logger().info('Waiting for Nav2 components to become active.')
        from lifecycle_msgs.srv import GetState  # noqa: PLC0415 — local import
        get_state_clients = {
            name: self.create_client(GetState, f'/{name}/get_state')
            for name in ('bt_navigator', 'controller_server', 'planner_server',
                          'behavior_server', 'waypoint_follower', 'slam_toolbox')
        }
        # Wait until all services are reachable AND all are active.
        deadline = self.get_clock().now() + Duration(seconds=30.0)
        import time as _time
        while rclpy.ok() and self.get_clock().now() < deadline:
            all_ready = True
            states = {}
            for name, client in get_state_clients.items():
                if not client.service_is_ready():
                    all_ready = False
                    states[name] = 'no-service'
                    continue
                future = client.call_async(GetState.Request())
                rclpy.spin_until_future_complete(self, future, timeout_sec=1.0)
                res = future.result()
                states[name] = res.current_state.label if res else 'no-response'
                if states[name] != 'active':
                    all_ready = False
            if all_ready:
                self.get_logger().info('All Nav2 nodes are active.')
                break
            self.get_logger().info(
                f'Nav2 not all-active yet: {states}; retrying.')
            _time.sleep(1.0)
        else:
            self.get_logger().error(
                'Timed out (30s) waiting for Nav2 to come up — bailing.')
            return 4

        self.get_logger().info(f'Sending {len(self._waypoints)} waypoint(s) to Nav2.')
        start = self._navigator.get_clock().now()
        task = self._navigator.followWaypoints(self._waypoints)

        feedback_count = 0
        while not self._navigator.isTaskComplete(task=task):
            feedback = self._navigator.getFeedback(task=task)
            if feedback is not None and feedback_count % 5 == 0:
                self.get_logger().info(
                    f'Executing waypoint {feedback.current_waypoint + 1}/'
                    f'{len(self._waypoints)}')
            feedback_count += 1

            if self._navigator.get_clock().now() - start > self._timeout:
                self.get_logger().warning('Waypoint sequence timed out — cancelling.')
                self._navigator.cancelTask()
                break

            rclpy.spin_once(self, timeout_sec=0.1)

        result = self._navigator.getResult()
        if result == TaskResult.SUCCEEDED:
            self.get_logger().info('Goal succeeded!')
            return 0
        if result == TaskResult.CANCELED:
            self.get_logger().warning('Goal was canceled.')
            return 1
        if result == TaskResult.FAILED:
            code, msg = self._navigator.getTaskError()
            self.get_logger().error(f'Goal failed: {code}: {msg}')
            return 2
        self.get_logger().error('Goal has an invalid return status.')
        return 3


def main(args=None):
    rclpy.init(args=args)
    node = WaypointFollower()
    try:
        rc = node.run()
    except KeyboardInterrupt:
        node.get_logger().info('Interrupted by user — shutting down.')
        rc = 130
    finally:
        # NB: BasicNavigator.lifecycleShutdown() shuts down the *whole* nav2
        # system (controller_server, planner_server, bt_navigator, ...) — fine
        # if we own the nav2 bringup, but in our setup nav2_bringup's
        # lifecycle_manager owns those nodes. We must NOT shut them down or
        # slam_toolbox / nav2_container die and RViz loses the costmap.
        # Destroying our own node + the navigator's BasicNavigator internal
        # node is enough cleanup.
        node.destroy_node()
        rclpy.shutdown()
    return rc


if __name__ == '__main__':
    raise SystemExit(main())