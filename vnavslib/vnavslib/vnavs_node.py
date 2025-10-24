import configparser
import json
import socket
import sys
import time
import traceback

import paho.mqtt.client as mqtt


from vnavslib import vnavs_comms as vcomms
from vnavslib import vnavs_const as vconst
from vnavslib import vnavs_mqtt_clients as vmqtt

stop_process = False

ARG_HOST = "host"
ARG_PORT = "port"
ARG_LOCAL = "local"
ARG_TRUE = "true"
ARG_FALSE = "false"
ARG_CWD = "cwd"


def NowStr():
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S")


class Subscription:
    __slots__ = (
        "async_delivery",
        "handler_method",
        "handler_needs_topic",
        "last_payload",
        "message_queue",
        "request_only",
        "topic",
    )

    def __init__(
        self,
        topic,
        handler=None,
        handler_needs_topic=False,
        request_only=False,
        async_delivery=False,
        LatestOnly=True,
    ):
        self.async_delivery = async_delivery  # process asyncronously
        self.topic = topic
        self.request_only = request_only
        self.handler_method = handler
        self.handler_needs_topic = handler_needs_topic
        self.last_payload = None
        if LatestOnly:
            self.message_queue = None
        else:
            self.message_queue = queue.Queue()


class ConfirmationRequest:
    __slots__ = ("checked_time", "conf_id", "confirmed_time", "payload", "request_time")

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


class Counters:
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
            outFmt.append(this + ":")
            outFmt.append("{}")
            outFmt.append("({} /sec)")
            outVal.append(self.counters[this])
            outVal.append(self.counters[this] / elapsedTime)
        fmt = " ".join(outFmt)
        print(fmt.format(*outVal))


#
# VnavsNode() encapsolates practices that VNAVS nodes are expected
#               to follow. This allows simple nodes to have
#               relatively code, most of which are specific to
#               the node's purpose, not communications.
#
# automatically_connect=False is for nodes that don't want automatic connection managment.
#       One eample is darkroom which may run stand-alone or as a nhode communivating with bots.
# wait_if_not_connected=True is for nodes that have nothing to do if no message server
#       is available. do_loop() is blocked.
# 	    If set to False, the node can continue critical functions like managing actuators,
#       sensors or GUI but it need code to check the connection status in order to
#       avoid crashing when calling communications activities.
# single_threaded=False is the default configuration. This starts a separate thread for
#       for communications processing so the node can do it's functional work without
#       monitoring communications activity. The node can publish() whenever it needs and
#       receives messages asynchronously via handlers defined with the subscription.
# select_timeout mainly applies to single_threaded=True mode. Use None for a node
#       that has nothing else to do but receive messages and does all its work in
#       the subscriptions handlers. This might be the case for a message logger.
#       If a selet_timeout period is specified, the node must periodically
#       exercise messaging by either calling loop() or or mqttc.loop().
#       ** This needs clarification **
# mqttc is a handler for either true mqqt or vnavs fast mqqt
#


class VnavsNode:
    __slots__ = (
        "args",
        "automatically_connect",
        "automatically_handle_synchronous_messages",
        "wait_if_not_connected",
        "broker_timeout",
        "broker_type",
        "config",
        "confirmation_pending",
        "debug",
        "exception_ct",
        "exception_last_time",
        "has_synchronous_message_subscriptions",
        "lastSocketError",
        "loop_sleep",
        "mqttc",
        "node_name",
        "select_timeout",
        "single_threaded",
        "socket_host",
        "socket_port",
        "stats",
        "streamer",
        "subscriptions",
        "verbose",
        "vnavs_mid",
        "vnavs_pid",
        "wildcard_handler",
    )

    def __init__(
        self,
        node_name=None,
        subscriptions=[],
        ack_topic=None,
        loop_sleep=0.001,
        automatically_connect=True,
        automatically_handle_synchronous_messages=True,
        wait_if_not_connected=True,
        single_threaded=False,
        select_timeout_secs=1.0,
        broker_type="F",
        host=None,
        port=vconst.FAST_MQTT_PORT,
        streamer=False,
        verbose=True,
    ):
        self.args = {}
        for this in sys.argv[1:]:
            eq_pos = this.find("=")
            if eq_pos >= 0:
                key = this[:eq_pos]
                val = this[eq_pos + 1 :]
                if (key == ARG_HOST) and (val == ARG_LOCAL):
                    val = HOST_LOCAL
                self.args[key] = val
            else:
                self.args[this] = True
        # __init__ parameters take priority over command line
        if host is not None:
            self.args[ARG_HOST] = host
        if port is not None:
            self.args[ARG_PORT] = port
        #
        self.confirmation_pending = {}
        self.vnavs_pid = int(time.time())  # non-repeating with ~ 1 second
        self.vnavs_mid = 0  # publish() sequence
        self.wait_if_not_connected = wait_if_not_connected
        self.config = configparser.ConfigParser()
        self.config.read_file(open(vconst.config_file_path))
        self.automatically_connect = automatically_connect
        self.automatically_handle_synchronous_messages = (
            automatically_handle_synchronous_messages
        )
        self.single_threaded = single_threaded
        self.select_timeout = select_timeout_secs
        self.has_synchronous_message_subscriptions = False
        self.subscriptions = {}
        for this in subscriptions:
            if not this.async_delivery:
                self.has_synchronous_message_subscriptions = True
            self.subscriptions[this.topic] = this
        self.wildcard_handler = None
        self.broker_type = broker_type
        self.verbose = verbose  # needed by init_mqtt_client()
        self.socket_host = None  # needed by init_mqtt_client()
        self.socket_port = None  # needed by init_mqtt_client()
        self.init_mqtt_client()
        self.broker_timeout = 60
        self.debug = 0
        self.exception_last_time = 0
        self.exception_ct = 0
        self.loop_sleep = loop_sleep
        self.lastSocketError = None
        if node_name is None:
            self.node_name = self.__class__.__name__
        else:
            self.node_name = node_name
        self.stats = Counters()
        self.streamer = None
        if streamer:
            self.streamer = socket_xfer()
        if self.verbose:
            if self.single_threaded:
                print("Single Threaded")
            else:
                print("Not Single Threaded")

    def init_mqtt_client(self):
        if self.broker_type == "M":
            ini_section = "MqttBroker"  # Mosquitto
            self.mqttc = vmqtt.PahoClient()
        else:
            ini_section = "MqttFast"
            self.mqttc = vmqtt.FastMqttClient()
        # Assign event callbacks
        self.mqttc.on_message = self.on_message
        self.mqttc.on_connect = self.on_connect
        if ARG_HOST in self.args:
            self.socket_host = self.args[ARG_HOST]
        else:
            self.socket_host = self.config.get(ini_section, "Host")
        if ARG_PORT in self.args:
            self.socket_port = int(self.args[ARG_PORT])
        else:
            self.socket_port = int(self.config.get(ini_section, "Port"))
        if self.verbose:
            print(
                "init_mqtt_client()",
                self.broker_type,
                "@",
                self.socket_host,
                ":",
                self.socket_port,
            )

    def connect_to_mqtt_server(self):
        if self.mqttc.connected:
            print("MqqtNode() already connected")
            return
        while True:
            if self.wait_if_not_connected:
                timeout = None
            else:
                timeout = 0.01
            self.mqttc.connect(
                host=self.socket_host, port=self.socket_port, timeout=timeout
            )
            if self.mqttc.connected:
                print("MqqtNode() connected")
                break
            else:
                print("MqqtNode() NOT connected")
                return False
        if self.single_threaded:
            if self.select_timeout is None:
                self.mqttc.select_forever()
                return True
            else:
                return True
        else:
            # tkinter and others don't support threads.
            # This starts select() looping in a separate thread.
            self.mqttc.thread_start()
            return True

    def check_mqtt_pending_activity(self):
        # blocking mode nodes with blockingTimeoutSecs not None need
        # to call this periodically or messages will never be seen.
        # Depending on how you think about it, calling these blocking
        # may seem like an oxymoron.
        #
        # print ("ZZZ Check Activity timeout", self.select_timeout)
        try:
            self.mqttc.loop(timeout=self.select_timeout)
        except socket.error as e:
            # THIS IS WRONG
            # connected will be handled by mqttc client object.
            # I need to figure out who to save data for logging and
            # reconnect to server when possible.
            # Maybe do an E-Stop sort of thing.i
            # Helmsman stiops on e-stop. Other may change mode, signal operator, whtever
            print("check_mqtt_pending_activity() Socket Error:", e.errno)
            self.mqttc.connected = False

    def disconnect(self):
        if not self.single_threaded:
            self.mqttc.loop_stop(force=False)
        self.mqttc.disconnect()

    def get_ini_directory(self, section, attribute, IsWriteable=True):
        source = "vnavs.ini [{}] {}".format(section, attribute)
        dir_name = self.config.get(section, attribute)
        dir_name = vconst.CheckDirectory(dir_name, source, IsWriteable=IsWriteable)
        return dir_name

    def main_loop(self):
        while True:
            try:
                if self.automatically_connect and (not self.mqttc.connected):
                    # This could be a reconnection. Maybe we want more logging, etc.
                    # Exceptions with socket.error is how we detect a disconnect.
                    self.connect_to_mqtt_server()
                    print("loop() Just attempted to connect")
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
                            self.init_mqtt_client()
                            self.connect_to_mqtt_server()
                if self.mqttc.connected:
                    if self.single_threaded:
                        self.check_mqtt_pending_activity()
                    if (
                        self.has_synchronous_message_subscriptions
                        and self.automatically_handle_synchronous_messages
                    ):
                        self.handle_all_synchronous_messages()
                    if hasattr(self, "client_loop_code"):
                        # used to be do_loop()
                        self.client_loop_code()
                elif not self.wait_if_not_connected:
                    if (
                        self.has_synchronous_message_subscriptions
                        and self.automatically_handle_synchronous_messages
                    ):
                        self.handle_all_synchronous_messages()
                    if hasattr(self, "client_loop_code"):
                        # used to be do_loop()
                        self.client_loop_code()
                if self.check_exceptions():
                    sys.exit(0)
                if self.loop_sleep > 0:
                    # This is essentially a yield to the other thread. Without this, the communications
                    # thread can be blocked. Navigator was experiencing MANY MINUTES of message delivery
                    # delay without this. Nodes with lots of i/o in the main thread may not need this
                    # sleep. Cameraman does fine without it.
                    # Was using 0.01 sec, just changed to 0.001 to try speeding up process.
                    time.sleep(self.loop_sleep)
            except KeyboardInterrupt:
                self.cleanup_loop()
                sys.exit(0)
            except:
                exception_time = time.process_time()
                payload = {}
                payload["node_class"] = self.__class__.__name__
                payload["node_module"] = self.__module__
                payload["traceback"] = traceback.format_exc()
                print(payload["traceback"])  # display in case we are running in console
                self.publish(vconst.system_abend_topic, payload)
                self.cleanup_loop()
                if (exception_time - self.exception_last_time) < 60:
                    if self.exception_ct > 10:
                        sys.exit(0)
                    self.exception_ct += 1
                else:
                    self.exception_ct = 0
                self.exception_last_time = exception_time

    def cleanup_loop(self):
        pass  # override in client if cleanup needed

    #
    # Long running processes should call this periodically.
    # It was a particular problem when when capturing a long
    # long sequence with the RPI camera and the sender socket died.
    #
    def check_exceptions(self):
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

    def message_str(self, msg):
        max_chars = 25
        s = str(msg)
        if len(s) <= max_chars:
            return s
        return s[:max_chars] + " [...]"

    def get_latest_message(self, topic):
        # This methodology risks loosing a latest message that arrives between the line
        # where the payload is copied and the line where the subscription object payload is cleared.
        # This should be extremely rare and is not completely inconsistent with the expectation that
        # latest method subscriptions may not process all messages.
        # As currenty written, using a single swap statement, this should be completely thread safe.
        #
        if topic not in self.subscriptions:
            raise Exception("get_latest_message() unknown topic '{}'".format(topic))
        subscription = self.subscriptions[topic]
        if subscription.last_payload is None:
            return (
                None  # avoids tiny chance of clearing payload that arrives mid-method
            )
        payload, subscription.last_payload = subscription.last_payload, None
        return payload

    def handle_all_synchronous_messages(self):
        for this in self.subscriptions.values():
            if this.handler_method is None:
                continue
            if this.async_delivery:
                # messages was handled as soon as it arrived
                continue
            payload = self.get_latest_message(this.topic)
            if payload is not None:
                if this.handler_needs_topic:
                    this.handler_method(this.topic, payload)
                else:
                    this.handler_method(payload)

    # VnavsNode
    def publish(self, topic, payload, conf_request=None):
        # payload is a dict to be converted to JSON)
        # conf_request is an ID asking the recipient to clearly identify
        # the response to this request. This requires cooperative
        # requestors and respondors.
        if not self.mqttc.connected:
            print("publish() Not connected, not sent")
            # for now, silently ignore publish errors. Need to do better
            return
        self.vnavs_mid += 1
        j = vcomms.prepare_message(
            self.node_name,
            self.vnavs_pid,
            self.vnavs_mid,
            topic,
            payload,
            conf_request=conf_request,
        )
        if conf_request is not None:
            self.confirmation_pending[conf_request] = ConfirmationRequest(conf_request)
            print("publish() has confirmation request", payload)
        # print("publish() JSON", j)
        res, mid = self.mqttc.publish(topic, j)
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT publish Error")

    def get_conf_request(self, payload):
        return payload.get("_conf_request", None)

    def check_confirmation(self, conf):
        res = False
        if conf in self.confirmation_pending:
            c = self.confirmation_pending[conf]
            if c.payload is not None:
                res = True
                if c.checked_time is None:
                    c.checked_time = time.time
        self.scrub_confirmations()
        if res:
            return c.payload
        else:
            return None

    def scrub_confirmations(self):
        # This should delete checked confirmations after a little while
        # print("ScrubConfirmation()", self.confirmation_pending)
        return

    def wait_for_payload(self, conf):
        # This was created for limited use where convenience matters more than the ability
        # to handle exception cases.
        while True:
            if not (conf in self.confirmation_pending):
                print("wait_for_payload()", conf, "not pending.")
                return None  # maybe should be exception
            payload = self.check_confirmation(conf)
            if payload is not None:
                return payload
            self.check_mqtt_pending_activity()

    def on_connect(self, client, userdata, flags, rc):
        print("on_connect() rc: " + str(rc))
        for this_subscription in self.subscriptions.values():
            if not this_subscription.request_only:
                if this_subscription.message_queue is None:
                    mode = vmqtt.SUBSCRIPTION_MODE_LATEST
                else:
                    mode = vmqtt.SUBSCRIPTION_MODE_ALL
                self.mqttc.subscribe(this_subscription.topic, 0, mode=mode)

    def on_message(self, client, userdata, message):
        if self.verbose:
            print(
                "on_message()",
                message.topic
                + " "
                + str(message.qos)
                + " "
                + self.message_str(message.payload),
            )
        msg = message.payload
        # print(f"VnavsNode.on_message() MESSAGE {msg}")
        if msg == "":
            payload = {}
        else:
            try:
                payload = json.loads(msg)
            except ValueError:
                payload = {}
                print("JSON Error", message.payload)
        subscription = self.subscriptions[message.topic]
        # print(f"VnavsNode.on_message() PAYLOAD {payload}")
        if "_sendTime" in payload:
            send_time = float(payload["_sendTime"])
            send_diff = time.time() - send_time
            if send_diff > 120:
                print(
                    "Node stale message {} - {} = {} {}".format(
                        time.time(), send_time, send_diff, message.topic
                    )
                )
                # raise Exception("node message stale")
        #
        if "_isConfirmation" in payload:
            print("on_message() Message received with confirmation:", payload)
            conf_id = payload["_isConfirmation"]
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
