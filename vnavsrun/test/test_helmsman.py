import math

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
