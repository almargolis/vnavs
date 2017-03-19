from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import multiprocessing
import os
import Queue
import socket
import sys
import time

import paho.mqtt.client as mqtt

if sys.version_info[0] < 3:
    import ConfigParser
else:
    import configparser as ConfigParser

config_file_path = os.path.expanduser("~/vnavs.ini")
handler_method_prefix = 'rmsg_'

#
# Streamer() is the socket_xfer writer function which runs in its own process.
# It empties the FIFO system queue as quickly as it can and converts that to a
# LIFO queue so the receiver has the most recent image for navigation. Older
# images are sent if possible for archiving. The buffer size is limited due to
# memory contraints and excess images are discarded.
#
# This process assumes that we have a network that is faster than storage (SDCARD).
# We therefore manage memory to avoid hitting the swap disk.
# Getting 
#
def Streamer(q, q_len, host_ip, host_socket):
    lifo = []
    while True:
        # This process runs forever
        while True:
            # After sending each file, quickly empty the system queue and turn it into a LIFO
            try:
                stream = q.get_nowait()
                print("LIFO", len(lifo))
                if len(lifo) > 6:
                    lifo = lifo[-3:]
                    print("DISCARD")
                lifo.append(stream)
                q_len.value = len(lifo)
            except Queue.Empty:
                #print("NO QUEUE", len(lifo))
                break			# the interprocess queue is empty
        if len(lifo) > 0:
            stream = lifo.pop()
            print("SEND", len(lifo), len(stream))
            q_len.value = len(lifo)
            s = socket.socket()
            s.connect((host_ip, host_socket))
            ix = 0
            while ix <= len(stream):
                # potentially check queue here. we want to keep the queue empty and
                # discard from the LIFO so we are always sending the most recent
                # images. We don't want socket_xfer.write() to discard. Need more
                # more stats to see if this is an issue.
                s.send(stream[ix:ix+1024])
                ix += 1024
            s.close()

#
# socket_xfer encapsulates a multi-processing point-to-point file transfer process.
# It was developed to transfer files between an RPI and a faster host for VNAVS.
# The client application just writes as if this were a reliable, single-threaded
# application. The ugly detals are completely hidden.
#
class socket_xfer(object):
    def __init__(self):
        self.server_ip = "192.168.8.11"
        self.server_socket = 3050
        self.capture_ct = 0
        self.start = time.time()
        self.queue = multiprocessing.Queue()
        self.q_len = multiprocessing.Value('i', 0)
        self.streamer = multiprocessing.Process(target=Streamer, args=(self.queue, self.q_len, self.server_ip, self.server_socket))
        self.streamer.start()
        self.timer_ct = 0
        self.timer_skip_ct = 0
        self.timer_start = time.clock()

    def stop(self):
        self.streamer.join()

    def write(self, stream):
        self.capture_ct += 1
        if self.q_len.value > 3:
            self.timer_skip_ct += 1
            print("NO Q")
            return
        print("Q IT")
        self.queue.put(stream)
        self.timer_ct += 1
        if self.timer_ct >= 10:
            timer_stop = time.clock()
            print("Qd %d in %f secs SKIPPED %d" % (self.timer_ct, timer_stop - self.timer_start, self.timer_skip_ct))
            self.timer_ct = 0
            self.timer_skip_ct = 0
            self.timer_start = timer_stop

class mqtt_node(object):
    def __init__(self, Subscriptions=[], Blocking=False, BlockingTimeoutSecs=1.0, Verbose=True):
        self.config = ConfigParser.SafeConfigParser()
        self.config.readfp(open(config_file_path))
        self.blocking_mode = Blocking
        self.blocking_timeout = BlockingTimeoutSecs
        self.subscriptions = Subscriptions
        self.handlers = {}
        self.broker_host = self.config.get("MqttBroker", "Host")
        self.broker_port = int(self.config.get("MqttBroker", "Port"))	# 1883
        self.broker_timeout = 60
        self.verbose = False
        self.debug = 0
        self.mqttc = None
        self.verbose = Verbose
        if self.blocking_mode:
            print("Blocking Mode")
        else:
            print("Non-Blocking Mode")

    def Connect(self):
        self.mqttc = mqtt.Client()
        # Assign event callbacks
        self.mqttc.on_message = self.on_message
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_publish = self.on_publish
        self.mqttc.on_subscribe = self.on_subscribe
        # Connect
        self.mqttc.connect(self.broker_host, self.broker_port, self.broker_timeout)
        if self.blocking_mode:
            if self.blocking_timeout <= 0:
                self.mqttc.loop_forever()
            # else, periodically call CheckMqtt()
        else:
            # this starts a separate thread which is handy, but tkinter and others don't support threads
            self.mqttc.loop_start()

    def CheckMqtt(self):
         self.mqttc.loop(timeout=self.blocking_timeout)

    def Disconnect(self):
        if self.blocking_mode:
            pass
        else:
            self.mqttc.loop_stop(force=False)

    def MessageStr(self, msg):
        max = 25
        s = str(msg)
        if len(s) <= max:
            return s
        return s[:max] + ' [...]'

    def RegisterMessageHandlers(self):
        self.handlers = {}
        for this_topic in self.subscriptions:
            handler_name = handler_method_prefix + this_topic.replace('/', '_')
            handler_method = getattr(self, handler_name, None)
            if handler_method is None:
                print("No message handler for topic '%s'" % (this_topic))
            self.handlers[this_topic] = handler_method
            self.mqttc.subscribe(this_topic, 0)

    def on_connect(self, client, userdata, flags, rc):
        print("on_connect() rc: " + str(rc))
        self.RegisterMessageHandlers()

    def on_message(self, client, userdata, message):
        print("on_message()", message.topic + " " + str(message.qos) + " " + self.MessageStr(message.payload))
        handler_method = self.handlers[message.topic]
        handler_method(message.payload.decode("utf-8"))

    def on_publish(self, client, userdata, mid):
        if self.verbose:
            print("on_publish() mid: " + str(mid))

    def on_subscribe(self, client, userdata, mid, granted_qos):
        print("Subscribed: " + str(mid) + " " + str(granted_qos))

    def on_log(self, client, userdata, level, buf):
        print(buf)

def Test_Mqtt_Node():
    n = mqtt_node(Subscriptions=['test'], Blocking=True)
    n.Connect()

