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
- ``dock``   — STUB. Logged as "not implemented" and stays in whatever
              state the FSM was already in (we don't actually transition
              to DOCK because that would be a lie — the service response
              reports the *actual* current state, so the caller can detect
              the stub and retry later). Pass-through is identical to
              IDLE/NAV in ``_publish_cmd_vel``, so if DOCK is requested
              from IDLE the practical effect matches "IDLE semantics".
              If requested from NAV, the FSM stays in NAV (no transition)
              — orchestrators reading ``supervisor/state`` will see NAV
              and should treat that as the stub being a no-op.
- ``estop``  — holds zero velocity. No input reaches ``cmd_vel`` until
              the supervisor leaves ESTOP via the ``reset`` command.
              (See "Cache overwrite during ESTOP" note below — input
              callbacks must refuse to refresh the cache in this state.)

Topic / service contract
------------------------
- Subscribes (two inputs, both write to the same cached last_cmd_vel):
  - ``cmd_vel_in_topic`` (default ``/cmd_vel_nav``, geometry_msgs/TwistStamped)
    — Nav2 main/rolling publish this; the type is dictated by Nav2.
  - ``manual_cmd_vel_in_topic`` (default ``/cmd_vel_manual``, geometry_msgs/Twist)
    — manual teleop (WebManager, joystick, keyboard). The default is
    intentionally **distinct** from ``cmd_vel_out_topic`` — sharing them
    was a safety hole: the manual subscription received the supervisor's
    own published output back as fresh input, which (a) defeated the
    ``cmd_vel_timeout_sec`` watchdog (every republish refreshed
    ``_last_cmd_vel_stamp``) and (b) meant any external publisher on the
    shared topic was publishing directly to the firmware-facing topic,
    bypassing the ESTOP gate. Skipped if its name equals either
    ``cmd_vel_in_topic`` (DDS rejects two subs with different types) or
    ``cmd_vel_out_topic`` (loopback — log an error and skip).
- Subscribes: ``emergency_stop`` (Bool, latched).
- Publishes:  ``cmd_vel`` (geometry_msgs/Twist, RELIABLE — downstream
  ros_gz_bridge and the firmware expect this type). ``supervisor/state``
  (String, latched, TRANSIENT_LOCAL).
- Service:    ``supervisor/cmd`` (smb_msgs/SupervisorCmd).

Why two inputs: Nav2 publishes TwistStamped (its required type), but manual
teleop nodes naturally emit plain Twist. Forcing every teleop publisher to
switch to TwistStamped is needless busywork. Instead, the supervisor
accepts both and normalizes into a single cached velocity. The output
timer keeps republishing the cached value so a single tap on a button
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

Cache overwrite during ESTOP
-----------------------------
When ESTOP is active, the output timer publishes a zero Twist regardless
of what's in the cache — so a fresh nonzero input from Nav2/teleop can't
reach the wheels during ESTOP. BUT: the cache is still updated by the
input callbacks, so the moment ``reset`` transitions back to IDLE, the
next output tick would republish whatever stale/overwritten velocity
happens to be cached. ``_on_cmd_vel_in_stamped`` and ``_on_cmd_vel_in_plain``
explicitly refuse to update ``_last_cmd_vel`` while in ESTOP — the
supervisor zero-on-entry is preserved until reset.
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
        # geometry_msgs/Twist (not TwistStamped). Default is intentionally
        # DISTINCT from ``cmd_vel_out_topic`` — sharing the same topic
        # created a real safety hole (see supervisor.py module docstring):
        # the supervisor's manual subscription would receive its OWN
        # published output back as "fresh input", which (a) defeated the
        # ``cmd_vel_timeout_sec`` watchdog because every republish refreshed
        # ``_last_cmd_vel_stamp`` and (b) meant any external publisher on
        # ``/cmd_vel`` (the manual-input path) was publishing to the same
        # topic the firmware/ros_gz_bridge subscribes to for the GATED
        # output — bypassing the ESTOP gate. Teleop must now remap its
        # ``cmd_vel`` output to ``/cmd_vel_manual`` (see test_teleop.sh).
        self.declare_parameter('manual_cmd_vel_in_topic', '/cmd_vel_manual')
        self.declare_parameter('cmd_vel_out_topic', '/cmd_vel')
        self.declare_parameter('state_topic', '/supervisor/state')
        self.declare_parameter('estop_topic', '/emergency_stop')
        self.declare_parameter('cmd_service', '/supervisor/cmd')
        # How often to republish the current state, even when no transition
        # happened — useful for late-joining subscribers on TRANSIENT_LOCAL.
        self.declare_parameter('state_publish_period_sec', 0.1)
        # Cmd_vel input watchdog: if no fresh /cmd_vel within this many seconds,
        # force _last_cmd_vel to zero on the next publish. Without this, the
        # supervisor keeps republishing the last cached value forever — when
        # teleop releases a key, robot keeps driving.
        #
        # Constraint: cmd_vel_timeout_sec MUST BE > state_publish_period_sec.
        # Suppose teleop publishes one key-press, then stops for a few hundred
        # ms (keyboard auto-repeat phase-out). The next supervisor republish
        # tick happens. The cmd_vel cache age at that moment is
        # (state_publish_period_sec - eps). If the timeout is smaller than
        # that, the watchdog fires and the robot stops mid-drive — producing
        # the "robot jitters in tiny steps" symptom rather than smooth motion.
        # Default timeout is set to 2 s, well above the 100 ms republish period,
        # so any cache age < 2 s is considered fresh and the robot drives
        # continuously while teleop keys are held.
        self.declare_parameter('cmd_vel_timeout_sec', 2.0)

        cmd_vel_in = self.get_parameter('cmd_vel_in_topic').value
        cmd_vel_out = self.get_parameter('cmd_vel_out_topic').value
        state_topic = self.get_parameter('state_topic').value
        estop_topic = self.get_parameter('estop_topic').value
        cmd_service = self.get_parameter('cmd_service').value
        period_sec = self.get_parameter('state_publish_period_sec').value
        self._cmd_vel_timeout_sec = self.get_parameter('cmd_vel_timeout_sec').value

        # ---- State ----
        self._state = State.IDLE
        # Most recent input velocity. We hold the last one so we keep
        # republishing it on a timer (consistent output) AND we can override
        # to zero on ESTOP. Without buffering, the bridge would only see
        # velocity when an upstream node publishes.
        self._last_cmd_vel = Twist()
        # ROS2 builtin time, used by the cmd_vel watchdog.
        self._last_cmd_vel_stamp = self.get_clock().now()
        self._estop_latched = False  # latched from /emergency_stop latched topic
        # Teleop override window: when teleop publishes, block Nav2 input
        # for this many seconds. Prevents Nav2 behavior_server (spin/backup)
        # from fighting teleop by overwriting _last_cmd_vel on every tick.
        self._teleop_override_sec = 2.0
        self._teleop_override_until = self.get_clock().now()
        # Explicit stop flag: when teleop sends lin=0 (key released), we set
        # this flag and stop publishing *any* cmd_vel (not just zero). The
        # ESP32's own 500 ms watchdog will stop the robot if teleop disappears.
        # Without this flag, supervisor republishes lin=0 at 10 Hz between
        # teleop key presses — triggering botStop() on every republish tick
        # and causing the robot to take micro-steps instead of smooth motion.
        # Clear this flag on the next non-zero command.
        self._stop_requested = False

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
        # Manual/teleop input: plain Twist on the manual-input topic. Default
        # is ``/cmd_vel_manual`` (distinct from ``/cmd_vel``) — see module
        # docstring for why sharing the output topic name is a safety hole.
        # Created only if its name differs from both ``cmd_vel_in_topic``
        # (DDS rejects two subs on one topic with different types) and
        # ``cmd_vel_out_topic`` (the supervisor's own loopback would
        # refresh ``_last_cmd_vel_stamp`` every publish tick, defeating
        # the ``cmd_vel_timeout_sec`` watchdog AND letting any external
        # ``/cmd_vel`` publisher bypass the ESTOP gate). Either collision
        # is logged as an error and the manual sub is skipped.
        manual_cmd_vel_in = self.get_parameter('manual_cmd_vel_in_topic').value
        self._manual_cmd_vel_in_sub = None
        if not manual_cmd_vel_in:
            self.get_logger().info(
                'manual_cmd_vel_in_topic is empty — manual/teleop input disabled.')
        elif manual_cmd_vel_in == cmd_vel_in:
            self.get_logger().error(
                f'manual_cmd_vel_in_topic ({manual_cmd_vel_in!r}) equals '
                f'cmd_vel_in_topic ({cmd_vel_in!r}); DDS would reject two '
                'subscriptions on one topic with different types '
                '(Twist vs TwistStamped). Manual input disabled — '
                'publish teleop to a distinct topic, e.g. /cmd_vel_manual.')
        elif manual_cmd_vel_in == cmd_vel_out:
            self.get_logger().error(
                f'manual_cmd_vel_in_topic ({manual_cmd_vel_in!r}) equals '
                f'cmd_vel_out_topic ({cmd_vel_out!r}); this would create a '
                'self-loopback where the supervisor receives its own '
                'published output back as "fresh input", defeating the '
                'cmd_vel_timeout_sec watchdog AND letting any external '
                '/cmd_vel publisher bypass the ESTOP gate. Manual input '
                'disabled — publish teleop to a distinct topic, e.g. '
                '/cmd_vel_manual. (See supervisor.py docstring.)')
        else:
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

        In ESTOP we ignore the input rather than refreshing the cache:
        ``_enter_estop`` zeros ``_last_cmd_vel`` once and ``_publish_cmd_vel``
        overrides the cache with a zero Twist every tick, so the cache is
        irrelevant during ESTOP. But if we kept refreshing it here, the
        moment ``reset`` transitions back to IDLE the next output tick
        would republish whatever stale/nonzero velocity happens to be
        cached — causing motion-on-reset without any new operator input.

        Teleop override: Nav2 behavior_server (spin/backup) constantly ticks
        nonzero angular vel on /cmd_vel_nav even with no active goal. Without
        this guard, every Nav2 tick overwrites the teleop command cached from
        /cmd_vel_manual, causing the robot to barely move while teleop is held.
        """
        if self._state is State.ESTOP:
            return
        # Block Nav2 input if teleop was active recently
        now = self.get_clock().now()
        if now < self._teleop_override_until:
            return
        plain = Twist()
        plain.linear = msg.twist.linear
        plain.angular = msg.twist.angular
        self._last_cmd_vel = plain
        self._last_cmd_vel_stamp = now

    def _on_cmd_vel_in_plain(self, msg: Twist) -> None:
        """Cache the latest manual/teleop Twist command.

        This is the path used by WebManager, joystick_teleop, keyboard_teleop
        etc. that publish geometry_msgs/Twist on the manual-input topic. Both
        inputs share the same _last_cmd_vel cache so the output timer keeps
        republishing until a fresh command arrives or the user releases.

        Same ESTOP guard as ``_on_cmd_vel_in_stamped`` — see that method's
        docstring for why refreshing the cache while estopped would leak
        motion through the reset transition.

        Teleop override: resets the 2-second window so Nav2 behavior ticks
        can't fight the teleop command while the operator is actively driving.

        Stop suppression: when teleop sends lin=0 (key released), set the
        _stop_requested flag so _publish_cmd_vel stops publishing entirely.
        The ESP32's own 500ms watchdog handles stopping the robot. This
        prevents supervisor from flooding /cmd_vel with zeros between teleop
        key presses, which was causing micro-step jitter on ESP32.
        """
        if self._state is State.ESTOP:
            return
        # Detect stop (key released)
        is_stop = (abs(msg.linear.x) < 0.001 and abs(msg.angular.z) < 0.001)
        if is_stop:
            self._stop_requested = True
        else:
            self._stop_requested = False
        self._last_cmd_vel = msg
        self._last_cmd_vel_stamp = self.get_clock().now()
        # Extend teleop override window
        self._teleop_override_until = (
            self.get_clock().now() +
            rclpy.duration.Duration(seconds=self._teleop_override_sec))

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
        # DOCK is a stub in Phase 4: we accept the command but do NOT
        # transition to DOCK (would be a lie — there's no docking BT wired
        # up). The service response reports the *actual* current state, so
        # the orchestrator can detect the stub and retry later.
        #
        # NOTE on the docstring above: this does NOT "fall back to IDLE"
        # semantics — it preserves the current state (IDLE or NAV) without
        # transition. Behavior in ``_publish_cmd_vel`` is identical for
        # IDLE/NAV (both pass through), so the practical effect matches
        # "IDLE semantics" only if the FSM was already in IDLE. If DOCK
        # is requested while in NAV, the robot keeps doing whatever NAV
        # was doing — orchestrators reading ``supervisor/state`` will see
        # NAV, not IDLE, and should treat that as the stub being a no-op.
        # See SupervisorCmd.srv comments for the orchestrator contract.
        if self._state is State.DOCK:
            return
        self.get_logger().warning(
            f"DOCK requested ({reason}) — not implemented in Phase 4; "
            f'staying in {self._state.value}.')

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

        Watchdog: if no fresh _last_cmd_vel has arrived within
        ``cmd_vel_timeout_sec``, force zero so the firmware stops even
        when the upstream publisher has gone silent (e.g., teleop released).

        Stop suppression: if _stop_requested is set (teleop sent lin=0),
        publish nothing. The ESP32's own 500ms watchdog will stop the robot.
        This prevents supervisor from republishing zeros at 10 Hz between
        teleop key presses, which was triggering botStop() on the ESP32
        on every republish tick and causing micro-step jitter.
        """
        if self._state is State.ESTOP:
            self._cmd_vel_out_pub.publish(Twist())
            return
        age = (self.get_clock().now() - self._last_cmd_vel_stamp).nanoseconds / 1e9
        if age > self._cmd_vel_timeout_sec:
            self._stop_requested = False
            self._cmd_vel_out_pub.publish(Twist())
            return
        if self._stop_requested:
            return
        self._cmd_vel_out_pub.publish(self._last_cmd_vel)

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
