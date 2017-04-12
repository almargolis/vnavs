from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import multiprocessing
import os
import Queue
import select
import socket
import SocketServer
import sys
import threading
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

class SelectServer(object):
    def __init__(self, IniSection=None, IsServer=True):
        self.config = ConfigParser.SafeConfigParser()
        self.config.readfp(open(config_file_path))
        self.broker_host = None
        self.broker_port = None
        if IniSection is not None:
            self.broker_host = self.config.get(IniSection, "Host")
            self.broker_port = int(self.config.get(IniSection, "Port"))	# 1883

        # This can be a server or client. Either way self.server is the primary socket
        self.isServer = IsServer
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setblocking(0)
        self.mqttPayloads = {}
        self.inputSockets = [ self.server ]
        self.outputSockets = [ ]
        self.outputQueues = {}
        self.fragments = {}

    def connect(self, host=None, port=None, keepalive=60, bind_address="", timeout=None):
        if host is not None:
            self.broker_host = host
        if port is not None:
            self.broker_port = port
        if self.isServer:
            self.server.bind((self.broker_host, self.broker_port))
            self.server.listen(5)
            if self.broker_host == '':
                displayHost = 'INADDR_ANY'
            else:
                displayHost = self.broker_host
            print("Server listening on host %s, port %s." % (displayHost, self.broker_port))
            print("Server listening on port %s." % (`self.server.getsockname()`))
        else:
            self.server.connect((self.broker_host, self.broker_port))

    def disconnect(self):
        self.sock.close()

    def CloseConnection(self, s):
        if s in self.outputSockets:
            self.outputSockets.remove(s)
        if s in self.inputSockets:
            self.inputSockets.remove(s)
        if s in self.outputQueues:
            del self.outputQueues[s]
        if s in self.fragments:
            del self.fragments[s]
        s.close()

    def ProcessData(self, s, data):
        if s in self.fragments:
            data = self.fragments[s] + data
            del self.fragments[s]
        messages = data.split('\x01')
        if data[-1] != '\x01':
            # the last message isn't complete, save the fragment
            fragment = messages.pop()
            self.fragments[s] = fragment
        for this_message in messages:
            parts = this_message.split('\x00')
            self.ProcessMessage(s, parts)
            print("recieve", parts)

    def loop_forever(self):
        while True:
            self.loop(timeout=None)

    def loop(self, timeout=1.0):
        # timeout=None blocks indefinately, timeout=0.0 polls and return immediately, potentially with three empty lists
        print('waiting for the next event')
        readable, writable, exceptional = select.select(self.inputSockets, self.outputSockets, self.inputSockets, timeout)
        for s in readable:
            if self.isServer and (s is self.server):
                # A "readable" server socket is ready to accept a connection
                connection, client_address = s.accept()
                print('new connection from', client_address)
                connection.setblocking(0)
                self.inputSockets.append(connection)
            else:
                try:
                    data = s.recv(1024)
                except socket.error as e:
                    if e.errno == 104:
                        # socket.error: [Errno 104] Connection reset by peer
                        data = None
                    else:
                        raise
                if data:
                    self.ProcessData(s, data)
                else:
                    # Interpret empty result as closed connection
                    self.CloseConnection(s)
        for s in writable:
            try:
                next_msg = self.outputQueues[s].get_nowait()
            except Queue.Empty:
                # No messages waiting so stop checking for writability.
                self.outputSockets.remove(s)
            else:
                try:
                    s.send(next_msg)
                except socket.error:
                    # socket.error: [Errno 104] Connection reset by peer (I ctrl-C client)
                    self.CloseConnection(s)
        for s in exceptional:
            self.CloseConnection(s)

#
# FastMqttServer is a simplified broker that is much faster thean mosquitto.
# It supports publish/subscribe with less chance of blockage due to increased
# speed. Use that when you need to see every message.
# It also supports a read mode, which allows you to get the latst message
# for a topic without, ignoring any previous messages. This is essentially
# a LIFO. Use this for topics which generate large volumes of messages
# that you can't process.
#
# There is only one queue per client, so be careful about subscribing to high
# volume topics for time sensitive processes.
#
class FastMqttServer(SelectServer):
    def __init__(self):
        super().__init__(IniSection="MqttFastServer")
        self.mqttPayloads = {}
        self.subscriptions = {}

    def ProcessMessage(self, s, message):
        if message[0] == '':
            return
        action = message[0]
        if action == 'publish':
            topic = message[1]
            payload = message[2]
            self.mqttPayloads[topic] = payload
            print("PUBLISH", topic, self.subscriptions)
            if topic in self.subscriptions:
                newSubscriptionList = []
                for sendSocket in self.subscriptions[topic]:
                    if sendSocket in self.inputSockets:
                        # we get here for subscription by still-connected sockets
                        newSubscriptionList.append(sendSocket)
                        print("SENDING", sendSocket.getsockname())
                        self.SendMessage(sendSocket, topic)
                self.subscriptions[topic] = newSubscriptionList		# scrubbed of closed connections
        elif action == 'subscribe':
            topic = message[1]
            if topic in self.subscriptions:
                if s not in self.subscriptions[topic]:
                    self.subscriptions[topic].append(s)
            else:
                self.subscriptions[topic] = [s]
        elif action == 'read':
            topic = message[1]
            self.SendMessage(s, topic)

    def SendMessage(self, s, topic):
        if not s in self.outputQueues:
            self.outputQueues[s] = Queue.Queue()
        if topic in self.mqttPayloads:
            payload = self.mqttPayloads[topic]
        else:
            payload = ''
        message = "message\x00%s\x00%s\x01" % (topic, payload)
        self.outputQueues[s].put(message)
        if s not in self.outputSockets:
            self.outputSockets.append(s)

class FastMqttClient(SelectServer):
    def __init__(self):
        super().__init__(IniSection="MqttBroker", IsServer=False)
        self.thread = None
        self.on_message = None
        self.on_connect = None

    def connect(self, **kwargs):
        super().connect(**kwargs)
        if self.on_connect is not None:
            client = None			# not implemented
            userdata = None			# not implemented
            flags = None			# not implemented
            rc = 0				# not implemented
            self.on_connect(client, userdata, flags, rc)

    def publish(self, topic, msg, qos=0):
        msg_sent = False
        retry_ct = 0
        while (not msg_sent) and (retry_ct < 10):
            try:
                self.server.sendall("publish\x00%s\x00%s\x01" % (topic, msg))
                msg_sent = True
            except socket.error:
                # socket.error: [Errno 11] Resource temporarily unavailable
                # need to check Errno - kep running even when server died
                retry_ct += 1
        return msg_sent

    def read(self, topic, qos=0):
        self.server.sendall("read\n%s\n" % (topic))
        received = self.sock.recv(1024)

    def subscribe(self, topic, qos):
        self.server.sendall("subscribe\x00%s\x01" % (topic))

    def loop_start(self):
        self.thread = threading.Thread(target=self.loop)
        self.thread.start()

    def loop_stop(self):
        if self.thread is not None:
            self.thread.stop()
            self.thread = None

    def ProcessMessage(self, s, message):
        if message[0] == '':
            return
        if message[0] == 'message':
            topic = message[1]
            payload = message[2]
            if self.on_message is not None:
                mqtt_message = FastMqttMessage(topic, payload)
                client = None			# not implemented
                userdata = None			# not implemented
                self.on_message(client, userdata, mqtt_message)

class FastMqttMessage(object):
    def __init__(self, topic, payload, qos=0):
        self.topic = topic
        self.payload = payload
        self.qos = 0

class mqtt_node(object):
    def __init__(self, Subscriptions=[], Blocking=False, BlockingTimeoutSecs=1.0, BrokerType='M', Streamer=False, Verbose=True):
        self.config = ConfigParser.SafeConfigParser()
        self.config.readfp(open(config_file_path))
        self.blocking_mode = Blocking
        self.blocking_timeout = BlockingTimeoutSecs
        self.subscriptions = Subscriptions
        self.handlers = {}
        self.broker_type = BrokerType
        if self.broker_type == 'M':
            iniSection = 'MqttBroker'		# Mosquitto
        else:
            iniSection = 'MqttFast'
        self.broker_host = self.config.get(iniSection, "Host")
        self.broker_port = int(self.config.get(iniSection, "Port"))	# 1883
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
        if self.broker_type == "M":
            self.mqttc = mqtt.Client()
        else:
            self.mqttc = FastMqttClient()
        # Assign event callbacks
        self.mqttc.on_message = self.on_message
        self.mqttc.on_connect = self.on_connect
        # Connect
        connected = False
        connect_time = time.time()
        while not connected:
            try:
                self.mqttc.connect(host=self.broker_host, port=self.broker_port, timeout=self.broker_timeout)
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
        super().__init__(Subscriptions=[], Blocking=False, BrokerType='F', Streamer=False, Verbose=Verbose)
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
        super().__init__(Subscriptions=['test'], Blocking=True, BlockingTimeoutSecs=0, BrokerType='F', Streamer=False, Verbose=Verbose)
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
        s = FastMqttServer()
        s.connect()
        s.loop_forever()
