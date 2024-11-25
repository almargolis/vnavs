#
# These are MQTT and FMQTT clients that handle a lot of boilerplate for
# threading consistent API for both types of servers.
#

import datetime
import queue
import socket
import sys
import threading
import time

import paho.mqtt.client as mqtt

from vnavslib import vnavs_const as vconst
from vnavslib import vnavs_comms as vcomms


SUBSCRIPTION_MODE_ALL = "a"
SUBSCRIPTION_MODE_LATEST = "l"


class FastMqttMessage:
    def __init__(self, topic, payload, qos=0, mid=0):
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.mid = mid  # this is a fast mqtt extension


class FastMqttClient(vcomms.SocketWrapperClient):
    __slots__ = ("on_connect", "on_message")

    def __init__(self, verbose=False):
        super().__init__(ini_section="MqttFast", verbose=verbose)
        self.on_message = None
        self.on_connect = None

    def connect(self, **kwargs):
        # Hmmm ... maybe dangerous. Clients have both connect() and Connect()
        # doing slightly different things.
        # Above comment is deprecated due to PEP8 transition, but I'm
        # leaving it here in case I discover there really are two different
        # functions that need different names.
        super().connect(**kwargs)
        if self.on_connect is not None:
            client = None  # not implemented
            userdata = None  # not implemented
            flags = None  # not implemented
            rc = 0  # not implemented
            self.on_connect(client, userdata, flags, rc)

    def blocking_write_socket(self, msg):
        msg_sent = super().blocking_write_socket(msg)
        if msg_sent:
            mid = 0  # not implemented -- message id
            return (mqtt.MQTT_ERR_SUCCESS, mid)
        else:
            mid = 0  # not sue if this matches Paho MQTT behavior
            return (mqtt.MQTT_ERR_NO_CONN, mid)

    def loop(self, timeout=1.0):
        self.select(timeout=timeout)

    # I probably created these for compatibility with the Paho MQTT
    # client but I am finding them confusing right now. I am simplifying
    # now and will figure out compatibility if I ever get back to
    # testing Mosquitto.
    # def loop_forever(self):
    #    self.select_forever()
    # def start_thread(self):
    #    # was named loop_start()
    #    self.select_thread_start()
    # def loop_stop(self, force=False):
    #    # unused force parameter exists for mosquitto compatibility
    #    self.select_thread_stop()

    def publish(self, topic, msg, qos=0):
        self.queue_message_z(["publish", topic, msg])
        mid = 0  # not implemented -- message id
        return (mqtt.MQTT_ERR_SUCCESS, mid)

    def read(self, topic, qos=0):
        # This is a non-repeating request to get the latest message
        self.queue_message_z(["read", topic])
        mid = 0  # not implemented -- message id
        return (mqtt.MQTT_ERR_SUCCESS, mid)

    def subscribe(self, topic, qos, timeout=1.0, mode=SUBSCRIPTION_MODE_ALL):
        packet_sent = False
        start_time = time.time()
        while not packet_sent:
            try:
                print("SUBSCRIBE", topic)
                self.queue_message_z(["subscribe", topic, mode])
                packet_sent = True
            except socket.error as e:
                # socket.error: [Errno 11] Resource temporarily unavailable
                if e.errno == 11:
                    return
                if (e.errno == 11) and ((time.time() - start_time) < timeout):
                    continue
                raise

    def process_message(self, s, message):
        if message[0] == "":
            return
        if message[0] == "message":
            topic = message[1]
            mid = message[2]
            payload = message[3]
            if self.on_message is not None:
                mqtt_message = FastMqttMessage(topic, payload, mid=mid)
                client = None  # not implemented
                userdata = None  # not implemented
                self.on_message(client, userdata, mqtt_message)


class PahoClient(mqtt.Client):
    # This should be a very thin wrapper.
    # FastMqttClient() should have as close to identical API as Paho client.
    # This object reconciles any unavoidable differences so MqqtNode works
    # with either server.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.connected = False
        self.connect_in_progress = False

    def connect(self, *args, **kwargs):
        super().connect(*args, **kwargs)
        self.connected = True
        self.connect_in_progress = False

    def disconnect(self):
        super().disconnect()
        self.connected = False
        self.connect_in_progress = False

    def subscribe(self, topic, qos, timeout=1.0, mode=SUBSCRIPTION_MODE_ALL):
        super().subscribe(topic, qos)
