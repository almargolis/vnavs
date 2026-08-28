import tkinter

from ezcomms import vnavs_const as vconst
from vnavsrun import helmsman
from vnavsrun import mission_control


class _StubWidget:
    """Minimal stub for eztk widgets (entry fields, labels, etc.)."""

    def __init__(self, val=""):
        self._val = val

    def value(self):
        return self._val

    def replace_value(self, v, caption=None):
        self._val = str(v)


def _make_mc(**overrides):
    """Create a MissionControl without calling __init__ (no broker/Tk)."""
    mc = object.__new__(mission_control.MissionControl)
    mc._published = []  # capture publish calls

    def _mock_publish(topic, payload):
        mc._published.append((topic, dict(payload)))

    mc.publish = _mock_publish
    mc.speed = 0.0
    mc.keys_held = set()
    mc.drive_active = False
    mc.last_drive_publish_time = 0.0
    mc.pic_continuous = True
    mc.last_pic_time = 0.0
    mc.gamepad = None
    mc.gamepad_active = False
    mc.gamepad_speed = 0.0
    mc.gamepad_steer = 0.0

    # Stub UI widgets
    mc.drive_speed_entry = _StubWidget("20")
    mc.drive_steer_entry = _StubWidget("0.3")
    mc.drive_status = _StubWidget("stopped")
    mc.gamepad_label = _StubWidget("none")
    mc.image_status_label = _StubWidget("Image: ON")
    mc.camera_iso_entry = _StubWidget("800")
    mc.camera_shutter_entry = _StubWidget("10000")
    mc.max_width_entry = _StubWidget("320")
    mc.max_height_entry = _StubWidget("240")

    for k, v in overrides.items():
        setattr(mc, k, v)
    return mc


# --- _publish_drive_order ---


def test_publish_drive_order_fields():
    mc = _make_mc()
    mc._publish_drive_order(25.0, 0.5)
    assert len(mc._published) == 1
    topic, payload = mc._published[0]
    assert topic == vconst.helmsman_orders_topic
    assert payload[helmsman.HELMSMAN_CM_PER_SEC] == 25.0
    assert payload[helmsman.HELMSMAN_RAD_PER_SEC] == 0.5
    assert payload[helmsman.HELMSMAN_TIMER] == 3
    assert mc.drive_status.value() == "spd=25 str=0.50"


# --- Drive buttons ---


def test_drive_stop_zeros():
    mc = _make_mc()
    mc.keys_held = {"w", "a"}
    mc.drive_active = True
    mc.on_drive_stop()
    assert len(mc.keys_held) == 0
    assert mc.drive_active is False
    topic, payload = mc._published[0]
    assert payload[helmsman.HELMSMAN_CM_PER_SEC] == 0.0
    assert payload[helmsman.HELMSMAN_RAD_PER_SEC] == 0.0


def test_drive_forward():
    mc = _make_mc()
    mc.on_drive_forward()
    topic, payload = mc._published[0]
    assert payload[helmsman.HELMSMAN_CM_PER_SEC] == 20.0
    assert payload[helmsman.HELMSMAN_RAD_PER_SEC] == 0.0


def test_drive_back():
    mc = _make_mc()
    mc.on_drive_back()
    topic, payload = mc._published[0]
    assert payload[helmsman.HELMSMAN_CM_PER_SEC] == -20.0


def test_drive_left():
    mc = _make_mc()
    mc.on_drive_left()
    topic, payload = mc._published[0]
    assert payload[helmsman.HELMSMAN_CM_PER_SEC] == 20.0
    assert payload[helmsman.HELMSMAN_RAD_PER_SEC] == -0.3


def test_drive_right():
    mc = _make_mc()
    mc.on_drive_right()
    topic, payload = mc._published[0]
    assert payload[helmsman.HELMSMAN_CM_PER_SEC] == 20.0
    assert payload[helmsman.HELMSMAN_RAD_PER_SEC] == 0.3


# --- Keyboard ---


class _FakeEvent:
    def __init__(self, keysym, widget=None):
        self.keysym = keysym
        self.widget = widget if widget is not None else _StubWidget()


def test_key_press_adds_to_keys_held():
    mc = _make_mc()
    mc.on_key_press(_FakeEvent("w"))
    assert "w" in mc.keys_held
    assert mc.drive_active is True


def test_key_release_clears():
    mc = _make_mc()
    mc.keys_held = {"w"}
    mc.drive_active = True
    mc.on_key_release(_FakeEvent("w"))
    assert "w" not in mc.keys_held
    assert mc.drive_active is False


def test_key_press_ignores_entry_widget():
    mc = _make_mc()
    # mission_control.tkinter is None when not running as gui,
    # so set it for this test to enable the isinstance guard
    saved = mission_control.tkinter
    mission_control.tkinter = tkinter
    try:
        entry_widget = tkinter.Entry()
        mc.on_key_press(_FakeEvent("w", widget=entry_widget))
        assert "w" not in mc.keys_held
        assert mc.drive_active is False
    finally:
        mission_control.tkinter = saved


def test_key_press_space_stops():
    mc = _make_mc()
    mc.keys_held = {"w"}
    mc.drive_active = True
    mc.on_key_press(_FakeEvent("space"))
    assert len(mc.keys_held) == 0
    assert mc.drive_active is False
    assert len(mc._published) == 1
    assert mc._published[0][1][helmsman.HELMSMAN_CM_PER_SEC] == 0.0


# --- Toggle image ---


def test_toggle_image():
    mc = _make_mc()
    assert mc.pic_continuous is True
    mc.on_toggle_image()
    assert mc.pic_continuous is False
    assert mc.image_status_label.value() == "Image: OFF"
    mc.on_toggle_image()
    assert mc.pic_continuous is True
    assert mc.image_status_label.value() == "Image: ON"


# --- Camera apply ---


def test_camera_apply_payload():
    mc = _make_mc()
    mc.on_camera_apply()
    assert len(mc._published) == 1
    topic, payload = mc._published[0]
    assert topic == vconst.cameraman_orders_topic
    assert payload["iso"] == "800"
    assert payload["shutter_speed"] == "10000"


# --- Speed +/- now uses _publish_drive_order ---


def test_speed_plus_uses_drive_order():
    mc = _make_mc()
    mc.on_speed_plus()
    assert mc.speed == 5.0
    topic, payload = mc._published[0]
    assert topic == vconst.helmsman_orders_topic
    assert payload[helmsman.HELMSMAN_CM_PER_SEC] == 5.0
    assert payload[helmsman.HELMSMAN_RAD_PER_SEC] == 0.0
    assert helmsman.HELMSMAN_TIMER in payload


def test_speed_minus_uses_drive_order():
    mc = _make_mc()
    mc.speed = 10.0
    mc.on_speed_minus()
    assert mc.speed == 5.0
    topic, payload = mc._published[0]
    assert payload[helmsman.HELMSMAN_CM_PER_SEC] == 5.0
    assert helmsman.HELMSMAN_TIMER in payload


def test_speed_stop_uses_drive_order():
    mc = _make_mc()
    mc.speed = 15.0
    mc.on_speed_stop()
    assert mc.speed == 0.0
    topic, payload = mc._published[0]
    assert payload[helmsman.HELMSMAN_CM_PER_SEC] == 0.0
    assert payload[helmsman.HELMSMAN_RAD_PER_SEC] == 0.0
    assert helmsman.HELMSMAN_TIMER in payload
