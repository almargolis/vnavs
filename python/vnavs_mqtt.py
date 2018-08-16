from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import datetime
import json
import multiprocessing
import numpy as np
import os
import select
import socket
import sys
import threading
import traceback
import time

import paho.mqtt.client as mqtt

import vnavs_const as vconst
import vnavs_comms as vcomms

if sys.version_info[0] < 3:
    import ConfigParser
    import Queue
else:
    import configparser as ConfigParser
    import queue as Queue

config_file_path = os.path.expanduser("~/vnavs.ini")

ARG_HOST = 'host'
ARG_PORT = 'port'
ARG_LOCAL = 'local'
ARG_IMAGE_DIR = 'imagedir'
ARG_IMAGE_GET = 'imageget'
ARG_TRUE = 'true'
ARG_FALSE = 'false'
ARG_CWD = 'cwd'

stop_process = False

def NowStr():
     return datetime.datetime.now().strftime('%Y%m%d%H%M%S')

FILE_TRANSFER_IDLE = 0
FILE_TRANSFER_STARTED = 1
FILE_TRANSFER_COMPLETE = 2

class FileClient(vcomms.SocketWrapperClient):
    def __init__(self, BufferLen=vcomms.TCPIP_XFR_BUFLEN,  Verbose=False):
        super().__init__(BufferLen=BufferLen, IniSection="FileClient", IsZeroOneProtocol=False, Verbose=Verbose)
        self.Init()

    def Init(self):
        self.file_name = None
        self.file_out = None
        self.buffer = ""
        self.transfer_state = FILE_TRANSFER_IDLE
        self.start_time = 0
        self.timeout = False

    def GetFile(self, dir_code, filename, path=None):
        self.StartTransfer(dir_code=dir_code, filename=filename, path=path)
        while True:
            if self.CheckTransfer():
                return True
            if self.timeout:
                return False

    def StartTransfer(self, dir_code, filename, path=None):
        self.Init()
        retry_ct = 0
        while (not self.connected) and (retry_ct < 5):
            retry_ct += 1
            # There is an issue here that effects all connects.
            # Possibly just OSX connecting to RPI, but not sure.
            # First connect fails -- or seems to
            # If you try to reconnect immediately, you get a fail
            #    socket.error: [Errno 37] Operation already in progress
            # So some patience is needed. Somewhere there is some latency or
            # inconsistency of block / no block. Or one of the OSes trying to be polite.
            time.sleep(1)
            print("FileClient.StartTransfer() - Attempt Connect", self.socket_host, self.socket_port)
            self.Connect()
        #print("FileClient.StartTransfer() - CONNECTED", self.socket_host, self.socket_port)
        self.file_name = filename
        if path is None:
            self.file_path = filename
        else:
            self.file_path = path
        self.file_out = open(self.file_path, "wb")
        self.transfer_state = FILE_TRANSFER_STARTED
        self.timeout = False
        self.buffer = bytearray()
        self.buf_sum = 0
        self.QueueMessageZ([dir_code, filename])
        self.start_time = time.time()
        self.Select(timeout=0.1)

    def CheckTransfer(self, timeout=30.0):
        if self.transfer_state == FILE_TRANSFER_STARTED:
            self.Select(timeout=0.1)
        """
        if (self.transfer_state == FILE_TRANSFER_STARTED) and ((time.time() - self.start_time) < timeout):
            self.file_out.close()
            self.transfer_state = FILE_TRANSFER_COMPLETE
            print("FileClient.CheckTransfer() Timeout", self.file_name)
            self.timeout = True					# stays true until next transfer started
        """
        if self.transfer_state == FILE_TRANSFER_COMPLETE:
            self.transfer_state = FILE_TRANSFER_IDLE
            return True
        return False

    def RecvData(self, s, data):
        self.buffer += data
        self.buf_sum += len(data)
        p = self.buffer.find('\x00')
        #print("RCV DATA", len(data), len(self.buffer), self.buf_sum)
        if p > 0:
            try:
                file_len = int(self.buffer[:p])
            except:
                # need to do something specific here to restart / recover transfer
                # or neatly notify as not complete.
                # got an "invalid literal" exception. maybe due to noisy network.
                #raise
                # maybe we don't have enough data to figure out
                print("EX", p, len(data))
                return
            #print("FILE LEN", file_len)
            buf_len = p + file_len + 1
            if len(self.buffer) == buf_len:
                self.file_out.write(self.buffer[p+1:])
                self.file_out.close()
                self.transfer_state = FILE_TRANSFER_COMPLETE
                #print("FileClient.RecvData() Transfer Complete", time.time() - self.start_time, self.file_name, file_len)

class FastMqttClient(vcomms.SocketWrapperClient):
    # Many of these function names are lower case to be consistent with paho.mqtt.client.
    def __init__(self, Verbose=False):
        super().__init__(IniSection="MqttFast", Verbose=Verbose)
        self.on_message = None
        self.on_connect = None

    def connect(self, **kwargs):
        # Hmmm ... maybe dangerous. Clients have both connect() and Connect()
        # doing slightly different things.
        super().Connect(**kwargs)
        if self.on_connect is not None:
            client = None			# not implemented
            userdata = None			# not implemented
            flags = None			# not implemented
            rc = 0				# not implemented
            self.on_connect(client, userdata, flags, rc)

    def BlockingWriteSocket(self, msg):
        msg_sent = super().BlockingWriteSocket(msg)
        if msg_sent:
            mid = 0				# not implemented -- message id
            return (mqtt.MQTT_ERR_SUCCESS, mid)
        else:
            mid = 0				# not sue if this matches Paho MQTT behavior
            return (mqtt.MQTT_ERR_NO_CONN, mid)

    def loop(self, timeout=1.0):
        self.Select(timeout=timeout)

    def loop_forever(self):
        self.SelectForever()

    def loop_start(self):
        self.SelectThreadStart()

    def loop_stop(self, force=False):
        # unused force parameter exists for mosquitto compatibility
        self.SelectThreadStop()

    def publish(self, topic, msg, qos=0):
        self.QueueMessageZ(['publish', topic, msg])
        mid = 0					# not implemented -- message id
        return (mqtt.MQTT_ERR_SUCCESS, mid)

    def read(self, topic, qos=0):
        # This is a non-repeating request to get the latest message
        self.QueueMessageZ(['read', topic])
        mid = 0					# not implemented -- message id
        return (mqtt.MQTT_ERR_SUCCESS, mid)

    def subscribe(self, topic, qos, timeout=1.0, mode=vcomms.SUBSCRIPTION_MODE_ALL):
        packet_sent = False
        start_time = time.time()
        while not packet_sent:
            try:
                print("SUBSCRIBE", topic)
                self.QueueMessageZ(['subscribe', topic, mode])
                packet_sent = True
            except socket.error as e:
                # socket.error: [Errno 11] Resource temporarily unavailable
                if e.errno == 11:
                    return
                if (e.errno == 11) and ((time.time() - start_time) < timeout):
                    continue
                raise

    def ProcessMessage(self, s, message):
        if message[0] == '':
            return
        if message[0] == 'message':
            topic = message[1]
            mid = message[2]
            payload = message[3]
            if self.on_message is not None:
                mqtt_message = FastMqttMessage(topic, payload, mid=mid)
                client = None			# not implemented
                userdata = None			# not implemented
                self.on_message(client, userdata, mqtt_message)

class PahoClient(mqtt.Client):
    # This should be a very thin wrapper.
    # FastMqttClient() should have as close to identical API as Paho client.
    # This object reconciles any unavoidable differences so mqtt_node works
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

    def subscribe(self, topic, qos, timeout=1.0, mode=vcomms.SUBSCRIPTION_MODE_ALL):
        super().subscribe(topic, qos)

class FastMqttMessage(object):
    def __init__(self, topic, payload, qos=0, mid=0):
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.mid = mid				# this is a fast mqtt extension

class Counters(object):
    def __init__(self):
        self.start_time = time.time()
        self.counters = {}
        self.ctCt = 0
        self.lastPrintCtCt = -1

    def Count(self, name, ct=1):
        self.ctCt += 1
        if name in self.counters:
            new_ct = self.counters[name] + ct
        else:
            new_ct = ct
        self.counters[name] = new_ct

    def Print(self, msgid, names=None, freq=100):
        if (self.ctCt % freq) != 0:
            return
        if self.lastPrintCtCt == self.ctCt:
            return
        self.lastPrintCtCt = self.ctCt
        elapsedTime = time.time() - self.start_time
        if names is None:
            names = self.counters.keys()
        outFmt = [msgid]
        outVal = []
        for this in names:
            outFmt.append(this + ':')
            outFmt.append('{}')
            outFmt.append('({} /sec)')
            outVal.append(self.counters[this])
            outVal.append(self.counters[this] / elapsedTime)
        fmt = ' '.join(outFmt)
        print(fmt.format(*outVal))

#
# Blocking == True
#	Single threaded node.
#       if BlockingTimeoutSecs is None,
#		mqtt loop_forever() is run and after Connect() all processing is done via
#		callbacks.
#       if BlockingTimeoutSecs is not None.
#		messages are not automatically processed, call CheckMqtt() periodically
#		to process messages.
#               A convenient way to do this is is to call Loop() and implement a DoLoop()
#               method. This has the advantage of working identically for blocking and
#               non-blocking modes so the node blocking mode can be changed easily.
#               Loop() handles most exception processing. DoLoop() is called repetitively
#               and frequently, so it does not need to implement the overall looping
#		or routine exceptions.
# Blocking == False
#	Threaded node. Mqttc runs in its own thread and communicates with the main
#		node thread via callbacks. Since that is happening asyncronously,
#		you must be thoughtful regarding race conditions.
#	It is recommended to use the Loop() / DoLoop() mechanism to make sure
#		connections and exceptions are handled properly. Since Loop()
#		is non-blocking, DoLoop() needs to check self.mqttcConnected.
#
# (The following is a draft. May not be quite correct)
# Where do I put my code for a node?
#
# rmsg* handlers (callbacks) get called as messages arrive and run in the socket thread.
# It is possible for all code to live in these handlers. This makes for easy coding,
# but can lead to poor performance if the handlers take a long time to complete,
# either due to CPU intensive operations or waiting for external events (like database selects).
#
def LaunchNode(node_class):
    n = node_class()
    n.Loop()

def Publish(topic, payload, ResponseTopic=None):
    if ResponseTopic is None:
        subscriptions = []
        conf = None
        save_payload = False
    else:
        subscriptions = [Subscription(ResponseTopic)]
        conf = 'Publish' + NowStr()
        save_payload = True
    node = mqtt_node(Subscriptions=subscriptions, BrokerType='F', SingleThreaded=True,
			AckTopic=ResponseTopic)
    print("BrokerType", node.broker_type)
    try:
        node.ConnectToMqttServer()
    except:
        pass
    while not node.mqttc.connected:
        try:
            node.ConnectToMqttServer()
        except:
            pass
    node.Publish(topic, payload, ConfRequest=conf)
    while node.mqttc.sent_ct < 1:
        node.CheckMqttPendingActivity()
    if ResponseTopic is None:
        return None
    return node.WaitForPayload(conf)

class Subscription(object):
    __slots__ = ('async_delivery', 'handler_method', 'handler_needs_topic', 'last_payload', 'queue', 'request_only', 'topic')

    def __init__(self, topic, handler=None, handler_needs_topic=False, request_only=False, async_delivery=False, LatestOnly=True):
        self.async_delivery = async_delivery                  # process asyncronously
        self.topic = topic
        self.request_only = request_only
        self.handler_method = handler
        self.handler_needs_topic = handler_needs_topic
        self.last_payload = None
        if LatestOnly:
            self.queue = None
        else:
            self.queue = Queue.Queue()

class ConfirmationRequest(object):
    __slots__ = ('checked_time', 'conf_id', 'confirmed_time', 'payload', 'request_time')

    def __init__(self, conf_id):
        self.checked_time = None
        self.conf_id = conf_id
        self.confirmed_time = None
        self.payload = None
        self.request_time = time.time()

    def __repr__(self):
        conf = "not confirmed"
        if self.confirmed_time is not None:
            conf = "confirmed"
        chk = "not checked"
        if self.checked_time is not None:
            chk = "checked"
        return "( CONF {} - {} - {} )".format(self.conf_id, conf, chk)

def JsonShowTypes(payload):
    for key, value in payload.items():
        print(key, value.__class__.__name__, value)

class JsonNumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.int64):
            obj_out = int(obj)
            #print("JsonNumpyEncoder()", obj.__class__.__name__, obj_out.__class__.__name__)
            return obj_out
        return super().default(obj)

class mqtt_node(object):
    __slots__ = ('args', 'automatically_connect', 'block_if_not_connected', 'broker_timeout', 'broker_type',
					'config', 'confirmation_pending', 'debug', 'exception_ct', 'exception_last_time',
					'imageDir', 'lastSocketError', 'loop_sleep',
					'mqttc', 'node_name',
					'select_timeout', 'single_threaded', 'socket_host', 'socket_port', 'stats', 'streamer', 'subscriptions',
					'verbose', 'vnavs_mid', 'vnavs_pid', 'wildcard_handler')

    def __init__(self, node_name=None, Subscriptions=[], AckTopic=None,
				LoopSleep=0.01,
				AutomaticallyConnect=True, BlockIfNotConnected=True, SingleThreaded=False, SelectTimeoutSecs=1.0,
				BrokerType='F', Streamer=False, Verbose=True):
        # AutomaticallyConnect is for nodes that don't want automatic connection managment. Such as darkroom which may run stand-alone or
        #	switch between cameras / bots manually.
        # BlockIfNotConnected is for nodes that only need to run when connected to a message server. DoLoop() is what is blocked.
        #	If set to false, the node needs code to avoid crashing when calling communications activities.
        self.args = {}
        for this in sys.argv[1:]:
            eq_pos = this.find('=')
            if eq_pos >= 0:
                key = this[:eq_pos]
                val = this[eq_pos+1:]
                if (key == ARG_HOST) and (val == ARG_LOCAL):
                    val = HOST_LOCAL
                elif (key == ARG_IMAGE_DIR) and (val == ARG_CWD):
                    val = os.getcwd()
                elif (key == ARG_IMAGE_GET) and (val == ARG_FALSE):
                    val = False
                elif (key == ARG_IMAGE_GET) and (val == ARG_TRUE):
                    val = True
                self.args[key] = val
            else:
                self.args[this] = True
        self.confirmation_pending = {}
        self.vnavs_pid = int(time.time())		# non-repeating with ~ 1 second
        self.vnavs_mid = 0				# Publish() sequence
        self.block_if_not_connected = BlockIfNotConnected
        self.config = ConfigParser.SafeConfigParser()
        self.config.readfp(open(config_file_path))
        self.automatically_connect = AutomaticallyConnect
        if ARG_IMAGE_DIR in self.args:
            self.imageDir = self.args[ARG_IMAGE_DIR]
        else:
            self.imageDir = self.config.get("Cameraman", "ImageDir")
        self.imageDir = os.path.expanduser(self.imageDir)		# this expands tilde in path
        self.single_threaded = SingleThreaded
        self.select_timeout = SelectTimeoutSecs
        self.subscriptions = {}
        for this in Subscriptions:
            self.subscriptions[this.topic] = this
        self.wildcard_handler = None
        self.broker_type = BrokerType
        self.InitMqttClient()
        self.broker_timeout = 60
        self.debug = 0
        self.exception_last_time = 0
        self.exception_ct = 0
        self.loop_sleep = LoopSleep
        self.lastSocketError = None
        if node_name is None:
            self.node_name = self.__class__.__name__
        else:
            self.node_name = node_name
        self.stats = Counters()
        self.verbose = Verbose
        self.streamer = None
        if Streamer:
            self.streamer = socket_xfer()
        if self.single_threaded:
            print("Blocking Mode")
        else:
            print("Non-Blocking Mode")

    def InitMqttClient(self):
        print("InitMqttClient()", self.broker_type)
        if self.broker_type == 'M':
            iniSection = 'MqttBroker'		# Mosquitto
            self.mqttc = PahoClient()
        else:
            iniSection = 'MqttFast'
            self.mqttc = FastMqttClient()
        # Assign event callbacks
        self.mqttc.on_message = self.on_message
        self.mqttc.on_connect = self.on_connect
        if ARG_HOST in self.args:
            self.socket_host = self.args[ARG_HOST]
        else:
            self.socket_host = self.config.get(iniSection, "Host")
        self.socket_port = int(self.config.get(iniSection, "Port"))

    def ConnectToMqttServer(self):
        if self.mqttc.connected:
            return
        while True:
            if self.block_if_not_connected:
                timeout = None
            else:
                timeout = 0.01
            self.mqttc.connect(host=self.socket_host, port=self.socket_port, timeout=timeout)
            if self.mqttc.connected:
                print("mqtt_node() connected")
                break
            else:
                print("mqtt_node() NOT connected")
                return False
        if self.single_threaded:
            if self.select_timeout is None:
                self.mqttc.loop_forever()
                return True
            else:
                # client must periodically either call call Loop() or periodically call mqtt loop()
                return True
        else:
            # this starts a separate thread which is handy, but tkinter and others don't support threads
            self.mqttc.loop_start()
            return True

    def CheckMqttPendingActivity(self):
         # Blocking mode nodes with BlockingTimeoutSecs not None need
         # to call this periodically or messages will never be seen.
         # Depending on how you think about it, calling these blocking
         # may seem like an oxymoron.
         #
         try:
             self.mqttc.loop(timeout=self.select_timeout)
         except socket.error:
            # THIS IS WRONG
            # connected will be handled by mqttc client object.
            # I need to figure out who to save data for logging and
            # reconnect to server when possible.
            # Maybe do an E-Stop sort of thing.i
            # Helmsman stiops on e-stop. Other may change mode, signal operator, whtever
            self.mqttc.connected = False

    def Disconnect(self):
        if not self.single_threaded:
            self.mqttc.loop_stop(force=False)
        self.mqttc.disconnect()

    def Loop(self):
        while True:
            try:
                if self.automatically_connect and (not self.mqttc.connected):
                    # This could be a reconnection. Maybe we want more logging, etc.
                    # Exceptions with socket.error is how we detect a disconnect.
                    self.ConnectToMqttServer()
                    print("Loop() Juat attemoted to connect")
                if self.mqttc.connected:
                    if self.mqttc.thread is not None:
                        if not self.mqttc.thread.is_alive():
                            # The thread has died. Probably due to an untrapped exception.
                            # This should be logged and we should probably try to save
                            # state information like queued messages and message counts
                            # for the new connection. FUTURE WORK.
                            # This has been tested as working in the event that a
                            # thread dies in an unexpected way. I'm now going
                            # to add exsception logic to the thread so this never
                            # gets here again.
                            print("THREAD DEAD")
                            self.InitMqttClient()
                            self.ConnectToMqttServer()
                if self.mqttc.connected:
                    if self.single_threaded:
                        self.CheckMqttPendingActivity()
                    self.DoLoop()
                elif not self.block_if_not_connected:
                    self.DoLoop()
                if self.CheckExceptions():
                    sys.exit(0)
                if self.loop_sleep > 0:
                    # This is essentially a yield to the other thread. Without this, the communications
                    # thread can be blocked. Navigator was experiencing MANY MINUTES of message delivery
                    # delay without this. Nodes with lots of i/o in the main thread may not need this
                    # sleep. Cameraman does fine without it.
                    time.sleep(self.loop_sleep)
            except KeyboardInterrupt:
                self.CleanupLoop()
                sys.exit(0)
            except:
                exception_time = time.clock()
                payload = {}
                payload['node_class'] = self.__class__.__name__
                payload['node_module'] = self.__module__
                payload['traceback'] = traceback.format_exc()
                print(payload['traceback'])				# display in case we are running in console
                self.Publish(vconst.system_abend_topic, payload)
                self.CleanupLoop()
                if (exception_time - self.exception_last_time) < 60:
                    if self.exception_ct > 10:
                        sys.exit(0)
                    self.exception_ct += 1
                else:
                    self.exception_ct = 0
                self.exception_last_time = exception_time

    def CleanupLoop(self):
        pass					# override in client if cleanup needed

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
        max_chars = 25
        s = str(msg)
        if len(s) <= max_chars:
            return s
        return s[:max_chars] + ' [...]'

    def GetLatestPayload(self, topic):
        # This methodology risks loosing a latest message that arrives between the line
        # where the payload is copied and the line where the subscription object payload is cleared.
        # This should be extremely rare and is not completely inconsistent with the expectation that
        # latest method subscriptions may not process all messages.
        # As currenty written, using a single swap statement, this should be completely thread safe.
        #
        if topic not in self.subscriptions:
            raise Exception("GetLatestPayload() unknown topic '{}'".format(topic))
        subscription = self.subscriptions[topic]
        if subscription.last_payload is None:
            return None					# avoids tiny chance of clearing payload that arrives mid-method
        payload, subscription.last_payload = subscription.last_payload, None
        return payload

    def HandleAllSynchronousPayloads(self):
        for this in self.subscriptions.values():
            if this.handler_method is None:
                continue
            if this.async_delivery:
                # messages was handled as soon as it arrived
                continue
            payload = self.GetLatestPayload(this.topic)
            if payload is not None:
                if this.handler_needs_topic:
                    this.handler_method(this.topic, payload)
                else:
                    this.handler_method(payload)

    def Publish(self, topic, payload, ConfRequest=None):
        # payload is a dict to be converted to JSON)
        # ConfRequest is an ID asking the recipient to clearly identify
        # the response to this request. This requires cooperative
        # requestors and respondors.
        if not self.mqttc.connected:
            print("Publish() Not connected, not sent")
            # for now, silently ignore publish errors. Need to do better
            return
        payload['_topic'] = topic
        payload['_sender'] = self.node_name
        payload['_sendTime'] = time.time()
        payload['_sendPid'] = self.vnavs_pid
        self.vnavs_mid += 1
        payload['_sendSeq'] = self.vnavs_mid
        if ConfRequest is not None:
            payload['_confRequest'] = ConfRequest
            self.confirmation_pending[ConfRequest] = ConfirmationRequest(ConfRequest)
            print("Publish() has confirmation request", payload)
        #JsonShowTypes(payload)
        j = json.dumps(payload, cls=JsonNumpyEncoder)
        #print("Publish() JSON", j)
        res, mid = self.mqttc.publish(topic, j)
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def PrepareResponse(self, payload, ConfResponse=False):
        # Prepares payload to be used as a response.
        # Copy identifier fields so recipients can match source message
        # so it knows request is completed and where to continue its process.
        # Info about original message is always there thanks to Publish()
        new_payload = {}
        if '_topic' in payload:
            new_payload['_ackTopic'] = payload['_topic']
        if '_sendPid' in payload:
            new_payload['_ackPid'] = payload['_sendPid']
        if '_sendSeq' in payload:
            new_payload['_ackSeq'] = payload['_sendSeq']
        if ConfResponse:
            if '_confRequest' in payload:
                new_payload['_isConfirmation'] = payload['_confRequest']
        return new_payload

    def GetConfRequest(self, payload):
        return payload.get('_confRequest', None)

    def CheckConfirmation(self, conf):
        res = False
        if conf in self.confirmation_pending:
            c = self.confirmation_pending[conf]
            if c.payload is not None:
                res = True
                if c.checked_time is None:
                    c.checked_time = time.time
        self.ScrubConfirmations()
        if res:
            return c.payload
        else:
            return None

    def ScrubConfirmations(self):
        # This should delete checked confirmations after a little while
        #print("ScrubConfirmation()", self.confirmation_pending)
        return

    def WaitForPayload(self, conf):
        # This was created for limited use where convenience matters more than the ability
        # to handle exception cases.
        while True:
            if not (conf in self.confirmation_pending):
                return None					# maybe should be exception
            payload = self.CheckConfirmation('conf')
            if payload is not None:
                return payload
            self.CheckMqttPendingActivity()

    def on_connect(self, client, userdata, flags, rc):
        print("on_connect() rc: " + str(rc))
        for this_subscription in self.subscriptions.values():
            if not this_subscription.request_only:
                if this_subscription.queue is None:
                    mode = vcomms.SUBSCRIPTION_MODE_LATEST
                else:
                    mode = vcomms.SUBSCRIPTION_MODE_ALL
                self.mqttc.subscribe(this_subscription.topic, 0, mode=mode)

    def on_message(self, client, userdata, message):
        if self.verbose:
            print("on_message()", message.topic + " " + str(message.qos) + " " + self.MessageStr(message.payload))
        msg = message.payload.decode("utf-8")
        if msg == '':
            payload = {}
        else:
            try:
                payload = json.loads(msg)
            except ValueError:
                payload = {}
                print("JSON Error", message.payload)
        subscription = self.subscriptions[message.topic]
        if '_sendTime' in payload:
            send_time = float(payload['_sendTime'])
            send_diff = time.time() - send_time
            if send_diff > 5:
                print("Node stale message {} - {} = {} {}".format(time.time(), send_time, send_diff, message.topic))
                #raise Exception("node message stale")
        #
        if '_isConfirmation' in payload:
            print("on_message() Message received with confirmation:", payload)
            conf_id = payload['_isConfirmation']
            # it may be that some other node wants the confirmation
            if conf_id in self.confirmation_pending:
                # it should only be confirmed once, but we don't check for duplicates
                c = self.confirmation_pending[conf_id]
                c.confirmed_time = time.time
                c.payload = payload
        if subscription.async_delivery:
            # Handle immediately. Most commonly in multi-thread mode, so handler_method
            # needs to be thread safe and typically small/fast.
            if subscription.handler_needs_topic:
                subscription.handler_method(subscription.topic, payload)
            else:
                subscription.handler_method(payload)
        else:
            subscription.last_payload = payload

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

class FastMqttUtil(mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=[], Blocking=True, BlockingTimeoutSecs=0, BrokerType='F', Streamer=False, Verbose=Verbose)

if __name__ == "__main__":
    if 'verbose' in sys.argv:
        print("VERBOSE")
        verbose = True
    else:
        print("QUIET")
        verbose = False
    if sys.argv[1] == 's':
        n = TestSender()
        n.Connect()
        n.Loop()
    elif sys.argv[1] == 'r':
        n = TestReceiver()
        n.Connect()
    elif sys.argv[1] == 'fpub':
        s = FastMqttUtil()
        s.Connect()
        time.sleep(1)
        s.mqttc.publish(sys.argv[2], sys.argv[3])
        time.sleep(1)
