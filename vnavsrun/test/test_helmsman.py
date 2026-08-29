import math
import time

from vnavsrun import helmsman


def test_helmsman_constants_exist():
    assert helmsman.HELMSMAN_CM_PER_SEC == "cm_per_sec"
    assert helmsman.HELMSMAN_RAD_PER_SEC == "rad_per_sec"
    assert helmsman.HELMSMAN_TIMER == "timer"
    assert helmsman.HELMSMAN_GOVERNOR == "governor"
    assert helmsman.HELMSMAN_P_ERROR == "p_error"
    assert helmsman.HELMSMAN_I_ACCUMULATOR == "i_accumulator"
    assert helmsman.HELMSMAN_DERIVATIVE == "derivative"
    assert helmsman.HELMSMAN_STATE == "state"
    assert helmsman.HELMSMAN_SPEED_CONTROL == "speed_control"
    assert helmsman.HELMSMAN_MAX_SPEED_CONTROL == "max_speed_control"
    assert helmsman.HELMSMAN_STEERING_CONTROL == "steering_control"


def test_helmsman_state_constants():
    assert helmsman.STATE_DEADMAN == "d"
    assert helmsman.STATE_CONTINUOUS == "c"
    assert helmsman.STATE_TIMED_OUT == "t"
    assert helmsman.STATE_ESTOPPED == "e"
    assert helmsman.STATE_DEADMAN in helmsman.STATES_MOVING
    assert helmsman.STATE_CONTINUOUS in helmsman.STATES_MOVING


def test_helmsman_class_exists():
    assert hasattr(helmsman, "Helmsman")


def test_steering_type_constants():
    assert helmsman.STEERING_TYPE_DIFFERENTIAL == "d"
    assert helmsman.STEERING_TYPE_ACKERMAN == "a"
    assert helmsman.HELMSMAN_STEERING_TYPE == "steering_type"
    assert helmsman.HELMSMAN_ANGLE == "angle"
    assert helmsman.HELMSMAN_ANGLE_RATE == "angle_rate"


# --- Helper to create a Helmsman without connecting to a broker ---


def make_helmsman(**overrides):
    """Create a Helmsman instance without calling __init__ (no broker needed)."""
    h = object.__new__(helmsman.Helmsman)
    h.speed_control = helmsman.HELMSMAN_SPEED_CONTROL_DEFAULT
    h.steering_control = helmsman.HELMSMAN_STEERING_CONTROL_DEFAULT
    h.governor = 0.0
    h.vehicle_steering_type = helmsman.STEERING_TYPE_DIFFERENTIAL
    h.wheelbase = 26.0
    h.current_cm_per_sec = 0.0
    h.current_ackerman_angle = None
    h.state = helmsman.STATE_DEADMAN
    h._log_state = None
    h._log_connected = None
    h._last_order_log = 0.0
    h._last_speed = None
    h._last_steering = None
    h._last_angle = None
    h._last_angle_rate = None
    for k, v in overrides.items():
        setattr(h, k, v)
    return h


def _patch_vehicle_methods(h):
    """Patch abstract vehicle methods to record calls."""
    h.vehicle_set_speed = lambda cm: setattr(h, "_last_speed", cm)
    h.vehicle_set_steering = lambda rad: setattr(h, "_last_steering", rad)
    h.vehicle_set_steering_angle = lambda a, r: (
        setattr(h, "_last_angle", a),
        setattr(h, "_last_angle_rate", r),
    )
    h._last_throttle_norm = None
    h._last_steering_norm = None
    h.vehicle_set_throttle = lambda n: setattr(h, "_last_throttle_norm", n)
    h.vehicle_set_steering_direct = lambda n: setattr(h, "_last_steering_norm", n)


def test_manual_throttle_steering_fields_route_directly():
    h = make_helmsman()
    _patch_vehicle_methods(h)
    h.deadman_time = 0
    h.InterpretOrders(
        {
            helmsman.HELMSMAN_THROTTLE: "0.4",
            helmsman.HELMSMAN_STEERING: "-0.7",
            "_sender": "drive",
        }
    )
    assert h._last_throttle_norm == 0.4
    assert h._last_steering_norm == -0.7
    assert h._last_speed is None  # cm/s path untouched
    assert h._last_steering is None  # PID-gain path untouched
    assert h.deadman_time > 0  # deadman still armed


def test_manual_command_default_scaling():
    """Base vehicle_set_throttle/steering_direct scale onto speed_max /
    steering_max and clamp."""
    h = make_helmsman(speed_max=150.0, steering_max=3.0)
    h._last_speed = None
    h._last_steering = None
    h.vehicle_set_speed = lambda cm: setattr(h, "_last_speed", cm)
    h.vehicle_set_steering = lambda rad: setattr(h, "_last_steering", rad)
    helmsman.Helmsman.vehicle_set_throttle(h, 0.5)
    helmsman.Helmsman.vehicle_set_steering_direct(h, -2.0)  # clamps to -1
    assert h._last_speed == 75.0
    assert h._last_steering == -3.0


# --- Conversion tests ---


def test_ackerman_to_differential_conversion():
    h = make_helmsman()
    _patch_vehicle_methods(h)
    h.current_cm_per_sec = 20.0
    h.current_ackerman_angle = math.radians(30)
    h._recompute_differential_from_ackerman()
    expected = 20.0 * math.tan(math.radians(30)) / 26.0
    assert abs(h._last_steering - expected) < 1e-9


def test_ackerman_to_differential_zero_speed():
    h = make_helmsman()
    _patch_vehicle_methods(h)
    h.current_cm_per_sec = 0.0
    h.current_ackerman_angle = math.radians(15)
    h._recompute_differential_from_ackerman()
    assert abs(h._last_steering) < 1e-9


def test_ackerman_to_differential_zero_angle():
    h = make_helmsman()
    _patch_vehicle_methods(h)
    h.current_cm_per_sec = 30.0
    h.current_ackerman_angle = 0.0
    h._recompute_differential_from_ackerman()
    assert abs(h._last_steering) < 1e-9


def test_ackerman_to_differential_no_wheelbase(capsys):
    h = make_helmsman(wheelbase=0.0)
    _patch_vehicle_methods(h)
    h.current_cm_per_sec = 10.0
    h.current_ackerman_angle = 0.5
    h._recompute_differential_from_ackerman()
    assert h._last_steering is None  # vehicle_set_steering not called
    assert "wheelbase not set" in capsys.readouterr().out


# --- InterpretOrders routing tests ---


def test_interpret_orders_differential_default():
    """Messages without steering_type default to differential."""
    h = make_helmsman()
    _patch_vehicle_methods(h)
    payload = {
        helmsman.HELMSMAN_CM_PER_SEC: "10",
        helmsman.HELMSMAN_RAD_PER_SEC: "1.5",
        "_sender": "test",
    }
    h.InterpretOrders(payload)
    assert h._last_speed == 10.0
    assert h._last_steering == 1.5
    assert h.current_ackerman_angle is None


def test_interpret_orders_ackerman_on_differential_robot():
    """Ackerman command on a differential robot triggers conversion."""
    h = make_helmsman()
    _patch_vehicle_methods(h)
    angle = math.radians(20)
    payload = {
        helmsman.HELMSMAN_CM_PER_SEC: "15",
        helmsman.HELMSMAN_STEERING_TYPE: helmsman.STEERING_TYPE_ACKERMAN,
        helmsman.HELMSMAN_ANGLE: str(angle),
        "_sender": "test",
    }
    h.InterpretOrders(payload)
    assert h._last_speed == 15.0
    expected_rad = 15.0 * math.tan(angle) / 26.0
    assert abs(h._last_steering - expected_rad) < 1e-9
    assert h.current_ackerman_angle == angle


def test_interpret_orders_ackerman_on_ackerman_robot():
    """Ackerman command on an ackerman robot calls vehicle_set_steering_angle."""
    h = make_helmsman(vehicle_steering_type=helmsman.STEERING_TYPE_ACKERMAN)
    _patch_vehicle_methods(h)
    angle = math.radians(25)
    payload = {
        helmsman.HELMSMAN_STEERING_TYPE: helmsman.STEERING_TYPE_ACKERMAN,
        helmsman.HELMSMAN_ANGLE: str(angle),
        helmsman.HELMSMAN_ANGLE_RATE: "2.0",
        "_sender": "test",
    }
    h.InterpretOrders(payload)
    assert h._last_angle == angle
    assert h._last_angle_rate == 2.0


def test_interpret_orders_speed_only_recomputes_ackerman():
    """Speed-only update recomputes steering when ackerman angle is cached."""
    h = make_helmsman()
    _patch_vehicle_methods(h)
    angle = math.radians(10)
    h.current_ackerman_angle = angle
    payload = {
        helmsman.HELMSMAN_CM_PER_SEC: "25",
        "_sender": "test",
    }
    h.InterpretOrders(payload)
    expected_rad = 25.0 * math.tan(angle) / 26.0
    assert abs(h._last_steering - expected_rad) < 1e-9


def test_interpret_orders_speed_only_no_recompute_without_ackerman():
    """Speed-only update does not touch steering when no ackerman angle cached."""
    h = make_helmsman()
    _patch_vehicle_methods(h)
    payload = {
        helmsman.HELMSMAN_CM_PER_SEC: "25",
        "_sender": "test",
    }
    h.InterpretOrders(payload)
    assert h._last_speed == 25.0
    assert h._last_steering is None  # no steering call


def test_ackerman_robot_rejects_differential(capsys):
    """Ackerman robot rejects differential steering commands."""
    h = make_helmsman(vehicle_steering_type=helmsman.STEERING_TYPE_ACKERMAN)
    _patch_vehicle_methods(h)
    payload = {
        helmsman.HELMSMAN_RAD_PER_SEC: "1.0",
        "_sender": "test",
    }
    h.InterpretOrdersHeading(payload)
    assert h._last_steering is None  # vehicle_set_steering not called
    assert "Ackerman robot cannot accept" in capsys.readouterr().out


def test_differential_heading_clears_ackerman_state():
    """Differential steering command clears cached ackerman angle."""
    h = make_helmsman()
    _patch_vehicle_methods(h)
    h.current_ackerman_angle = 0.5
    payload = {
        helmsman.HELMSMAN_RAD_PER_SEC: "2.0",
        "_sender": "test",
    }
    h.InterpretOrdersHeading(payload)
    assert h.current_ackerman_angle is None
    assert h._last_steering == 2.0


def test_ackerman_default_angle_rate():
    """Ackerman command without angle_rate defaults to 1.0."""
    h = make_helmsman(vehicle_steering_type=helmsman.STEERING_TYPE_ACKERMAN)
    _patch_vehicle_methods(h)
    payload = {
        helmsman.HELMSMAN_STEERING_TYPE: helmsman.STEERING_TYPE_ACKERMAN,
        helmsman.HELMSMAN_ANGLE: "0.3",
        "_sender": "test",
    }
    h.InterpretOrdersAckerman(payload)
    assert h._last_angle_rate == 1.0


# --- Stale / future message rejection in InterpretOrders ---


def test_interpret_orders_stale_rejected(capsys):
    """Stale _sendTime causes InterpretOrders to return early."""
    h = make_helmsman()
    _patch_vehicle_methods(h)
    h.deadman_time = 0
    payload = {
        helmsman.HELMSMAN_CM_PER_SEC: "10",
        helmsman.HELMSMAN_RAD_PER_SEC: "1.0",
        "_sender": "test",
        "_sendTime": time.time() - 10.0,
    }
    h.InterpretOrders(payload)
    assert h._last_speed is None  # speed never set
    assert h.deadman_time == 0  # deadman NOT extended
    assert "HELMSMAN REJECT" in capsys.readouterr().out


def test_interpret_orders_future_rejected(capsys):
    """Future _sendTime causes InterpretOrders to return early."""
    h = make_helmsman()
    _patch_vehicle_methods(h)
    h.deadman_time = 0
    payload = {
        helmsman.HELMSMAN_CM_PER_SEC: "10",
        "_sender": "test",
        "_sendTime": time.time() + 10.0,
    }
    h.InterpretOrders(payload)
    assert h._last_speed is None
    assert h.deadman_time == 0
    assert "HELMSMAN REJECT" in capsys.readouterr().out


def test_interpret_orders_fresh_accepted():
    """Fresh _sendTime allows normal InterpretOrders processing."""
    h = make_helmsman()
    _patch_vehicle_methods(h)
    h.deadman_time = 0
    payload = {
        helmsman.HELMSMAN_CM_PER_SEC: "10",
        helmsman.HELMSMAN_RAD_PER_SEC: "1.5",
        "_sender": "test",
        "_sendTime": time.time() - 1.0,
    }
    h.InterpretOrders(payload)
    assert h._last_speed == 10.0
    assert h._last_steering == 1.5
    assert h.deadman_time > 0


def test_interpret_orders_no_sendtime_backward_compat():
    """Orders without _sendTime are processed normally (backward compat)."""
    h = make_helmsman()
    _patch_vehicle_methods(h)
    h.deadman_time = 0
    payload = {
        helmsman.HELMSMAN_CM_PER_SEC: "20",
        helmsman.HELMSMAN_RAD_PER_SEC: "0.5",
        "_sender": "test",
    }
    h.InterpretOrders(payload)
    assert h._last_speed == 20.0
    assert h.deadman_time > 0


def test_safe_shutdown_estops_cleans_once():
    """safe_shutdown() estops + cleans up exactly once, even called repeatedly
    and even if a vehicle method raises."""
    h = object.__new__(helmsman.Helmsman)
    h._shutdown_done = False
    calls = []
    h.vehicle_estop = lambda: calls.append("estop")
    h.vehicle_cleanup = lambda: calls.append("cleanup")
    h.safe_shutdown()
    h.safe_shutdown()
    assert calls == ["estop", "cleanup"]


def test_safe_shutdown_survives_failing_vehicle(capsys):
    h = object.__new__(helmsman.Helmsman)
    h._shutdown_done = False

    def boom():
        raise RuntimeError("bus gone")

    h.vehicle_estop = boom
    cleaned = []
    h.vehicle_cleanup = lambda: cleaned.append(True)
    h.safe_shutdown()  # must not raise
    assert cleaned == [True]  # cleanup still attempted after estop failed


def test_cleanup_loop_delegates_to_safe_shutdown():
    h = object.__new__(helmsman.Helmsman)
    h._shutdown_done = False
    hits = []
    h.vehicle_estop = lambda: hits.append("e")
    h.vehicle_cleanup = lambda: hits.append("c")
    h.cleanup_loop()
    assert hits == ["e", "c"]


def test_deadman_fires_after_no_fresh_orders():
    """Deadman timer fires estop when no fresh orders arrive."""
    h = make_helmsman()
    _patch_vehicle_methods(h)
    estop_called = []
    h.vehicle_estop = lambda: estop_called.append(True)
    h.stats = type("C", (), {"Count": lambda self, n: None})()
    h.mqttc = type("M", (), {"connected": True})()
    h.orders_q = __import__("queue").Queue(10)

    # Set deadman in the past
    h.deadman_time = time.time() - 1.0
    h.state = helmsman.STATE_DEADMAN
    h.client_loop_code()
    assert len(estop_called) == 1
    assert h.state == helmsman.STATE_TIMED_OUT
