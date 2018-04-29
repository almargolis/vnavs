from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import sys
import evdev
import platform
import time

import vnavs_const as vconst
import vnavs_mqtt

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

class joystick(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=[],
					Readers=[],
					SingleThreaded=True, BlockIfNotConnected=False, 
					SelectTimeoutSecs=0.01,
					BrokerType='F', Streamer=False, Verbose=Verbose)
        self.system =  platform.system()
        if self.system == 'Linux':
            pass
            ## this only works under linux
        self.gamepad = evdev.InputDevice('/dev/input/event3')
        PrintCapability(self.gamepad)
        self.gamepadAxis = {}
        capabilities = self.gamepad.capabilities(absinfo=True)
        for thisType, thisCapability in capabilities.items():
            if thisType == evdev.ecodes.EV_ABS:
                for thisAxis in thisCapability:
                    self.gamepadAxis[thisAxis[0]] = thisAxis[1]
        self.gamepadMap = {}				# This map varies with controller type/brand
        self.speedAxisCode = 1
        self.directionAxisCode = 2
        self.gamepadMap[self.speedAxisCode] = self.SaveSpeed
        self.gamepadMap[self.directionAxisCode] = self.SaveDirection
        self.speedAxis = self.gamepadAxis[self.speedAxisCode]
        self.speedValue = self.gamepadAxis[self.speedAxisCode].value
        self.directionAxis = self.gamepadAxis[self.directionAxisCode]
        self.directionValue = self.gamepadAxis[self.directionAxisCode].value
        self.helmsmanChanged = False
        self.last_publish = 0.0

    def SaveSpeed(self, event):
        if self.speedValue == event.value:
            return					# No change in value
        self.speedAxis = self.gamepadAxis[event.code]
        self.speedValue = event.value
        self.helmsmanChanged = True

    def SaveDirection(self, event):
        if self.directionValue == event.value:
            return					# No change in value
        self.speedAxis = self.gamepadAxis[event.code]
        self.directionValue = event.value
        self.helmsmanChanged = True

    def PublishHelmsman(self):
        payload = {}
        payload['speed'] = self.speedValue
        payload['speed_scale_min'] = self.speedAxis.min
        payload['speed_scale_max'] = self.speedAxis.max
        payload['heading'] = self.directionValue
        payload['heading_scale_min'] = self.directionAxis.min
        payload['heading_scale_max'] = self.directionAxis.max
        self.Publish(vconst.helmsman_orders_topic, payload)
        self.helmsmanChanged = False
        print(payload)
        self.last_publish = time.time()

    def DoLoop(self):
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

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        vnavs_mqtt.LaunchNode(joystick)




