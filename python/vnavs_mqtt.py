from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import multiprocessing
import os
import Queue
import socket
import SocketServer
import sys
import time

import paho.mqtt.client as mqtt

if sys.version_info[0] < 3:
    import ConfigParser
else:
    import configparser as ConfigParser

config_file_path = os.path.expanduser("~/vnavs.ini")
handler_method_prefix = 'rmsg_'

stop_process = False


def PiShutdown():
    command = "/usr/bin/sudo /sbin/shutdown -h now"
    import subprocess
    process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
    output = process.communicate()[0]
    print(output)


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
            try:
                s.connect((host_ip, host_socket))
            except socket.error as e:
                # most likely errno=111, strerror="Connection refused"
                print(e.errno, e.strerror)
                return
            except (KeyboardInterrupt, SystemExit):
                print("Terminated @ connect() via KeyboardInterrupt")
                return
            ix = 0
            while ix <= len(stream):
                # potentially check queue here. we want to keep the queue empty and
                # discard from the LIFO so we are always sending the most recent
                # images. We don't want socket_xfer.write() to discard. Need more
                # more stats to see if this is an issue.
                try:
                    s.send(stream[ix:ix+1024])
                except (KeyboardInterrupt, SystemExit):
                    print("Terminated @ send() via KeyboardInterrupt")
                    #s.close()
                    return
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
        self.streamer.daemon = True		# causes child process to terminate with its parent
        self.streamer.start()
        self.timer_ct = 0
        self.timer_skip_ct = 0
        self.timer_start = time.clock()
        self.f = open("temp.text", "w")

    def stop(self):
        self.streamer.join()

    def write(self, stream):
        self.capture_ct += 1
        self.f.write(u"%d\n" % (self.capture_ct))
        self.f.flush()
        if not self.streamer.is_alive():
            self.timer_skip_ct += 1
            print("NO Q -- DEAD")
            return
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



class PsuedoMqttHandler(SocketServer.BaseRequestHandler):
    def handle(self):
        # self.rfile is a file-like object created by the handler;
        # we can now use e.g. readline() instead of raw recv() calls
        action = self.rfile.readline().strip()
        topic = self.rfile.readline().strip()
        if action == 'publish':
            message = self.rfile.readline().strip()
            self.server.mqtt_messages[topic] = message
        elif action == 'read':
            if topic in self.server.mqtt_messages:
                self.wfile.write(self.server.mqtt_messages[topic])

def PsuedoMqttServer():
    config = ConfigParser.SafeConfigParser()
    config.readfp(open(config_file_path))
    broker_host = config.get("MqttBroker", "Host")
    broker_port = int(config.get("MqttBroker", "Port"))	# 1883

    # Create the server, binding to localhost on port 9999
    server = SocketServer.TCPServer((broker_host, broker_port), PsuedoMqttHandler)
    server.mqtt_messages = {}

    # Activate the server; this will keep running until you
    # interrupt the program with Ctrl-C
    server.serve_forever()

class PsuedoMqttClient(object):
    def __init__(self):
        # Create a socket (SOCK_STREAM means a TCP socket)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def disconnect(self):
        self.sock.close()

    def connect(self, host, port, timeout):
        self.sock.connect((host, port))

    def publish(self, topic, msg, qos=0):
        self.sock.sendall("publish\n%s\n%s\n" % (topic, msg))

    def read(self, topic, qos=0):
        self.sock.sendall("read\n%s\n" % (topic))
        received = self.sock.recv(1024)

class mqtt_node(object):
    def __init__(self, Subscriptions=[], Blocking=False, BlockingTimeoutSecs=1.0, Streamer=False, Verbose=True):
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
        self.streamer = None
        if Streamer:
            self.streamer = socket_xfer()
        if self.blocking_mode:
            print("Blocking Mode")
        else:
            print("Non-Blocking Mode")

    def Connect(self, timeout=0):
        self.mqttc = mqtt.Client()
        # Assign event callbacks
        self.mqttc.on_message = self.on_message
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_publish = self.on_publish
        self.mqttc.on_subscribe = self.on_subscribe
        # Connect
        connected = False
        connect_time = time.time()
        while not connected:
            try:
                self.mqttc.connect(self.broker_host, self.broker_port, self.broker_timeout)
                connected = True
            except socket.error:
                print ("vnavs_mqtt: unable to connect to broker")
                if (timeout > 0) and ((time.time() - connect_time) > timeout):
                    raise
                time.sleep(1)
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

    def Loop(self):
        try:
            while True:
                self.DoLoop()
                if self.CheckExceptions():
                    sys.exit(0)
        except KeyboardInterrupt:
            sys.exit(0)

    #
    # Long running processes should call this periodically.
    # It was a particular problem when when capturing a long
    # long sequence with the RPI camera and hte sender socket died.
    #
    def CheckExceptions(self):
        if stop_process:
            return True
        if self.streamer is not None:
            if not self.streamer.streamer.is_alive():
                # if the streamer has the focus when it dies or gets killed by ctrl-c,
                # the main program continues to run with no console. The shell seems
                # to be dead. The process has to be killed from another shell.
                # this avoids that, killing the parent if the child dies.
                return True
        return False

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
        if self.verbose:
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

#
# With TestSender and TestReceiver on the same RPI3 and the mosquitto broker
# on a second RPI3 connected via ethernet cable, the sender published
# about 1430 messages / second but the receiver only got about 315 / second.
# -- the reciver got all messages in order so it was constantly falling behind
# -- when the sender terminated, undelivered messages were discarded,
#	so the reciever never got the last messages. This may be fixable
#	by configuration, but doesn't matter because the readding is so slow.
#

class TestSender(mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=[], Blocking=False, Streamer=False, Verbose=Verbose)
        self.msgCt = 0
        self.startTime = time.time()

    def DoLoop(self):
        self.msgCt += 1
        self.mqttc.publish('test', self.msgCt)
        if (self.msgCt % 10) == 0:
            rate = self.msgCt / (time.time() - self.startTime)
            print("Published", self.msgCt, rate)

class TestReceiver(mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=['test'], Blocking=True, BlockingTimeoutSecs=0, Streamer=False, Verbose=Verbose)
        self.msgCt = 0
        self.startTime = time.time()

    def rmsg_test(self, msg):
        self.msgCt += 1
        if (self.msgCt % 10) == 0:
            rate = self.msgCt / (time.time() - self.startTime)
            print("Received", self.msgCt, msg, rate)

if __name__ == "__main__":
    #PiShutdown()
    if sys.argv[1] == 's':
        n = TestSender()
        n.Connect()
        n.Loop()
    elif sys.argv[1] == 'r':
        n = TestReceiver()
        n.Connect()
    elif sys.argv[1] == 'm':
        PsuedoMqttServer()
