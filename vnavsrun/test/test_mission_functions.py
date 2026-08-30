from ezcomms import vnavs_const as vconst
from vnavsrun import helmsman
from vnavsrun import mission_functions as mf


class _Node:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload):
        self.published.append((topic, dict(payload)))


# --- apply_deadzone ---


def test_deadzone_zeros_small_input():
    assert mf.apply_deadzone(0.05, 0.12) == 0.0
    assert mf.apply_deadzone(-0.1, 0.12) == 0.0


def test_deadzone_rescales_remainder():
    # just outside the zone -> ~0, full deflection -> 1
    assert abs(mf.apply_deadzone(0.12, 0.12)) < 1e-6
    assert abs(mf.apply_deadzone(1.0, 0.12) - 1.0) < 1e-6
    assert abs(mf.apply_deadzone(-1.0, 0.12) + 1.0) < 1e-6


def test_deadzone_disabled():
    assert mf.apply_deadzone(0.03, 0.0) == 0.03


# --- publish_manual_drive / stop / estop ---


def test_publish_manual_drive_payload():
    n = _Node()
    p = mf.publish_manual_drive(n, 2.0, -0.5)
    assert n.published[0][0] == vconst.helmsman_orders_topic
    assert p[helmsman.HELMSMAN_THROTTLE] == 1.0  # clamped
    assert p[helmsman.HELMSMAN_STEERING] == -0.5
    assert p[helmsman.HELMSMAN_TIMER] == mf.MANUAL_DRIVE_TIMER


def test_publish_stop():
    n = _Node()
    mf.publish_stop(n)
    _, p = n.published[0]
    assert p[helmsman.HELMSMAN_THROTTLE] == 0.0
    assert p[helmsman.HELMSMAN_STEERING] == 0.0


def test_publish_estop():
    n = _Node()
    mf.publish_estop(n)
    topic, p = n.published[0]
    assert topic == vconst.helmsman_orders_topic
    assert p[helmsman.HELMSMAN_STATE] == helmsman.STATE_ESTOPPED


# --- recording ---


def test_start_recording_publishes_init_then_log_start():
    n = _Node()
    mid = mf.start_recording(n, "headless")
    assert mid.startswith("headless_")
    topics = [t for t, _ in n.published]
    assert topics == [vconst.mission_init_topic, vconst.mission_log_start_topic]
    assert n.published[0][1]["mission_id"] == mid
    assert n.published[1][1]["mission_id"] == mid


def test_stop_recording():
    n = _Node()
    mf.stop_recording(n)
    assert n.published[0][0] == vconst.mission_log_stop_topic


# --- status ---


def test_build_and_format_status():
    p = mf.build_status_payload(
        armed=True, recording=False, mission_id="m1", throttle=0.123456, steering=-0.2
    )
    assert p["armed"] is True
    assert p["throttle"] == 0.123  # rounded
    s = mf.format_status(p)
    assert "ARMED" in s and "---" in s and "m1" in s
