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

    def rmsg_wildcard(self, topic, payload):
        print("Send {} to fast {}".format(topic, payload))
        parts = topic.split('/')
        self.fastBroker.Publish(parts[1], payload, source=parts[0])

class translate_fast_to_mosquitto(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=True):
        super().__init__(Subscriptions=['cameraman/pic_ready'], Blocking=True, BlockingTimeoutSecs=0.0, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.mosquitto = translate_mosquitto_to_fast()
        self.mosquitto.fastBroker = self
        self.mosquitto.Connect()

    def rmsg_wildcard(self, topic, payload):
        print("Send {} to fast {}".format(topic, payload))
        parts = topic.split('/')
        self.mosquitto.Publish(source[1], payload, source=parts[0])

    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which hands exceptions and propper shutdown.
        #
        self.mosquitto.CheckMqtt()	# checks for mosquitto messages
        time.sleep(0.1)			# leave cpu for automation, this is human speed

def RunNode():
    h = translate_fast_to_mosquitto()
    h.Loop()
    h.Disconnect()

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        RunNode()

