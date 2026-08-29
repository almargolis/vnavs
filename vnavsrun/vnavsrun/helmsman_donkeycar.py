"""Helmsman for a DonkeyCar-style rover driven over I2C.

The controller board (silkscreen "DuinoFun") is a PCA9685 16-channel PWM
driver on the Raspberry Pi I2C bus: one channel feeds the steering servo,
one feeds the ESC / throttle. All calibration values live in the
``[Helmsman]`` section of ``vnavs.ini`` (loaded from the launch directory)
so a robot can be tuned on-site without code changes.

Steering type is reported as differential so that the navigator's
``follow_line_pid`` / ``follow_line_trace`` output (published in the
``rad_per_sec`` field) is accepted. The value carried there is really the
PID correction term in pixels * Kp, so it is scaled to a normalized
[-1.0, 1.0] steering command via ``SteeringGain`` before being mapped onto
the servo's calibrated PWM range. Ackerman ``angle`` commands (radians) are
also accepted and scaled by ``MaxSteeringRadians``.
"""

import configparser
import sys
import time

from vnavslib import pca9685
from vnavsrun import helmsman

# Hold the ESC at neutral this long after init so it can arm before any
# order is processed. A too-short hold is a common "motors spin on startup".
ESC_ARM_SECONDS = 2.0


def _clamp(value, low, high):
    return max(low, min(high, value))


class Vehicle:
    """Thin wrapper over the PCA9685 that speaks normalized steering / throttle."""

    def __init__(self, config):
        def get(name, default, cast=str):
            try:
                return cast(config.get("Helmsman", name))
            except (configparser.NoSectionError, configparser.NoOptionError):
                return default

        self.i2c_bus = get("I2cBus", 1, int)
        self.i2c_address = int(get("I2cAddress", "0x40"), 0)
        self.pwm_frequency_hz = get("PwmFrequencyHz", 60.0, float)
        self.steering_channel = get("SteeringChannel", 1, int)
        self.throttle_channel = get("ThrottleChannel", 0, int)
        self.steering_left_pwm = get("SteeringLeftPwm", 460, int)
        self.steering_center_pwm = get("SteeringCenterPwm", 375, int)
        self.steering_right_pwm = get("SteeringRightPwm", 290, int)
        self.throttle_forward_pwm = get("ThrottleForwardPwm", 500, int)
        self.throttle_stopped_pwm = get("ThrottleStoppedPwm", 370, int)
        self.throttle_reverse_pwm = get("ThrottleReversePwm", 220, int)
        # PWM counts to skip past the ESC/motor deadband so ANY non-zero
        # throttle command actually moves the car. Bench-find the count just
        # above throttle_stopped_pwm where the wheels start turning; set
        # (that - stopped). 0 = no compensation.
        self.throttle_deadband_pwm = get("ThrottleDeadbandPwm", 0, int)
        self.steering_gain = get("SteeringGain", 0.012, float)
        self.max_steering_radians = get("MaxSteeringRadians", 0.6, float)
        self.max_speed_cm_per_sec = get("MaxSpeedCmPerSec", 200.0, float)

        self.pca = pca9685.Pca9685(
            bus=self.i2c_bus,
            address=self.i2c_address,
            freq_hz=self.pwm_frequency_hz,
        )
        self._closed = False
        self.steering_norm = 0.0
        self.throttle_frac = 0.0
        self.stop()

    def _steering_norm_to_pwm(self, norm):
        norm = _clamp(norm, -1.0, 1.0)
        center = self.steering_center_pwm
        if norm >= 0.0:
            return int(round(center + norm * (self.steering_right_pwm - center)))
        return int(round(center + (-norm) * (self.steering_left_pwm - center)))

    def _throttle_frac_to_pwm(self, frac):
        frac = _clamp(frac, -1.0, 1.0)
        stopped = self.throttle_stopped_pwm
        dead = self.throttle_deadband_pwm
        if frac > 0.0:
            base = stopped + dead
            return int(round(base + frac * (self.throttle_forward_pwm - base)))
        if frac < 0.0:
            base = stopped - dead
            return int(round(base + (-frac) * (self.throttle_reverse_pwm - base)))
        return stopped

    def set_steering_norm(self, norm):
        self.steering_norm = _clamp(norm, -1.0, 1.0)

    def set_throttle_frac(self, frac):
        self.throttle_frac = _clamp(frac, -1.0, 1.0)

    def tick(self):
        if self._closed:
            return
        self.pca.set_pwm(
            self.steering_channel, 0, self._steering_norm_to_pwm(self.steering_norm)
        )
        self.pca.set_pwm(
            self.throttle_channel, 0, self._throttle_frac_to_pwm(self.throttle_frac)
        )

    def stop(self):
        self.steering_norm = 0.0
        self.throttle_frac = 0.0
        if self._closed:
            return
        self.pca.set_pwm(self.steering_channel, 0, self.steering_center_pwm)
        self.pca.set_pwm(self.throttle_channel, 0, self.throttle_stopped_pwm)

    def cleanup(self):
        if self._closed:
            return
        self.stop()
        self.throttle_off()
        self._closed = True
        self.pca.close()

    def throttle_off(self):
        """Kill the throttle pulse entirely (not just "neutral PWM"). With no
        signal an ESC will not drive, even if throttle_stopped_pwm is
        mis-calibrated."""
        if self._closed:
            return
        self.pca.set_channel_off(self.throttle_channel)


class HelmsmanDonkeycar(helmsman.Helmsman):
    def __init__(self):
        self.v = None
        super().__init__()

    def vehicle_init(self):
        self.v = Vehicle(self.config)
        time.sleep(ESC_ARM_SECONDS)  # hold neutral so the ESC can arm
        self.speed_max = self.v.max_speed_cm_per_sec
        self.steering_max = 3.0  # rad/sec, nominal
        # Report differential so navigator rad_per_sec steering is accepted.
        self.vehicle_steering_type = helmsman.STEERING_TYPE_DIFFERENTIAL
        self.wheelbase = 15.0  # cm, DonkeyCar-ish; used only for ackerman conversion

    def vehicle_estop(self):
        if self.v is not None:
            self.v.stop()

    def vehicle_set_speed(self, cm_per_sec):
        self.v.set_throttle_frac(cm_per_sec / self.v.max_speed_cm_per_sec)

    def vehicle_set_steering(self, rad_per_sec):
        # rad_per_sec here carries the navigator's PID correction term.
        self.v.set_steering_norm(rad_per_sec * self.v.steering_gain)

    def vehicle_set_throttle(self, norm):
        # Direct manual throttle (Drive tab / gamepad): -1..1 straight through.
        self.v.set_throttle_frac(norm)

    def vehicle_set_steering_direct(self, norm):
        # Direct manual steering: -1..1 = full-left..full-right servo travel.
        self.v.set_steering_norm(norm)

    def vehicle_set_steering_angle(self, angle, angle_rate):
        self.v.set_steering_norm(angle / self.v.max_steering_radians)

    def vehicle_tick(self):
        self.v.tick()

    def vehicle_cleanup(self):
        if self.v is not None:
            self.v.cleanup()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "node":
        m = HelmsmanDonkeycar()
        m.run()
