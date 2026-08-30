from ezcomms import vnavs_const as vconst
from vnavsrun import helmsman
from vnavsrun import mission_functions as mf
from vnavsrun import headless_control as hc


class _FakePad:
    def __init__(self, axes=None, buttons=None, name="FakePad"):
        self.axes = axes or [0.0] * 6
        self.buttons = buttons or [0] * 16
        self._name = name

    def get_numaxes(self):
        return len(self.axes)

    def get_numbuttons(self):
        return len(self.buttons)

    def get_name(self):
        return self._name

    def get_axis(self, i):
        return self.axes[i]

    def get_button(self, i):
        return self.buttons[i]


class _FakeEvents:
    @staticmethod
    def get():
        return []

    @staticmethod
    def pump():
        pass


class _FakePygame:
    JOYDEVICEREMOVED = 1
    event = _FakeEvents()


def setup_module(module):
    hc.pygame = _FakePygame()


def _make_hc(**overrides):
    h = object.__new__(hc.HeadlessControl)
    h.published = []
    h.publish = lambda topic, payload: h.published.append((topic, dict(payload)))
    h.joystick_index = 0
    h.steer_axis = 0
    h.steer_invert = 1
    h.throttle_axis = 3
    h.throttle_invert = -1
    h.deadzone = 0.12
    h.throttle_max = 0.35
    h.steer_max = 0.7
    h.deadman_button = 5
    h.record_button = 0
    h.estop_button = 1
    h.publish_interval = 0.0
    h.status_interval = 999.0  # keep status out of the way unless asked
    h.mission_name = "headless"
    h.gamepad = _FakePad()
    h.gamepad_name = "FakePad"
    h.armed = False
    h.recording = False
    h.mission_id = ""
    h.note = ""
    h._prev_buttons = set()
    h._last_publish = 0.0
    h._last_status = 0.0
    h._last_throttle = 0.0
    h._last_steer = 0.0
    h._shutdown_done = False
    for k, v in overrides.items():
        setattr(h, k, v)
    return h


def _topics(h):
    return [t for t, _ in h.published]


# --- deadman gating ---


def test_no_drive_order_without_deadman():
    h = _make_hc()
    h.gamepad = _FakePad(axes=[1.0, 0, 0, -1.0])  # full steer + full throttle
    h.client_loop_code()
    assert vconst.helmsman_orders_topic not in _topics(h)
    assert h.armed is False


def test_deadman_held_publishes_scaled_order():
    h = _make_hc()
    buttons = [0] * 16
    buttons[5] = 1  # deadman
    h.gamepad = _FakePad(axes=[1.0, 0, 0, -1.0], buttons=buttons)
    h.client_loop_code()
    orders = [p for t, p in h.published if t == vconst.helmsman_orders_topic]
    assert orders
    assert abs(orders[-1][helmsman.HELMSMAN_STEERING] - 0.7) < 1e-6
    assert abs(orders[-1][helmsman.HELMSMAN_THROTTLE] - 0.35) < 1e-6
    assert h.armed is True


def test_deadman_release_publishes_one_stop():
    h = _make_hc(armed=True)
    h.gamepad = _FakePad(axes=[1.0, 0, 0, -1.0], buttons=[0] * 16)
    h.client_loop_code()
    orders = [p for t, p in h.published if t == vconst.helmsman_orders_topic]
    assert orders[-1][helmsman.HELMSMAN_THROTTLE] == 0.0
    assert orders[-1][helmsman.HELMSMAN_STEERING] == 0.0
    assert h.armed is False


def test_deadzone_applies():
    h = _make_hc()
    buttons = [0] * 16
    buttons[5] = 1
    h.gamepad = _FakePad(axes=[0.05, 0, 0, 0.05], buttons=buttons)
    h.client_loop_code()
    orders = [p for t, p in h.published if t == vconst.helmsman_orders_topic]
    assert orders[-1][helmsman.HELMSMAN_THROTTLE] == 0.0
    assert orders[-1][helmsman.HELMSMAN_STEERING] == 0.0


# --- buttons ---


def test_record_button_toggles_recording():
    h = _make_hc()
    buttons = [0] * 16
    buttons[0] = 1  # record
    h.gamepad = _FakePad(buttons=buttons)
    h.client_loop_code()
    assert h.recording is True
    assert _topics(h)[:2] == [vconst.mission_init_topic, vconst.mission_log_start_topic]
    assert h.mission_id.startswith("headless_")

    # release then press again -> stop
    h.published.clear()
    h.gamepad = _FakePad(buttons=[0] * 16)
    h.client_loop_code()  # release (edge clears)
    h.gamepad = _FakePad(buttons=buttons)
    h.client_loop_code()  # press again
    assert h.recording is False
    assert vconst.mission_log_stop_topic in _topics(h)


def test_estop_button():
    h = _make_hc(armed=True)
    buttons = [0] * 16
    buttons[1] = 1
    h.gamepad = _FakePad(buttons=buttons)
    h.client_loop_code()
    estops = [
        p
        for t, p in h.published
        if t == vconst.helmsman_orders_topic
        and p.get(helmsman.HELMSMAN_STATE) == helmsman.STATE_ESTOPPED
    ]
    assert estops
    assert h.armed is False


def test_button_is_edge_triggered():
    h = _make_hc()
    buttons = [0] * 16
    buttons[0] = 1
    h.gamepad = _FakePad(buttons=buttons)
    h.client_loop_code()
    assert h.recording is True
    h.published.clear()
    h.client_loop_code()  # button still held -- no second toggle
    assert h.recording is True
    assert vconst.mission_log_stop_topic not in _topics(h)


# --- shutdown ---


def test_safe_shutdown_stops_and_estops():
    h = _make_hc(recording=True)
    h.safe_shutdown()
    topics = _topics(h)
    assert vconst.mission_log_stop_topic in topics
    # a stop order and an estop order both went out
    orders = [p for t, p in h.published if t == vconst.helmsman_orders_topic]
    assert any(p.get(helmsman.HELMSMAN_THROTTLE) == 0.0 for p in orders)
    assert any(
        p.get(helmsman.HELMSMAN_STATE) == helmsman.STATE_ESTOPPED for p in orders
    )
    # idempotent
    n = len(h.published)
    h.safe_shutdown()
    assert len(h.published) == n
