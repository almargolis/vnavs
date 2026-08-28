"""Minimal PCA9685 16-channel PWM / servo driver for VNAVS.

Self-contained: talks to the chip over I2C using ``smbus2`` only, with no
Adafruit / Blinka dependency. Written for the DonkeyCar-style controller
board (silkscreen "DuinoFun") that a Raspberry Pi drives over I2C -- one
channel for the steering servo, one for the ESC / throttle.

Register map and timing follow the NXP PCA9685 datasheet. The internal
oscillator runs at 25 MHz.
"""

import math
import time

from smbus2 import SMBus

# Registers
MODE1 = 0x00
MODE2 = 0x01
PRESCALE = 0xFE
LED0_ON_L = 0x06
ALL_LED_ON_L = 0xFA
ALL_LED_OFF_H = 0xFD

# MODE1 bits
MODE1_RESTART = 0x80
MODE1_AI = 0x20  # register auto-increment
MODE1_SLEEP = 0x10
MODE1_ALLCALL = 0x01

# MODE2 bits
MODE2_OUTDRV = 0x04  # totem-pole outputs

OSC_CLOCK_HZ = 25_000_000
PWM_STEPS = 4096

DEFAULT_ADDRESS = 0x40
DEFAULT_BUS = 1
DEFAULT_FREQ_HZ = 60.0


class Pca9685:
    """Controls one PCA9685 board on a given I2C bus / address."""

    __slots__ = ("bus", "address", "freq_hz", "_smbus")

    def __init__(self, bus=DEFAULT_BUS, address=DEFAULT_ADDRESS, freq_hz=DEFAULT_FREQ_HZ):
        self.bus = bus
        self.address = address
        self.freq_hz = freq_hz
        self._smbus = SMBus(bus)
        self._init_chip()
        self.set_frequency(freq_hz)

    def _init_chip(self):
        self.all_off()
        self._smbus.write_byte_data(self.address, MODE2, MODE2_OUTDRV)
        self._smbus.write_byte_data(self.address, MODE1, MODE1_ALLCALL)
        time.sleep(0.005)  # wait for oscillator
        mode1 = self._smbus.read_byte_data(self.address, MODE1)
        mode1 &= ~MODE1_SLEEP
        self._smbus.write_byte_data(self.address, MODE1, mode1)
        time.sleep(0.005)

    def set_frequency(self, freq_hz):
        """Set the PWM frequency (Hz) for all channels."""
        self.freq_hz = float(freq_hz)
        prescale = int(round(OSC_CLOCK_HZ / (PWM_STEPS * self.freq_hz)) - 1)
        prescale = max(3, min(255, prescale))
        old_mode1 = self._smbus.read_byte_data(self.address, MODE1)
        sleep_mode1 = (old_mode1 & ~MODE1_RESTART) | MODE1_SLEEP
        self._smbus.write_byte_data(self.address, MODE1, sleep_mode1)
        self._smbus.write_byte_data(self.address, PRESCALE, prescale)
        self._smbus.write_byte_data(self.address, MODE1, old_mode1)
        time.sleep(0.005)
        self._smbus.write_byte_data(self.address, MODE1, old_mode1 | MODE1_RESTART | MODE1_AI)

    def set_pwm(self, channel, on_count, off_count):
        """Write raw 12-bit on/off counts (0..4095) for one channel."""
        on_count = int(on_count) & 0x0FFF
        off_count = int(off_count) & 0x0FFF
        base = LED0_ON_L + 4 * channel
        self._smbus.write_i2c_block_data(
            self.address,
            base,
            [
                on_count & 0xFF,
                on_count >> 8,
                off_count & 0xFF,
                off_count >> 8,
            ],
        )

    def set_pulse_us(self, channel, microseconds):
        """Drive a channel with a servo-style pulse width in microseconds."""
        period_us = 1_000_000.0 / self.freq_hz
        off_count = int(round(PWM_STEPS * microseconds / period_us))
        off_count = max(0, min(PWM_STEPS - 1, off_count))
        self.set_pwm(channel, 0, off_count)

    def set_duty(self, channel, fraction):
        """Drive a channel at a duty-cycle fraction in the range 0.0..1.0."""
        fraction = max(0.0, min(1.0, fraction))
        if fraction <= 0.0:
            self.set_channel_off(channel)
            return
        if fraction >= 1.0:
            self.set_pwm(channel, PWM_STEPS, 0)  # full-on bit
            return
        self.set_pwm(channel, 0, int(round(fraction * (PWM_STEPS - 1))))

    def set_channel_off(self, channel):
        """Fully de-energize one channel (0% duty)."""
        base = LED0_ON_L + 4 * channel
        self._smbus.write_i2c_block_data(self.address, base, [0x00, 0x00, 0x00, 0x10])

    def all_off(self):
        """De-energize every channel."""
        self._smbus.write_i2c_block_data(
            self.address, ALL_LED_ON_L, [0x00, 0x00, 0x00, 0x10]
        )

    def close(self):
        try:
            self.all_off()
        finally:
            self._smbus.close()


def angle_to_pulse_us(angle_norm, center_us, half_range_us):
    """Map a normalized steering value in -1.0..1.0 to a servo pulse width."""
    angle_norm = max(-1.0, min(1.0, angle_norm))
    return center_us + angle_norm * half_range_us


def radians_to_norm(radians, max_radians):
    """Map a steering angle in radians to a normalized -1.0..1.0 value."""
    if max_radians <= 0:
        return 0.0
    return max(-1.0, min(1.0, radians / max_radians))


# --------------------------------------------------------------------------
# Live bench self-test (python -m vnavslib.pca9685  /  python pca9685.py)
# --------------------------------------------------------------------------

class _KeyWatch:
    """Context manager: put the tty in cbreak mode so a single keypress
    can be detected without blocking or waiting for Enter."""

    def __init__(self):
        self.fd = None
        self._old = None

    def __enter__(self):
        import sys

        if not sys.stdin.isatty():
            return self
        import termios
        import tty

        self.fd = sys.stdin.fileno()
        self._old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._old)

    def pressed(self):
        """True if a key is waiting in the input buffer. Drains it."""
        import select
        import sys

        if self.fd is None:
            return False
        if select.select([sys.stdin], [], [], 0)[0]:
            _drain_fd(self.fd)
            return True
        return False


def _drain_fd(fd):
    import os

    try:
        while os.read(fd, 64):
            pass
    except (BlockingIOError, OSError):
        pass


def _probe(bus, address):
    """Return None if a PCA9685 answers on (bus, address), else an error string."""
    try:
        probe = SMBus(bus)
    except (OSError, FileNotFoundError) as exc:
        return f"cannot open I2C bus {bus}: {exc}  (is I2C enabled? see raspi-config)"
    try:
        probe.read_byte_data(address, MODE1)
    except OSError as exc:
        return f"no device at 0x{address:02x} on bus {bus}: {exc}"
    finally:
        probe.close()
    return None


def _dwell(keys, seconds):
    """Sleep, but bail out with KeyboardInterrupt the moment a key is hit."""
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if keys.pressed():
            raise KeyboardInterrupt
        time.sleep(0.02)


def _sweep(pca, channel, keys, lo_us, hi_us, step_us, dwell_s):
    """Walk a channel's pulse width lo -> hi -> lo, pausing between steps
    so a human can watch the servo travel. Raises KeyboardInterrupt the
    instant any key is hit."""
    ramp_up = list(range(lo_us, hi_us + 1, step_us))
    seq = ramp_up + ramp_up[::-1]
    for us in seq:
        if keys.pressed():
            raise KeyboardInterrupt
        pca.set_pulse_us(channel, us)
        print(f"  ch{channel}: {us:4d} us", end="\r", flush=True)
        _dwell(keys, dwell_s)
    print()


def _selftest(argv=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Live PCA9685 bench test: probe the chip, then sweep the "
        "first two channels through the servo pulse range. Hit any key to "
        "abort immediately if something looks wrong.",
    )
    parser.add_argument("--bus", type=int, default=DEFAULT_BUS)
    parser.add_argument(
        "--address", type=lambda s: int(s, 0), default=DEFAULT_ADDRESS
    )
    parser.add_argument("--freq", type=float, default=DEFAULT_FREQ_HZ)
    parser.add_argument("--channels", default="1,0",
                        help="comma-separated channels to exercise (default 1,0)")
    parser.add_argument("--min-us", type=int, default=1100)
    parser.add_argument("--max-us", type=int, default=1900)
    parser.add_argument("--center-us", type=int, default=1500)
    parser.add_argument("--step-us", type=int, default=25)
    parser.add_argument("--dwell", type=float, default=0.20,
                        help="seconds between steps (default 0.20)")
    args = parser.parse_args(argv)

    err = _probe(args.bus, args.address)
    if err:
        print(f"PCA9685 self-test: NOT CONNECTED -- {err}")
        sys.exit(1)
    print(f"PCA9685 found at 0x{args.address:02x} on I2C bus {args.bus}.")

    channels = [int(c) for c in args.channels.split(",") if c.strip() != ""]

    prompt = (
        "\n*** Make sure the rover is on blocks / wheels off the ground. ***\n"
        f"About to sweep channels {channels} from {args.min_us} to "
        f"{args.max_us} us in {args.step_us} us steps ({args.dwell}s dwell).\n"
        "Press any key during the sweep to abort (channels go OFF).\n"
        "Enter to start, Ctrl-C to quit: "
    )
    try:
        input(prompt)
    except (EOFError, KeyboardInterrupt):
        print("aborted.")
        sys.exit(0)

    pca = Pca9685(bus=args.bus, address=args.address, freq_hz=args.freq)
    try:
        with _KeyWatch() as keys:
            for ch in channels:
                print(f"channel {ch}: centering at {args.center_us} us")
                pca.set_pulse_us(ch, args.center_us)
                _dwell(keys, 0.5)
                print(f"channel {ch}: sweeping")
                _sweep(pca, ch, keys, args.min_us, args.max_us,
                       args.step_us, args.dwell)
                pca.set_pulse_us(ch, args.center_us)
                print(f"channel {ch}: back to center")
        print("\nself-test complete -- all channels OFF.")
    except KeyboardInterrupt:
        print("\n!! ABORTED by keypress -- all channels OFF.")
    finally:
        pca.close()


if __name__ == "__main__":
    _selftest()
