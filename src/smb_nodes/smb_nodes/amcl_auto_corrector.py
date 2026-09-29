#!/usr/bin/env python3
"""amcl_auto_corrector.py — Automatic AMCL Pose Correction on Nav2 Goal Arrival.

Listens to Nav2 action statuses (/navigate_to_pose/_action/status and
/navigate_through_poses/_action/status). Whenever an autonomous navigation
goal successfully arrives (STATUS_SUCCEEDED), it waits briefly for the
robot to settle to a halt, then fires a burst of stationary likelihood-field
updates to AMCL via /request_nomotion_update.

This snaps the particle filter and LaserScan alignment flush to the static map
walls, eliminating skid-steer odometry drift upon arrival at waypoints and goals.
"""

import sys
import threading
import time
from typing import Set

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSDurabilityPolicy
from action_msgs.msg import GoalStatus, GoalStatusArray
from geometry_msgs.msg import Twist
from std_srvs.srv import Empty


class AmclAutoCorrector(Node):
    """Monitors Nav2 goal completion and triggers AMCL stationary updates."""

    def __init__(self):
        super().__init__('amcl_auto_corrector')

        # ---- Parameters ----
        self.declare_parameter('pulse_count', 3)
        self.declare_parameter('pulse_interval_sec', 0.25)
        self.declare_parameter('settle_delay_sec', 0.35)
        self.declare_parameter('velocity_threshold', 0.03)
        self.declare_parameter('enabled', True)

        self._pulse_count = self.get_parameter('pulse_count').value
        self._pulse_interval_sec = self.get_parameter('pulse_interval_sec').value
        self._settle_delay_sec = self.get_parameter('settle_delay_sec').value
        self._velocity_threshold = self.get_parameter('velocity_threshold').value
        self._enabled = self.get_parameter('enabled').value

        # ---- State tracking ----
        self._active_goals: Set[bytes] = set()
        self._is_correcting = False
        self._lock = threading.Lock()
        self._last_cmd_vel = Twist()

        # ---- QoS Profiles ----
        # Action status topics typically use default reliable QoS
        action_status_qos = QoSProfile(
            depth=10,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE
        )
        cmd_vel_qos = QoSProfile(
            depth=10,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE
        )

        # ---- AMCL Service Client ----
        self._nomotion_client = self.create_client(Empty, '/request_nomotion_update')

        # ---- Action Status Subscriptions ----
        self._sub_nav_to_pose = self.create_subscription(
            GoalStatusArray,
            '/navigate_to_pose/_action/status',
            lambda msg: self._on_goal_status(msg, 'NavigateToPose'),
            action_status_qos
        )

        self._sub_nav_through_poses = self.create_subscription(
            GoalStatusArray,
            '/navigate_through_poses/_action/status',
            lambda msg: self._on_goal_status(msg, 'NavigateThroughPoses'),
            action_status_qos
        )

        # ---- Velocity Monitor Subscription ----
        self._sub_cmd_vel = self.create_subscription(
            Twist,
            '/cmd_vel',
            self._on_cmd_vel,
            cmd_vel_qos
        )

        # ---- Service to trigger correction on demand ----
        self._trigger_srv = self.create_service(
            Empty,
            '/amcl/trigger_correction',
            self._on_manual_trigger
        )

        self.get_logger().info(
            f'AMCL Auto-Corrector initialized (pulses={self._pulse_count}, '
            f'interval={self._pulse_interval_sec}s, settle={self._settle_delay_sec}s).')

    def _on_cmd_vel(self, msg: Twist) -> None:
        self._last_cmd_vel = msg

    def _is_moving(self) -> bool:
        lin = abs(self._last_cmd_vel.linear.x) + abs(self._last_cmd_vel.linear.y)
        ang = abs(self._last_cmd_vel.angular.z)
        return (lin > self._velocity_threshold) or (ang > self._velocity_threshold)

    def _on_goal_status(self, msg: GoalStatusArray, action_name: str) -> None:
        if not self._enabled:
            return

        for gs in msg.status_list:
            gid = bytes(gs.goal_info.goal_id.uuid)
            st = gs.status

            if st in (GoalStatus.STATUS_ACCEPTED, GoalStatus.STATUS_EXECUTING):
                if gid not in self._active_goals:
                    self._active_goals.add(gid)
                    self.get_logger().debug(
                        f'[{action_name}] Goal {gid.hex()[:8]} is active.')

            elif st == GoalStatus.STATUS_SUCCEEDED:
                if gid in self._active_goals:
                    self._active_goals.remove(gid)
                    self.get_logger().info(
                        f'🏁 [{action_name}] Goal {gid.hex()[:8]} SUCCEEDED. '
                        f'Triggering automatic AMCL pose correction!')
                    self._trigger_correction_async(reason=f'{action_name} goal completed')

            elif st in (GoalStatus.STATUS_CANCELED, GoalStatus.STATUS_ABORTED):
                if gid in self._active_goals:
                    self._active_goals.remove(gid)

    def _on_manual_trigger(self, request: Empty.Request, response: Empty.Response) -> Empty.Response:
        self.get_logger().info('Manual AMCL pose correction requested via service.')
        self._trigger_correction_async(reason='manual service call')
        return response

    def _trigger_correction_async(self, reason: str) -> None:
        thread = threading.Thread(
            target=self._run_correction_worker,
            args=(reason,),
            daemon=True
        )
        thread.start()

    def _run_correction_worker(self, reason: str) -> None:
        with self._lock:
            if self._is_correcting:
                self.get_logger().info(
                    '[AMCL Auto-Corrector] Correction already running; skipping duplicate trigger.')
                return
            self._is_correcting = True

        try:
            # 1. Wait for physical deceleration and chassis settle
            if self._settle_delay_sec > 0:
                time.sleep(self._settle_delay_sec)

            # 2. Check if AMCL service is reachable
            if not self._nomotion_client.service_is_ready():
                if not self._nomotion_client.wait_for_service(timeout_sec=1.5):
                    self.get_logger().warn(
                        '⚠️ AMCL /request_nomotion_update service not ready. (Is AMCL running?)')
                    return

            self.get_logger().info(
                f'🎯 [AMCL Auto-Corrector] Commencing {self._pulse_count}-pulse stationary pose correction ({reason})...')

            # 3. Fire consecutive pulses to update particle weights & likelihood field
            for pulse in range(1, self._pulse_count + 1):
                if self._is_moving():
                    self.get_logger().info(
                        '[AMCL Auto-Corrector] Robot moved during correction; aborting remaining pulses.')
                    break

                req = Empty.Request()
                self._nomotion_client.call_async(req)
                self.get_logger().info(
                    f'🎯 [AMCL Auto-Corrector] Pulse {pulse}/{self._pulse_count} sent to /request_nomotion_update.')

                if pulse < self._pulse_count:
                    time.sleep(self._pulse_interval_sec)

            self.get_logger().info(
                '✅ [AMCL Auto-Corrector] AMCL stationary pose correction complete! Particles and laser scan snapped to map.')

        except Exception as e:
            self.get_logger().error(f'[AMCL Auto-Corrector] Error during correction: {e}')
        finally:
            with self._lock:
                self._is_correcting = False


def main(args=None):
    rclpy.init(args=args)
    node = AmclAutoCorrector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
