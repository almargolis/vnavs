import math
import queue
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
HELMSMAN_STEERING_TYPE = "steering_type"
HELMSMAN_ANGLE = "angle"
HELMSMAN_ANGLE_RATE = "angle_rate"


class Helmsman(vmqtt.VnavsNode):
    def __init__(self):
        self.orders_q = queue.Queue(10)
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
        self.vehicle_init()

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
                self.vehicle_estop()
                self.current_cm_per_sec = 0.0
                self.current_ackerman_angle = None
                self.state = STATE_ESTOPPED
                self.ClearOrdersQueue()
            if new_state in STATES_MOVING:
                self.state = new_state
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

    def InterpretOrdersSpeed(self, payload):
        if self.speed_control != HELMSMAN_SPEED_CONTROL_DEFAULT:
            if self.speed_control != payload["_sender"]:
                print(f"HELMSMAN - Unauthorized Speed Order from {payload['_sender']}")
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
        if HELMSMAN_CM_PER_SEC in payload:
            self.InterpretOrdersSpeed(payload)
        msg_steering_type = payload.get(
            HELMSMAN_STEERING_TYPE, STEERING_TYPE_DIFFERENTIAL
        )
        has_steering = False
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
        self.deadman_time = time.time() + timer
        if self.state == STATE_TIMED_OUT:
            self.state = STATE_DEADMAN

    def client_loop_code(self):
        if not self.mqttc.connected:
            self.vehicle_estop()
            self.current_cm_per_sec = 0.0
            self.current_ackerman_angle = None
            return
        if (self.state == STATE_DEADMAN) and (time.time() > self.deadman_time):
            self.vehicle_estop()
            self.current_cm_per_sec = 0.0
            self.current_ackerman_angle = None
            self.state = STATE_TIMED_OUT
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
        self.vehicle_cleanup()
