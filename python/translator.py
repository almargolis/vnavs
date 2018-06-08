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

import vnavs_mqtt as vmqtt
import vnavs_const as vconst
import paho.mqtt.client as mqtt

class translate_mosquitto_to_fast(vmqtt.mqtt_node):
    def __init__(self, Verbose=True):
        super().__init__(Subscriptions=[
                                            vmqtt.Subscription(vconst.cameraman_orders_topic, async=True,
                                                        handler=self.OnMessage, handler_needs_topic=True),
                                            vmqtt.Subscription(vconst.helmsman_orders_topic, async=True,
                                                        handler=self.OnMessage, handler_needs_topic=True),
                                            vmqtt.Subscription(vconst.navigator_mode_topic, async=True,
                                                        handler=self.OnMessage, handler_needs_topic=True),
                                            vmqtt.Subscription(vconst.navigator_waypoint_topic, async=True,
                                                        handler=self.OnMessage, handler_needs_topic=True),
                                        ],
					SingleThreaded=True, SelectTimeoutSecs=0.0, BrokerType='M', Streamer=False, Verbose=Verbose)
        self.fastBroker = None

    def OnMessage(self, topic, payload):
        print("Send {} to fast {}".format(topic, payload))
        self.fastBroker.Publish(topic, payload)

class translate_fast_to_mosquitto(vmqtt.mqtt_node):
    def __init__(self, Verbose=True):
        super().__init__(Subscriptions=[
                                        vmqtt.Subscription(vconst.cameraman_pic_ready_topic, async=True,
                                                        handler=self.OnMessage, handler_needs_topic=True),
                                    ],
                    SingleThreaded=True, SelectTimeoutSecs=0.0, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.mosquitto = translate_mosquitto_to_fast()
        self.mosquitto.fastBroker = self
        self.mosquitto.ConnectToMqttServer()

    def OnMessage(self, topic, payload):
        print("Send {} to fast {}".format(topic, payload))
        self.mosquitto.Publish(topic, payload)

    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which hands exceptions and propper shutdown.
        #
        self.mosquitto.CheckMqttPendingActivity()	# checks for mosquitto messages
        time.sleep(0.1)			# leave cpu for automation, this is human speed

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        vmqtt.LaunchNode(translate_fast_to_mosquitto)
