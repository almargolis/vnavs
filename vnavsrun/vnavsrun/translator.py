import datetime
import io
import json
import os
import sys
import threading
import time
import traceback

import paho.mqtt.client as mqtt

from ezcomms import vnavs_const as vconst
from ezcomms import vnavs_node as vmqtt


class translate_mosquitto_to_fast(vmqtt.VnavsNode):
    def __init__(self, verbose=True):
        super().__init__(
            subscriptions=[
                vmqtt.Subscription(
                    vconst.cameraman_orders_topic,
                    async_delivery=True,
                    handler=self.OnMessage,
                    handler_needs_topic=True,
                ),
                vmqtt.Subscription(
                    vconst.helmsman_orders_topic,
                    async_delivery=True,
                    handler=self.OnMessage,
                    handler_needs_topic=True,
                ),
                vmqtt.Subscription(
                    vconst.navigator_mode_topic,
                    async_delivery=True,
                    handler=self.OnMessage,
                    handler_needs_topic=True,
                ),
                vmqtt.Subscription(
                    vconst.navigator_waypoint_topic,
                    async_delivery=True,
                    handler=self.OnMessage,
                    handler_needs_topic=True,
                ),
            ],
            single_threaded=True,
            select_timeout_secs=0.0,
            broker_type="M",
            streamer=False,
            verbose=verbose,
        )
        self.fastBroker = None

    def OnMessage(self, topic, payload):
        print(f"Send {topic} to fast {payload}")
        self.fastBroker.publish(topic, payload)


class translate_fast_to_mosquitto(vmqtt.VnavsNode):
    def __init__(self, verbose=True):
        super().__init__(
            subscriptions=[
                vmqtt.Subscription(
                    vconst.cameraman_pic_ready_topic,
                    async_delivery=True,
                    handler=self.OnMessage,
                    handler_needs_topic=True,
                ),
            ],
            single_threaded=True,
            select_timeout_secs=0.0,
            broker_type="F",
            streamer=False,
            verbose=verbose,
        )
        self.mosquitto = translate_mosquitto_to_fast()
        self.mosquitto.fastBroker = self
        self.mosquitto.connect_to_mqtt_server()

    def OnMessage(self, topic, payload):
        print(f"Send {topic} to fast {payload}")
        self.mosquitto.publish(topic, payload)

    def client_loop_code(self):
        self.mosquitto.check_mqtt_pending_activity()  # checks for mosquitto messages
        time.sleep(0.1)  # leave cpu for automation, this is human speed


if __name__ == "__main__":
    if sys.argv[1] == "node":
        m = translate_fast_to_mosquitto()
        m.main_loop()
