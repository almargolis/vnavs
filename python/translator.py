from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import datetime
import io
import json
import os
import sys
import threading
import time
import traceback

import vnavs_mqtt
import paho.mqtt.client as mqtt

class translate_mosquitto_to_fast(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=True):
        super().__init__(Subscriptions=['cameraman/orders', 'helmsman/orders', 'navigator/mode', 'navigator/waypoint'],
					Blocking=True, BlockingTimeoutSecs=0.0, BrokerType='M', Streamer=False, Verbose=Verbose)
        self.fastBroker = None

    def rmsg_cameraman_orders(self, msg):
        print("Send cameraman/orders to fast", msg)
        self.fastBroker.mqttc.publish('cameraman/orders', msg)

    def rmsg_helmsman_orders(self, msg):
        print("Send helmsman/orders to fast", msg)
        self.fastBroker.mqttc.publish('helmsman/orders', msg)

    def rmsg_navigator_mode(self, msg):
        print("Send orders to fast", msg)
        self.fastBroker.mqttc.publish('navigator/mode', msg)

    def rmsg_navigator_waypoint(self, msg):
        print("Send orders to fast", msg)
        self.fastBroker.mqttc.publish('navigator/waypoint', msg)

class translate_fast_to_mosquitto(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=True):
        super().__init__(Subscriptions=['cameraman/pic_ready', 'engineer_1/status'], Blocking=True, BlockingTimeoutSecs=0.0, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.mosquitto = translate_mosquitto_to_fast()
        self.mosquitto.fastBroker = self
        self.mosquitto.Connect()

    def rmsg_cameraman_pic_ready(self, msg):
        print("Send cameraman/pic_ready to mosquitto", msg)
        self.mosquitto.mqttc.publish('cameraman/pic_ready', msg)

    def rmsg_engineer_1_status(self, msg):
        print("Send gps to mosquitto", msg)
        self.mosquitto.mqttc.publish('engineer_1/status', msg)

    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which hands exceptions and propper shutdown.
        #
        self.mosquitto.CheckMqtt()	# checks for mosquitto messages
        time.sleep(0.1)			# leave cpu for automation, this is human speed

if __name__ == '__main__':
    h = translate_fast_to_mosquitto()
    h.Loop()
    h.Disconnect()

