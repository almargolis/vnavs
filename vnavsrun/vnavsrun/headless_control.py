"""Headless joystick driver for the rover -- runs on the Pi in a screen
session, no X display, no Tk.

Minimal track-day use: hold the deadman button and drive with the sticks;
tap the record button to capture a mission log + camera frames for later
analysis in mission_control on the laptop. Publishes a compact status message
that a nearby mission_control shows.

    python -m vnavsrun.headless_control node     # the driver
    python -m vnavsrun.headless_control probe    # print live axis/button ids

Config: [HeadlessControl] in vnavs.ini (axis / button indices, limits). Run
`probe`, wiggle each control, and copy the numbers in.

Safety model, consistent with mission_control:
  * drive orders go out ONLY while the deadman button is held; releasing it
    publishes one explicit stop, and the helmsman's own deadman (~3 s) then
    E-stops if anything wedges.
  * every order carries a short (1 s) timer.
  * SIGTERM/SIGINT/SIGHUP and any crash publish a stop + E-stop on the way out.
  * a joystick unplug publishes a stop.
"""

import os
import signal
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

try:
    import pygame

    _HAS_PYGAME = True
except ImportError:  # pragma: no cover - pygame is installed on the Pi
    pygame = None
    _HAS_PYGAME = False

from ezcomms import vnavs_const as vconst
from ezcomms import vnavs_node as vmqtt
from vnavsrun import mission_functions as mf


def _cfg(config, name, default, cast=str):
    try:
        return cast(config.get("HeadlessControl", name))
    except Exception:
        return default


class HeadlessControl(vmqtt.VnavsNode):
    def __init__(self, verbose=False):
        super().__init__(
            subscriptions=[],
            single_threaded=True,
            wait_if_not_connected=False,
            select_timeout_secs=0.01,
            broker_type="F",
            streamer=False,
            verbose=verbose,
        )
        c = self.config
        self.joystick_index = _cfg(c, "JoystickIndex", 0, int)
        self.steer_axis = _cfg(c, "SteerAxis", 0, int)
        self.steer_invert = _cfg(c, "SteerAxisInvert", 0, int) and -1 or 1
        self.throttle_axis = _cfg(c, "ThrottleAxis", 3, int)
        self.throttle_invert = _cfg(c, "ThrottleAxisInvert", 1, int) and -1 or 1
        self.deadzone = _cfg(c, "DeadzoneFrac", 0.12, float)
        self.throttle_max = _cfg(c, "ThrottleMax", 0.35, float)
        self.steer_max = _cfg(c, "SteerMax", 0.7, float)
        self.deadman_button = _cfg(c, "DeadmanButton", 5, int)
        self.record_button = _cfg(c, "RecordButton", 0, int)
        self.estop_button = _cfg(c, "EstopButton", 1, int)
        self.publish_interval = 1.0 / max(1.0, _cfg(c, "PublishHz", 20.0, float))
        self.status_interval = 1.0 / max(1.0, _cfg(c, "StatusHz", 5.0, float))
        self.mission_name = _cfg(c, "MissionName", "headless")

        self.gamepad = None
        self.gamepad_name = ""
        self.armed = False
        self.recording = False
        self.mission_id = ""
        self.note = ""
        self._prev_buttons = set()
        self._last_publish = 0.0
        self._last_status = 0.0
        self._last_throttle = 0.0
        self._last_steer = 0.0
        self._shutdown_done = False

        if not _HAS_PYGAME:
            raise RuntimeError("pygame not available -- cannot read the joystick")
        pygame.init()
        pygame.joystick.init()
        self._open_gamepad()

    # --- joystick plumbing ------------------------------------------------

    def _open_gamepad(self):
        pygame.joystick.quit()
        pygame.joystick.init()
        if pygame.joystick.get_count() <= self.joystick_index:
            self.gamepad = None
            self.gamepad_name = ""
            return False
        self.gamepad = pygame.joystick.Joystick(self.joystick_index)
        self.gamepad.init()
        self.gamepad_name = self.gamepad.get_name()
        print(
            "HEADLESS - joystick '{}' ({} axes, {} buttons)".format(
                self.gamepad_name,
                self.gamepad.get_numaxes(),
                self.gamepad.get_numbuttons(),
            )
        )
        return True

    def _axis(self, index):
        try:
            return self.gamepad.get_axis(index)
        except Exception:
            return 0.0

    def _button(self, index):
        try:
            return bool(self.gamepad.get_button(index))
        except Exception:
            return False

    # --- actions --------------------------------------------------------

    def _toggle_recording(self):
        if self.recording:
            mf.stop_recording(self)
            print("HEADLESS - recording stopped:", self.mission_id)
            self.recording = False
            self.note = "saved " + self.mission_id
        else:
            self.mission_id = mf.start_recording(self, self.mission_name)
            self.recording = True
            self.note = "recording"
            print("HEADLESS - recording started:", self.mission_id)

    def _do_estop(self):
        mf.publish_estop(self)
        self.armed = False
        self.note = "E-STOP"
        print("HEADLESS - E-STOP")

    def _publish_status(self):
        payload = mf.build_status_payload(
            armed=self.armed,
            recording=self.recording,
            mission_id=self.mission_id,
            throttle=self._last_throttle,
            steering=self._last_steer,
            joystick_name=self.gamepad_name,
            note=self.note,
        )
        self.publish(mf.STATUS_TOPIC, payload)

    # --- main loop -----------------------------------------------------

    def client_loop_code(self):
        now = time.time()

        if self.gamepad is None:
            for event in pygame.event.get():
                pass
            if (now - self._last_status) > 1.0:
                self._open_gamepad()
                self.note = "no joystick" if self.gamepad is None else "joystick back"
                self._last_status = now
                self._publish_status()
            return

        reconnect_needed = False
        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEREMOVED:
                reconnect_needed = True
        pygame.event.pump()

        if reconnect_needed:
            print("HEADLESS - joystick removed")
            mf.publish_stop(self)
            self.armed = False
            self.gamepad = None
            self.note = "joystick unplugged"
            self._publish_status()
            return

        buttons = {
            i for i in range(self.gamepad.get_numbuttons()) if self._button(i)
        }
        pressed = buttons - self._prev_buttons
        self._prev_buttons = buttons

        if self.estop_button in pressed:
            self._do_estop()
        if self.record_button in pressed:
            self._toggle_recording()

        deadman = self.deadman_button in buttons

        steer = mf.apply_deadzone(
            self._axis(self.steer_axis) * self.steer_invert, self.deadzone
        )
        throttle = mf.apply_deadzone(
            self._axis(self.throttle_axis) * self.throttle_invert, self.deadzone
        )

        if deadman:
            self._last_throttle = throttle * self.throttle_max
            self._last_steer = steer * self.steer_max
            if (now - self._last_publish) > self.publish_interval:
                mf.publish_manual_drive(self, self._last_throttle, self._last_steer)
                self._last_publish = now
            if not self.armed:
                self.armed = True
                self.note = "driving"
        else:
            if self.armed:
                mf.publish_stop(self)
                self.note = "deadman released"
            self.armed = False
            self._last_throttle = 0.0
            self._last_steer = 0.0

        if (now - self._last_status) > self.status_interval:
            self._last_status = now
            self._publish_status()

    # --- shutdown -----------------------------------------------------

    def cleanup_loop(self):
        self.safe_shutdown()

    def safe_shutdown(self):
        if self._shutdown_done:
            return
        self._shutdown_done = True
        try:
            if self.recording:
                mf.stop_recording(self)
        except Exception as exc:
            print("HEADLESS - stop_recording during shutdown failed:", exc)
        try:
            mf.publish_stop(self)
            mf.publish_estop(self)
        except Exception as exc:
            print("HEADLESS - stop during shutdown failed:", exc)

    def run(self):
        def _on_signal(signum, _frame):
            print("HEADLESS - signal {}, stopping vehicle".format(signum))
            self.safe_shutdown()
            os._exit(0)

        for _sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            try:
                signal.signal(_sig, _on_signal)
            except (ValueError, OSError):
                pass
        try:
            self.main_loop()
        finally:
            self.safe_shutdown()


def probe():
    """Print live axis / button / hat values so the user can fill in
    [HeadlessControl]. No broker connection."""
    if not _HAS_PYGAME:
        print("pygame not available")
        return
    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("no joystick found")
        return
    js = pygame.joystick.Joystick(0)
    js.init()
    print(
        "joystick: {}  ({} axes, {} buttons, {} hats)".format(
            js.get_name(), js.get_numaxes(), js.get_numbuttons(), js.get_numhats()
        )
    )
    print("move each control; Ctrl-C to quit\n")
    try:
        while True:
            pygame.event.pump()
            axes = ["a{}={:+.2f}".format(i, js.get_axis(i)) for i in range(js.get_numaxes())]
            btns = [str(i) for i in range(js.get_numbuttons()) if js.get_button(i)]
            hats = [str(js.get_hat(i)) for i in range(js.get_numhats())]
            print(
                "  " + " ".join(axes)
                + "  | buttons: " + (",".join(btns) or "-")
                + "  | hats: " + (" ".join(hats) or "-")
                + " " * 8,
                end="\r",
            )
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "node"
    if cmd == "probe":
        probe()
    elif cmd == "node":
        HeadlessControl().run()
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv)
