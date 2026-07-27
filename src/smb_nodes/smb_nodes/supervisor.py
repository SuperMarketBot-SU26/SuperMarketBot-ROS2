"""Supervisor state machine for SuperMarketBot (Phase 4).

Sits between upstream controllers (Nav2's ``/cmd_vel_nav``, manual teleop)
and the firmware-facing ``/cmd_vel`` topic. Holds the high-level state of
the robot and gates which velocity commands actually reach the wheels.

States
------
- ``idle``   — pass-through. ``cmd_vel_in`` is republished to ``cmd_vel``.
- ``nav``    — same pass-through as IDLE. Logged so the Android hub can
              tell at a glance that Nav2 is in charge. (Phase 4 has no
              waypoint follower invocation here — that's a separate
              ``waypoint_follower`` executable started by a higher-level
              orchestrator when this state is entered.)
- ``dock``   — STUB. Logged as "not implemented" and falls back to IDLE
              semantics. Will be wired to a docking BT in a later phase.
- ``estop``  — holds zero velocity. No input reaches ``cmd_vel`` until
              the supervisor leaves ESTOP via the ``reset`` command.

Topic / service contract
------------------------
- Subscribes (two inputs, both write to the same cached last_cmd_vel):
  - ``cmd_vel_in_topic`` (default ``/cmd_vel_nav``, geometry_msgs/TwistStamped)
    — Nav2 main/rolling publish this; the type is dictated by Nav2.
  - ``manual_cmd_vel_in_topic`` (default ``/cmd_vel``, geometry_msgs/Twist)
    — manual teleop (WebManager, joystick, keyboard). Skipped if its name
    equals ``cmd_vel_in_topic`` to avoid the DDS "two subs on one topic
    with different types" rejection.
- Subscribes: ``emergency_stop`` (Bool, latched).
- Publishes:  ``cmd_vel`` (geometry_msgs/Twist, RELIABLE — downstream
  ros_gz_bridge and the firmware expect this type). ``supervisor/state``
  (String, latched, TRANSIENT_LOCAL).
- Service:    ``supervisor/cmd`` (smb_msgs/SupervisorCmd).

Why two inputs: Nav2 publishes TwistStamped (its required type), but manual
teleop nodes naturally emit plain Twist on the contract topic ``/cmd_vel``.
Forcing every teleop publisher to switch to TwistStamped is needless busywork
and breaks the contract that says ``/cmd_vel`` is plain Twist. Instead, the
supervisor accepts both and normalizes into a single cached velocity. The
output timer keeps republishing the cached value so a single tap on a button
isn't a one-shot motion — the firmware keeps receiving a velocity command
until either the upstream publishes a fresh (nonzero or zero) one.

Default topics match the values in ``docs/TOPIC_CONTRACT.md`` where they
overlap (``/cmd_vel``); the supervisor-owned topics are namespaced
``/supervisor/...`` and the estop input is ``/emergency_stop`` to match
the Android hub's expected interface.

E-stop precedence
-----------------
The ``/emergency_stop`` topic is the HARD kill switch: a ``True`` value
forces the FSM into ESTOP regardless of the current state, and only a
``False`` value (combined with the ``reset`` service call) lets the FSM
leave ESTOP. This means an Android-side "ESTOP" button + a hardware
e-stop GPIO both reach the same node through the same topic, and the
service interface is the only sanctioned way to leave ESTOP — there is
no autodowngrade after the topic goes back to ``False``.
"""

import enum
from typing import Optional

import rclpy
from geometry_msgs.msg import Twist, TwistStamped
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from smb_msgs.srv import SupervisorCmd
from std_msgs.msg import Bool, String


class State(str, enum.Enum):
    """FSM states. Values are the string identifiers exposed on the wire."""

    IDLE = 'idle'
    NAV = 'nav'
    DOCK = 'dock'
    ESTOP = 'estop'


# Allow list of incoming service commands. Keep in sync with SupervisorCmd.srv.
_VALID_COMMANDS = {State.IDLE.value, State.NAV.value,
                   State.DOCK.value, State.ESTOP.value, 'reset'}


class Supervisor(Node):
    """Gating state machine for ``/cmd_vel``."""

    def __init__(self):
        super().__init__('supervisor')

        # ---- Parameters (all overridable at launch via --ros-args -p ...) ----
        self.declare_parameter('cmd_vel_in_topic', '/cmd_vel_nav')
        # Optional second input for manual/teleop publishers that emit
        # geometry_msgs/Twist (not TwistStamped) on the contract topic /cmd_vel.
        # WebManager, joystick_teleop, keyboard_teleop etc. publish here.
        # Both inputs feed the same _last_cmd_vel cache; the output timer
        # keeps republishing so a single tap isn't a one-shot motion.
        self.declare_parameter('manual_cmd_vel_in_topic', '/cmd_vel')
        self.declare_parameter('cmd_vel_out_topic', '/cmd_vel')
        self.declare_parameter('state_topic', '/supervisor/state')
        self.declare_parameter('estop_topic', '/emergency_stop')
        self.declare_parameter('cmd_service', '/supervisor/cmd')
        # How often to republish the current state, even when no transition
        # happened — useful for late-joining subscribers on TRANSIENT_LOCAL.
        self.declare_parameter('state_publish_period_sec', 1.0)

        cmd_vel_in = self.get_parameter('cmd_vel_in_topic').value
        cmd_vel_out = self.get_parameter('cmd_vel_out_topic').value
        state_topic = self.get_parameter('state_topic').value
        estop_topic = self.get_parameter('estop_topic').value
        cmd_service = self.get_parameter('cmd_service').value
        period_sec = self.get_parameter('state_publish_period_sec').value

        # ---- State ----
        self._state = State.IDLE
        # Most recent input velocity. We hold the last one so we keep
        # republishing it on a timer (consistent output) AND we can override
        # to zero on ESTOP. Without buffering, the bridge would only see
        # velocity when an upstream node publishes.
        self._last_cmd_vel = Twist()
        self._estop_latched = False  # latched from /emergency_stop latched topic

        # ---- QoS profiles ----
        # cmd_vel is RELIABLE per the topic contract.
        cmd_vel_qos = QoSProfile(
            depth=10, reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.VOLATILE)
        # State and estop are latched: late joiners (Android hub that
        # connects after a state change) should get the current value.
        latched_qos = QoSProfile(
            depth=1, reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL)

        # ---- I/O ----
        # Nav2 main (and rolling) publishes geometry_msgs/TwistStamped on the
        # controller output topic (see smb_nav2_minimal.launch.py which remaps
        # controller_server's internal cmd_vel -> cmd_vel_nav). The contract
        # publishes geometry_msgs/Twist on /cmd_vel for the ros_gz_bridge and
        # firmware, so the supervisor normalizes TwistStamped -> Twist and
        # caches it as _last_cmd_vel; the output timer publishes the cached
        # value at state_publish_period_sec.
        self._cmd_vel_in_sub = self.create_subscription(
            TwistStamped, cmd_vel_in, self._on_cmd_vel_in_stamped, cmd_vel_qos)
        # Manual/teleop input: plain Twist on the contract topic /cmd_vel.
        # Created only if the topic name differs from cmd_vel_in_topic to
        # avoid subscribing twice to the same topic with different types
        # (DDS would reject it).
        manual_cmd_vel_in = self.get_parameter('manual_cmd_vel_in_topic').value
        self._manual_cmd_vel_in_sub = None
        if manual_cmd_vel_in and manual_cmd_vel_in != cmd_vel_in:
            self._manual_cmd_vel_in_sub = self.create_subscription(
                Twist, manual_cmd_vel_in, self._on_cmd_vel_in_plain, cmd_vel_qos)
        self._estop_sub = self.create_subscription(
            Bool, estop_topic, self._on_estop, latched_qos)
        self._cmd_vel_out_pub = self.create_publisher(
            Twist, cmd_vel_out, cmd_vel_qos)
        self._state_pub = self.create_publisher(
            String, state_topic, latched_qos)
        self._cmd_service = self.create_service(
            SupervisorCmd, cmd_service, self._on_cmd_service)

        # Republish current state on a timer. Initial publish below is
        # the "latched" value; the timer keeps it fresh.
        self._state_timer = self.create_timer(
            period_sec, self._publish_state)
        self._publish_state()  # immediate latched publish for late joiners

        # Output timer: re-publish the last command at the same period so
        # the bridge keeps getting velocity while a controller is silent.
        # In ESTOP, _last_cmd_vel is forced to zero.
        self._output_timer = self.create_timer(
            period_sec, self._publish_cmd_vel)

        self.get_logger().info(
            f'Supervisor started: state={self._state.value}, '
            f'in={cmd_vel_in}, out={cmd_vel_out}, '
            f'estop={estop_topic}, service={cmd_service}')

    # ---- Callbacks ----

    def _on_cmd_vel_in_stamped(self, msg: TwistStamped) -> None:
        """Cache the latest upstream TwistStamped command (Nav2 main/rolling).

        Normalize to a plain Twist — the contract topic ``/cmd_vel`` is
        ``geometry_msgs/Twist`` and downstream (ros_gz_bridge, firmware)
        expects that type. We discard the stamp and header.
        """
        plain = Twist()
        plain.linear = msg.twist.linear
        plain.angular = msg.twist.angular
        self._last_cmd_vel = plain

    def _on_cmd_vel_in_plain(self, msg: Twist) -> None:
        """Cache the latest manual/teleop Twist command.

        This is the path used by WebManager, joystick_teleop, keyboard_teleop
        etc. that publish geometry_msgs/Twist on the contract topic /cmd_vel.
        Both inputs share the same _last_cmd_vel cache so the output timer
        keeps republishing until a fresh command arrives or the user releases.
        """
        self._last_cmd_vel = msg

    def _on_estop(self, msg: Bool) -> None:
        """Latched ESTOP from /emergency_stop. True forces ESTOP state."""
        new_latched = bool(msg.data)
        if new_latched == self._estop_latched:
            return
        self._estop_latched = new_latched
        if new_latched:
            self._enter_estop(reason=f'/emergency_stop True')
        # We do NOT auto-leave ESTOP on /emergency_stop going False —
        # the service 'reset' command is the only sanctioned exit.

    def _on_cmd_service(self, request, response):
        """Handle /supervisor/cmd requests. See SupervisorCmd.srv for the API."""
        response.new_state = self._state.value
        cmd = (request.command or '').strip().lower()
        if cmd not in _VALID_COMMANDS:
            response.success = False
            response.message = (
                f"unknown command {request.command!r}; "
                f"expected one of {sorted(_VALID_COMMANDS)}")
            return response

        # From ESTOP, only 'reset' is allowed (and only if /emergency_stop
        # is currently False — hardware e-stop still in effect blocks
        # the exit even via service).
        if self._state is State.ESTOP:
            if cmd != 'reset':
                response.success = False
                response.message = (
                    'in ESTOP; only the reset command is accepted')
                return response
            if self._estop_latched:
                response.success = False
                response.message = (
                    'in ESTOP and /emergency_stop is True; clear the hardware '
                    'e-stop before calling reset')
                return response
            self._enter_idle(reason="service 'reset'")
        else:
            if cmd == 'reset':
                # reset outside ESTOP is a no-op success; report current state.
                response.success = True
                response.message = 'reset is a no-op outside ESTOP'
                response.new_state = self._state.value
                return response
            if cmd == 'idle':
                self._enter_idle(reason="service 'idle'")
            elif cmd == 'nav':
                self._enter_nav(reason="service 'nav'")
            elif cmd == 'dock':
                self._enter_dock(reason="service 'dock'")
            elif cmd == 'estop':
                self._enter_estop(reason="service 'estop'")

        response.success = True
        response.message = 'ok'
        response.new_state = self._state.value
        return response

    # ---- State transitions (all log + latched-publish) ----

    def _enter_idle(self, reason: str) -> None:
        if self._state is State.IDLE:
            return
        self.get_logger().info(f'IDLE <- {self._state.value} ({reason})')
        self._state = State.IDLE
        self._publish_state()

    def _enter_nav(self, reason: str) -> None:
        if self._state is State.NAV:
            return
        self.get_logger().info(f'NAV <- {self._state.value} ({reason})')
        self._state = State.NAV
        self._publish_state()

    def _enter_dock(self, reason: str) -> None:
        # DOCK is a stub in Phase 4: we accept the command but stay in IDLE
        # semantics. The next phase will wire this to a docking BT.
        if self._state is State.DOCK:
            return
        self.get_logger().warning(
            f"DOCK requested ({reason}) — not implemented in Phase 4; "
            f'staying in {self._state.value}.')
        # We don't actually transition the state to DOCK because that would
        # be a lie. The service response reports the *actual* state (IDLE),
        # so the caller can detect the stub and retry later.
        # See SupervisorCmd.srv comments for the orchestrator contract.

    def _enter_estop(self, reason: str) -> None:
        if self._state is State.ESTOP:
            return
        self.get_logger().warning(f'ESTOP <- {self._state.value} ({reason})')
        self._state = State.ESTOP
        # Force the next publish to be zero even if the upstream controller
        # is still streaming.
        self._last_cmd_vel = Twist()
        self._publish_state()

    # ---- Periodic publishers ----

    def _publish_cmd_vel(self) -> None:
        """Republish the cached input as the contract cmd_vel, gated by state.

        In ESTOP we publish a zero Twist instead of the cached input so
        the firmware/wheels get a hard stop even if Nav2 keeps streaming.
        In IDLE/NAV we pass through; DOCK is currently identical to IDLE.
        """
        out = Twist()
        if self._state is not State.ESTOP:
            out = self._last_cmd_vel
        self._cmd_vel_out_pub.publish(out)

    def _publish_state(self) -> None:
        msg = String()
        msg.data = self._state.value
        self._state_pub.publish(msg)


def main(args=None) -> int:
    rclpy.init(args=args)
    node = Supervisor()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
