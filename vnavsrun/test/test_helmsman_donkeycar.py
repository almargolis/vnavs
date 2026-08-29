from vnavsrun import helmsman
from vnavsrun import helmsman_donkeycar as hd


def make_vehicle():
    """A Vehicle with calibration values set but no PCA9685 / I2C bus."""
    v = object.__new__(hd.Vehicle)
    v.steering_channel = 1
    v.throttle_channel = 0
    v.steering_left_pwm = 460
    v.steering_center_pwm = 375
    v.steering_right_pwm = 290
    v.throttle_forward_pwm = 500
    v.throttle_stopped_pwm = 370
    v.throttle_reverse_pwm = 220
    v.steering_gain = 0.01
    v.max_steering_radians = 0.6
    v.max_speed_cm_per_sec = 200.0
    v.steering_norm = 0.0
    v.throttle_frac = 0.0
    v.throttle_deadband_pwm = 0
    v._closed = False
    return v


class _FakePca:
    def __init__(self):
        self.writes = []
        self.channels_off = []
        self.closed = False

    def set_pwm(self, ch, on, off):
        self.writes.append((ch, on, off))

    def set_channel_off(self, ch):
        self.channels_off.append(ch)

    def close(self):
        self.closed = True


def test_steering_center_maps_to_center_pwm():
    v = make_vehicle()
    assert v._steering_norm_to_pwm(0.0) == 375


def test_steering_full_right_and_left():
    v = make_vehicle()
    assert v._steering_norm_to_pwm(1.0) == 290
    assert v._steering_norm_to_pwm(-1.0) == 460


def test_steering_partial_and_clamp():
    v = make_vehicle()
    assert v._steering_norm_to_pwm(0.5) == round(375 + 0.5 * (290 - 375))
    assert v._steering_norm_to_pwm(3.0) == 290  # clamped


def test_throttle_mapping():
    v = make_vehicle()
    assert v._throttle_frac_to_pwm(0.0) == 370
    assert v._throttle_frac_to_pwm(1.0) == 500
    assert v._throttle_frac_to_pwm(-1.0) == 220
    assert v._throttle_frac_to_pwm(0.5) == round(370 + 0.5 * (500 - 370))


def test_throttle_deadband_compensation():
    v = make_vehicle()
    v.throttle_deadband_pwm = 25
    assert v._throttle_frac_to_pwm(0.0) == 370          # zero stays neutral
    # any positive frac starts at stopped + deadband, ramps to forward
    assert v._throttle_frac_to_pwm(0.0001) > 393
    assert v._throttle_frac_to_pwm(1.0) == 500
    assert v._throttle_frac_to_pwm(0.5) == round(395 + 0.5 * (500 - 395))
    # reverse mirrors below stopped
    assert v._throttle_frac_to_pwm(-1.0) == 220
    assert v._throttle_frac_to_pwm(-0.5) == round(345 + 0.5 * (220 - 345))


def test_manual_norm_commands_pass_through():
    h = object.__new__(hd.HelmsmanDonkeycar)
    h.v = make_vehicle()
    hd.HelmsmanDonkeycar.vehicle_set_throttle(h, 0.4)
    assert h.v.throttle_frac == 0.4
    hd.HelmsmanDonkeycar.vehicle_set_steering_direct(h, -0.7)
    assert h.v.steering_norm == -0.7


def test_tick_writes_both_channels():
    v = make_vehicle()
    writes = []
    v.pca = type("P", (), {"set_pwm": lambda self, ch, on, off: writes.append((ch, on, off))})()
    v.set_steering_norm(1.0)
    v.set_throttle_frac(0.0)
    v.tick()
    assert (1, 0, 290) in writes
    assert (0, 0, 370) in writes


def test_helmsman_reports_differential_steering():
    h = object.__new__(hd.HelmsmanDonkeycar)
    h.v = make_vehicle()
    h.v.max_speed_cm_per_sec = 200.0
    hd.HelmsmanDonkeycar.vehicle_set_speed(h, 100.0)
    assert h.v.throttle_frac == 0.5
    hd.HelmsmanDonkeycar.vehicle_set_steering(h, 50.0)  # 50 * 0.01 gain
    assert abs(h.v.steering_norm - 0.5) < 1e-9
    hd.HelmsmanDonkeycar.vehicle_set_steering_angle(h, 0.3, 1.0)
    assert abs(h.v.steering_norm - 0.5) < 1e-9


def test_cleanup_neutralises_kills_throttle_and_closes_bus():
    v = make_vehicle()
    v.pca = _FakePca()
    v.cleanup()
    assert (v.throttle_channel, 0, v.throttle_stopped_pwm) in v.pca.writes  # neutral
    assert v.throttle_channel in v.pca.channels_off                        # no pulse
    assert v.pca.closed
    assert v._closed


def test_cleanup_is_idempotent_after_bus_closed():
    v = make_vehicle()
    v.pca = _FakePca()
    v.cleanup()
    before = (len(v.pca.writes), len(v.pca.channels_off))
    v.cleanup()          # second call must not touch the closed bus
    v.stop()
    v.throttle_off()
    assert (len(v.pca.writes), len(v.pca.channels_off)) == before


def test_module_uses_differential_type_constant():
    # navigator publishes steering in the rad_per_sec field, which the base
    # class only forwards for differential-type vehicles.
    assert helmsman.STEERING_TYPE_DIFFERENTIAL == "d"
