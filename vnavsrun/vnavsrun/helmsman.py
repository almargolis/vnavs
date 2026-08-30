import math
import os
import queue
import signal
import sys
import time

from ezcomms import vnavs_node as vmqtt
from ezcomms import vnavs_const as vconst

STATE_DEADMAN = "d"  # d=deadman active
STATE_CONTINUOUS = "c"  # c=continuous-no timer
STATE_TIMED_OUT = "t"  # t=time out
STATE_ESTOPPED = "e"  # e=e-stop
STATES_MOVING = STATE_DEADMAN + STATE_CONTINUOUS

HELMSMAN_CM_PER_SEC = "cm_per_sec"
HELMSMAN_RAD_PER_SEC = "rad_per_sec"
# Direct manual commands, normalized -1.0..1.0 (RC-transmitter style). These
# bypass cm/s and the PID steering_gain -- for the mission-control Drive tab /
# a gamepad, where the human is the control loop.
HELMSMAN_THROTTLE = "throttle"
HELMSMAN_STEERING = "steering"
HELMSMAN_TIMER = "timer"
HELMSMAN_P_ERROR = "p_error"
HELMSMAN_I_ACCUMULATOR = "i_accumulator"
HELMSMAN_DERIVATIVE = "derivative"

HELMSMAN_STATE = "state"
HELMSMAN_GOVERNOR = "governor"
HELMSMAN_SPEED_CONTROL = "speed_control"
HELMSMAN_SPEED_CONTROL_DEFAULT = "*"
HELMSMAN_MAX_SPEED_CONTROL = "max_speed_control"
HELMSMAN_STEERING_CONTROL = "steering_control"
HELMSMAN_STEERING_CONTROL_DEFAULT = "*"

STEERING_TYPE_DIFFERENTIAL = "d"
STEERING_TYPE_ACKERMAN = "a"


def _clamp(value, low, high):
    return max(low, min(high, value))
HELMSMAN_STEERING_TYPE = "steering_type"
HELMSMAN_ANGLE = "angle"
HELMSMAN_ANGLE_RATE = "angle_rate"


class Helmsman(vmqtt.VnavsNode):
    def __init__(self):
        self.orders_q = queue.Queue(10)
        self._shutdown_done = False
        super().__init__(
            subscriptions=[
                vmqtt.Subscription(
                    vconst.helmsman_orders_topic,
                    async_delivery=True,
                    handler=self.OnHelmsmanOrders,
                    stale_threshold=5.0,
                ),
                vmqtt.Subscription(
                    vconst.helmsman_controls_topic,
                    async_delivery=True,
                    handler=self.OnHelmsmanControls,
                    stale_threshold=10.0,
                ),
                vmqtt.Subscription(
                    vconst.mission_log_start_topic,
                    async_delivery=True,
                    handler=self.OnMissionLogStart,
                    stale_threshold=None,
                ),
                vmqtt.Subscription(
                    vconst.mission_log_stop_topic,
                    async_delivery=True,
                    handler=self.OnMissionLogStop,
                    stale_threshold=None,
                ),
            ],
            single_threaded=False,
            broker_type="F",
            verbose=False,
        )
        self.speed_max = 0.0  # cm/sec, subclass sets in vehicle_init()
        self.steering_max = 0.0  # rad/sec, subclass sets in vehicle_init()
        self.governor = 0.0  # cm/sec, 0 means no limit
        self.mission_logging = False
        self.deadman_time = 0  # E-Stop if time.time() exceeds this
        self.speed_control = HELMSMAN_SPEED_CONTROL_DEFAULT
        self.steering_control = HELMSMAN_STEERING_CONTROL_DEFAULT
        self.state = STATE_DEADMAN
        self.vehicle_steering_type = None  # subclass sets: "d" or "a"
        self.wheelbase = 0.0  # cm, subclass sets if differential
        self.current_cm_per_sec = 0.0  # cached for ackerman->differential recomputation
        self.current_ackerman_angle = None  # cached angle (radians), None if not active
        self._log_state = self.state  # last state we logged a transition for
        self._log_connected = None  # last broker-connection state we logged
        self._last_order_log = 0.0
        # Backstop deadman for manual drive -- see _manual_throttle_effective().
        self._manual_throttle_since = None
        self._manual_hold_tripped = False
        try:
            self.manual_drive_max_hold_s = float(
                self.config.get("Helmsman", "ManualDriveMaxHoldSeconds")
            )
        except Exception:
            self.manual_drive_max_hold_s = 5.0
        self.vehicle_init()

    def _log(self, *parts):
        print("HELMSMAN -", *parts)

    def _log_state_change(self):
        if self.state != self._log_state:
            self._log("state", self._log_state, "->", self.state)
            self._log_state = self.state

    def vehicle_init(self):
        """Initialize hardware. Must set self.speed_max and self.steering_max."""
        raise NotImplementedError

    def vehicle_estop(self):
        """Emergency stop -- immediately halt all motors."""
        raise NotImplementedError

    def vehicle_set_speed(self, cm_per_sec):
        """Set target linear velocity in cm/sec."""
        raise NotImplementedError

    def vehicle_set_steering(self, rad_per_sec):
        """Set target angular velocity in rad/sec."""
        raise NotImplementedError

    def vehicle_set_steering_angle(self, angle, angle_rate):
        """Set target steering angle (radians) and transition rate (radians/sec)."""
        raise NotImplementedError

    def vehicle_tick(self):
        """Periodic call to update hardware with current speed/steering."""
        raise NotImplementedError

    def vehicle_set_throttle(self, norm):
        """Direct manual throttle, normalized -1.0..1.0. Default: scale to
        speed_max and reuse vehicle_set_speed(). Subclasses with a native
        normalized throttle should override."""
        self.vehicle_set_speed(_clamp(norm, -1.0, 1.0) * self.speed_max)

    def vehicle_set_steering_direct(self, norm):
        """Direct manual steering, normalized -1.0..1.0. Default: scale to
        steering_max and reuse vehicle_set_steering()."""
        self.vehicle_set_steering(_clamp(norm, -1.0, 1.0) * self.steering_max)

    def vehicle_cleanup(self):
        """Shutdown hardware gracefully."""
        raise NotImplementedError

    def _recompute_differential_from_ackerman(self):
        if self.wheelbase <= 0:
            print("HELMSMAN - wheelbase not set, cannot convert ackerman to differential")
            return
        rad_per_sec = (
            self.current_cm_per_sec
            * math.tan(self.current_ackerman_angle)
            / self.wheelbase
        )
        self.vehicle_set_steering(rad_per_sec)

    def ClearOrdersQueue(self):
        while True:
            try:
                self.orders_q.get_nowait()
            except queue.Empty:
                return

    def OnHelmsmanControls(self, payload):
        if HELMSMAN_GOVERNOR in payload:
            self.governor = float(payload[HELMSMAN_GOVERNOR])
        if HELMSMAN_MAX_SPEED_CONTROL in payload:
            self.speed_max = float(payload[HELMSMAN_MAX_SPEED_CONTROL])
        if HELMSMAN_STEERING_CONTROL in payload:
            self.steering_control = payload[HELMSMAN_STEERING_CONTROL].strip()
        if HELMSMAN_SPEED_CONTROL in payload:
            self.speed_control = payload[HELMSMAN_SPEED_CONTROL].strip()

    def OnHelmsmanOrders(self, payload):
        if HELMSMAN_STATE in payload:
            new_state = payload[HELMSMAN_STATE]
            if new_state == STATE_ESTOPPED:
                self._log("E-STOP order from", payload.get("_sender", "?"))
                self.vehicle_estop()
                self.current_cm_per_sec = 0.0
                self.current_ackerman_angle = None
                self._reset_manual_hold()
                self.state = STATE_ESTOPPED
                self._log_state_change()
                self.ClearOrdersQueue()
            if new_state in STATES_MOVING:
                self.state = new_state
                self._log_state_change()
        if self.state == STATE_ESTOPPED:
            return
        try:
            self.orders_q.put_nowait(payload)
        except queue.Full:
            pass

    def OnMissionLogStart(self, payload):
        self.mission_logging = True

    def OnMissionLogStop(self, payload):
        self.mission_logging = False

    def _authorized_speed(self, payload):
        if self.speed_control == HELMSMAN_SPEED_CONTROL_DEFAULT:
            return True
        if self.speed_control == payload.get("_sender"):
            return True
        print(f"HELMSMAN - Unauthorized Speed Order from {payload.get('_sender')}")
        return False

    def _authorized_steering(self, payload):
        if self.steering_control == HELMSMAN_STEERING_CONTROL_DEFAULT:
            return True
        if self.steering_control == payload.get("_sender"):
            return True
        print(f"HELMSMAN - Unauthorized Steering Order from {payload.get('_sender')}")
        return False

    def _reset_manual_hold(self):
        self._manual_throttle_since = None
        self._manual_hold_tripped = False

    def _manual_throttle_effective(self, throttle):
        """Backstop deadman for direct manual drive: if a non-zero manual
        throttle keeps arriving with no release for longer than
        ManualDriveMaxHoldSeconds, force it to zero. A human varies throttle
        and lets go (which stops publishing -> the ordinary deadman fires); a
        stuck / zombie mission control republishes the same non-zero value
        forever and re-arms the ordinary deadman every time. Once tripped, the
        ordinary deadman is left to expire (full estop) and the trip stays
        latched until an explicit zero-throttle order arrives -- so a stuck
        sender stays stopped instead of stuttering."""
        now = time.time()
        if abs(throttle) < 1e-3:
            self._reset_manual_hold()
            return throttle
        if self._manual_throttle_since is None:
            self._manual_throttle_since = now
        held = now - self._manual_throttle_since
        if held > self.manual_drive_max_hold_s:
            if not self._manual_hold_tripped:
                self._manual_hold_tripped = True
                self._log(
                    "manual throttle held {:.1f}s with no release -- forcing "
                    "stop (stuck mission control?); send a zero-throttle order "
                    "to resume".format(held)
                )
            return 0.0
        return throttle

    def InterpretOrdersSpeed(self, payload):
        if not self._authorized_speed(payload):
            return
        cm_per_sec = float(payload[HELMSMAN_CM_PER_SEC])
        if self.governor > 0:
            if cm_per_sec > self.governor:
                cm_per_sec = self.governor
            elif cm_per_sec < -self.governor:
                cm_per_sec = -self.governor
        self.current_cm_per_sec = cm_per_sec
        self.vehicle_set_speed(cm_per_sec)

    def InterpretOrdersHeading(self, payload):
        if self.steering_control != HELMSMAN_STEERING_CONTROL_DEFAULT:
            if self.steering_control != payload["_sender"]:
                print(
                    f"HELMSMAN - Unauthorized Steering Order from {payload['_sender']}"
                )
                return
        if self.vehicle_steering_type == STEERING_TYPE_ACKERMAN:
            print("HELMSMAN - Ackerman robot cannot accept differential steering command")
            return
        rad_per_sec = float(payload[HELMSMAN_RAD_PER_SEC])
        self.current_ackerman_angle = None
        self.vehicle_set_steering(rad_per_sec)

    def InterpretOrdersAckerman(self, payload):
        if self.steering_control != HELMSMAN_STEERING_CONTROL_DEFAULT:
            if self.steering_control != payload["_sender"]:
                print(
                    f"HELMSMAN - Unauthorized Steering Order from {payload['_sender']}"
                )
                return
        angle = float(payload[HELMSMAN_ANGLE])
        angle_rate = float(payload.get(HELMSMAN_ANGLE_RATE, 1.0))
        self.current_ackerman_angle = angle
        if self.vehicle_steering_type == STEERING_TYPE_ACKERMAN:
            self.vehicle_set_steering_angle(angle, angle_rate)
        elif self.vehicle_steering_type == STEERING_TYPE_DIFFERENTIAL:
            self._recompute_differential_from_ackerman()

    def InterpretOrders(self, payload):
        if "_sendTime" in payload:
            send_age = time.time() - float(payload["_sendTime"])
            if send_age > 5.0 or send_age < -2.0:
                print(
                    "HELMSMAN REJECT stale/future order age={:.1f}s"
                    .format(send_age)
                )
                return
        has_steering = False
        # Direct normalized manual commands take priority and bypass all the
        # cm/s and PID-gain scaling below.
        if HELMSMAN_THROTTLE in payload:
            if self._authorized_speed(payload):
                self.current_cm_per_sec = 0.0
                self.vehicle_set_throttle(self._manual_throttle_effective(
                    float(payload[HELMSMAN_THROTTLE])
                ))
        if HELMSMAN_STEERING in payload:
            if self._authorized_steering(payload):
                self.current_ackerman_angle = None
                self.vehicle_set_steering_direct(float(payload[HELMSMAN_STEERING]))
                has_steering = True
        if HELMSMAN_CM_PER_SEC in payload:
            self.InterpretOrdersSpeed(payload)
        msg_steering_type = payload.get(
            HELMSMAN_STEERING_TYPE, STEERING_TYPE_DIFFERENTIAL
        )
        if msg_steering_type == STEERING_TYPE_ACKERMAN:
            if HELMSMAN_ANGLE in payload:
                self.InterpretOrdersAckerman(payload)
                has_steering = True
        else:
            if HELMSMAN_RAD_PER_SEC in payload:
                self.InterpretOrdersHeading(payload)
                has_steering = True
        if not has_steering and HELMSMAN_CM_PER_SEC in payload:
            if self.current_ackerman_angle is not None:
                if self.vehicle_steering_type == STEERING_TYPE_DIFFERENTIAL:
                    self._recompute_differential_from_ackerman()
        if HELMSMAN_TIMER in payload:
            timer = int(payload[HELMSMAN_TIMER])
        else:
            timer = 3
        if self._manual_hold_tripped:
            # Stuck-sender backstop tripped: stop re-arming so the ordinary
            # deadman expires and a full estop runs. A zero-throttle order
            # (which clears the trip) will re-arm normally.
            pass
        else:
            self.deadman_time = time.time() + timer
            if self.state == STATE_TIMED_OUT:
                self.state = STATE_DEADMAN
                self._log_state_change()
        now = time.time()
        if now - self._last_order_log > 1.0:
            self._last_order_log = now
            fields = {
                k: payload[k]
                for k in (
                    HELMSMAN_THROTTLE,
                    HELMSMAN_STEERING,
                    HELMSMAN_CM_PER_SEC,
                    HELMSMAN_RAD_PER_SEC,
                    HELMSMAN_ANGLE,
                )
                if k in payload
            }
            self._log(
                "order from {} {} deadman={}s".format(
                    payload.get("_sender", "?"), fields, timer
                )
            )

    def client_loop_code(self):
        if not self.mqttc.connected:
            if self._log_connected is not False:
                self._log("broker connection lost -- holding vehicle stopped")
                self._log_connected = False
            self.vehicle_estop()
            self.current_cm_per_sec = 0.0
            self.current_ackerman_angle = None
            return
        if self._log_connected is not True:
            self._log("broker connected")
            self._log_connected = True
        if (self.state == STATE_DEADMAN) and (time.time() > self.deadman_time):
            self.vehicle_estop()
            self.current_cm_per_sec = 0.0
            self.current_ackerman_angle = None
            self.state = STATE_TIMED_OUT
            self._log_state_change()
            self.stats.Count("timeouts")
            return
        if self.state == STATE_ESTOPPED:
            self.vehicle_estop()
            return
        payload = None
        while True:
            try:
                payload = self.orders_q.get_nowait()
            except queue.Empty:
                break
        if payload is not None:
            self.InterpretOrders(payload)

        if self.state in STATES_MOVING:
            self.vehicle_tick()

    def cleanup_loop(self):
        # Called by VnavsNode.main_loop on KeyboardInterrupt / fatal exception.
        self.safe_shutdown()

    def safe_shutdown(self):
        """Stop the motors and release the hardware, exactly once, on any exit
        path. Without this a killed helmsman leaves the last PWM latched in the
        PWM chip / ESC and the vehicle keeps driving (only power-cycling the
        battery stops it)."""
        if self._shutdown_done:
            return
        self._shutdown_done = True
        try:
            self.vehicle_estop()
        except Exception as exc:  # hardware may already be half torn down
            print("HELMSMAN - estop during shutdown failed:", exc)
        try:
            self.vehicle_cleanup()
        except Exception as exc:
            print("HELMSMAN - vehicle_cleanup during shutdown failed:", exc)

    def run(self):
        """Entry point for the node scripts. Runs main_loop() but guarantees
        safe_shutdown() on every exit path: Ctrl-C, a normal return, a fatal
        exception, and -- the case main_loop() misses -- SIGTERM / SIGHUP,
        which is how `screen -X quit` / `kill` / `stop_all` end the process."""

        def _on_signal(signum, _frame):
            print("HELMSMAN - signal {}, stopping vehicle".format(signum))
            self.safe_shutdown()
            os._exit(0)

        for _sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            try:
                signal.signal(_sig, _on_signal)
            except (ValueError, OSError):
                pass  # not the main thread, or unsupported on this platform
        try:
            self.main_loop()
        finally:
            self.safe_shutdown()
