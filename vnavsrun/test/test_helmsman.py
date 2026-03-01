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
