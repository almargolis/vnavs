# DEPRECATED: older evdev prototype (cm/s + rad/s path through the PID gain,
# hard-coded /dev/input/eventN, `raise Error` on no pad). Superseded by
# vnavsrun.headless_control (pygame, deadman button, recording, status). Kept
# only for reference.
import platform
import sys
import time

import evdev

from ezcomms import vnavs_const as vconst
from ezcomms import vnavs_node as vmqtt

SPEED_MAX = 40.0  # cm/sec, max linear velocity for axis mapping
STEERING_MAX = 3.0  # rad/sec, max angular velocity for axis mapping


def PrintCapability(gamepad):
    print(gamepad)
    print(gamepad.capabilities(absinfo=True, verbose=True))
    print("==============")
    cap = gamepad.capabilities(absinfo=True)
    for thisType, thisCap in cap.items():
        if thisType == evdev.ecodes.EV_KEY:
            print("KEY", thisCap)
        elif thisType == evdev.ecodes.EV_ABS:
            for thisJoy in thisCap:
                print("ABS", thisJoy[0], thisJoy[1].min, thisJoy[1].max)
        else:
            print("XXX", thisType, thisCap)


def scale_axis(raw_value, axis_min, axis_max, target_max):
    """Scale raw axis value to range [-target_max, +target_max]."""
    axis_range = float(axis_max - axis_min)
    if axis_range == 0:
        return 0.0
    normalized = (float(raw_value - axis_min) / axis_range) * 2.0 - 1.0
    return normalized * target_max


class joystick(vmqtt.VnavsNode):
    def __init__(self, verbose=False):
        super().__init__(
            subscriptions=[
                vmqtt.Subscription(
                    vconst.mission_log_start_topic,
                    async_delivery=True,
                    handler=self.OnMissionLogStart,
                ),
                vmqtt.Subscription(
                    vconst.mission_log_stop_topic,
                    async_delivery=True,
                    handler=self.OnMissionLogStop,
                ),
            ],
            single_threaded=True,
            wait_if_not_connected=False,
            select_timeout_secs=0.01,
            broker_type="F",
            streamer=False,
            verbose=verbose,
        )
        self.system = platform.system()
        if self.system == "Linux":
            pass
            ## this only works under linux
        if not self.ConfigureJoystick("/dev/input/event2"):
            if not self.ConfigureJoystick("/dev/input/event3"):
                if not self.ConfigureJoystick("/dev/input/event4"):
                    raise Error("No Joystick found!")
        self.helmsmanChanged = False
        self.last_publish = 0.0

    def ConfigureJoystick(self, port):
        self.gamepad = evdev.InputDevice(port)
        PrintCapability(self.gamepad)
        self.gamepadAxis = {}
        capabilities = self.gamepad.capabilities(absinfo=True)
        for thisType, thisCapability in capabilities.items():
            if thisType == evdev.ecodes.EV_ABS:
                for thisAxis in thisCapability:
                    self.gamepadAxis[thisAxis[0]] = thisAxis[1]
        self.gamepadMap = {}  # This map varies with controller type/brand
        self.speedAxisCode = 1
        self.directionAxisCode = 2
        self.gamepadMap[self.speedAxisCode] = self.SaveSpeed
        self.gamepadMap[self.directionAxisCode] = self.SaveDirection
        self.mission_logging = False
        try:
            self.speedAxis = self.gamepadAxis[self.speedAxisCode]
            self.speedValue = self.gamepadAxis[self.speedAxisCode].value
            self.directionAxis = self.gamepadAxis[self.directionAxisCode]
        except KeyError:
            return False
        self.directionValue = self.gamepadAxis[self.directionAxisCode].value
        return True

    def OnMissionLogStart(self, payload):
        self.mission_logging = True

    def OnMissionLogStop(self, payload):
        self.mission_logging = False

    def SaveSpeed(self, event):
        if self.speedValue == event.value:
            return  # No change in value
        self.speedAxis = self.gamepadAxis[event.code]
        self.speedValue = event.value
        self.helmsmanChanged = True

    def SaveDirection(self, event):
        if self.directionValue == event.value:
            return  # No change in value
        self.speedAxis = self.gamepadAxis[event.code]
        self.directionValue = event.value
        self.helmsmanChanged = True

    def PublishHelmsman(self):
        payload = {}
        cm_per_sec = scale_axis(
            self.speedValue, self.speedAxis.min, self.speedAxis.max, SPEED_MAX
        )
        payload["cm_per_sec"] = cm_per_sec
        if not self.mission_logging:
            rad_per_sec = scale_axis(
                self.directionValue,
                self.directionAxis.min,
                self.directionAxis.max,
                STEERING_MAX,
            )
            payload["rad_per_sec"] = rad_per_sec
        self.publish(vconst.helmsman_orders_topic, payload)
        self.helmsmanChanged = False
        print(payload)
        self.last_publish = time.time()

    def client_loop_code(self):
        gamepad_events = self.gamepad.read()
        try:
            for event in gamepad_events:
                # This may process a series of events if the system is busy
                if event.code in self.gamepadMap:
                    self.gamepadMap[event.code](event)
            if self.helmsmanChanged:
                # Speed and direction ignore any intermediate changes, send latest value if changed
                self.PublishHelmsman()
            elif (time.time() - self.last_publish) > 1.0:
                self.PublishHelmsman()
        except IOError as e:
            if e.errno == 11:
                pass


if __name__ == "__main__":
    if sys.argv[1] == "node":
        m = joystick()
        m.main_loop()
