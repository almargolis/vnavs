import configparser
import json
import numpy as np
import os
import queue
import sys
import time

from vnavslib import vnavs_comms as vcomm
from vnavslib import vnavs_const as vconst
from vnavslib import vnavs_mqtt_clients as vmqtt

#
# FastMqttServer is a simplified broker that is much faster thean mosquitto.
# It supports publish/subscribe with less chance of blockage due to increased
# speed. Use that when you need to see every message.
# It also supports a read mode, which allows you to get the latst message
# for a topic without scrolling through all messages, ignoring any previous messages.
# This is essentially
# a LIFO. Use this for topics which generate large volumes of messages
# that you can't process.
#
# There is only one queue per client, so be careful about subscribing to high
# volume topics for time sensitive processes.
#


FMQTT_INI_SECTION = "MqttFastServer"
FMQTT_ARCHIVE_DIR = "ArchiveDir"
FMQTT_LOG_EXTENSION = ".nav"


class Subscription:
    __slots__ = ("message", "mode", "s", "topic")

    def __init__(self, topic, mode, s):
        self.topic = topic
        self.mode = mode
        self.message = None
        self.s = s  # socket - this is the id of the subsriber


class FastMqttServer(vcomm.SocketWrapperServer):
    __slots__ = (
        "archive_dir",
        "archiver",
        "mission_id",
        "no_archive",
        "topics_last_message",
        "subscriptions",
    )

    def __init__(self, NoArchive=False, verbose=False):
        super().__init__(
            ini_section=FMQTT_INI_SECTION, port=vconst.FAST_MQTT_PORT, verbose=verbose
        )
        self.topics_last_message = {}
        self.subscriptions = {}
        self.message_in_ct = 0
        self.message_out_ct = 0
        self.mission_id = None
        self.no_archive = NoArchive
        if not self.no_archive:
            try:
                self.archive_dir = self.config.get(FMQTT_INI_SECTION, FMQTT_ARCHIVE_DIR)
            except configparser.NoSectionError:
                print(f"No config file [{FMQTT_INI_SECTION}] - archiving disabled")
                self.no_archive = True
        if self.no_archive:
            self.archiver = None
            self.archive_dir = None
        else:
            self.archiver = MessageArchiver()
            self.archive_dir = os.path.expanduser(
                self.archive_dir
            )  # this expands tilde in path

    def close_client_connection(self, s):
        super().close_client_connection(s)

    def process_message(self, s, message):
        if message[0] == "":
            return
        action = message[0]
        if action == "publish":
            self.message_in_ct += 1
            server_time = time.time()
            topic = message[1]
            payload = message[2]
            self.topics_last_message[topic] = (
                self.message_in_ct,
                payload,
            )  # This saves the last message of each topic
            if self.verbose:
                print("PUBLISH", topic, self.subscriptions)
            if topic in self.subscriptions:
                for this in self.subscriptions[topic].values():
                    if this.s in self.input_sockets:
                        # we get here for subscription by still-connected sockets
                        # print("FastMqttServer.ProcesMessage() Queue {} for ?".format(topic))
                        if this.mode == vmqtt.SUBSCRIPTION_MODE_LATEST:
                            queue_class = vcomm.QueueOne
                        else:
                            queue_class = queue.Queue
                        self.queue_message_z(
                            ["message", topic, repr(self.message_in_ct), payload],
                            s=this.s,
                            QueueClass=queue_class,
                        )
            if topic == vconst.mission_init_topic:
                payload_dict = json.loads(payload)
                print("process_message()", payload_dict)
                if "mission_id" in payload_dict:
                    self.mission_id = payload_dict["mission_id"]
                else:
                    self.mission_id = "MISSION"  # this is really an error
            elif topic == vconst.mission_log_start_topic:
                archive_file_path = os.path.join(self.archive_dir, self.mission_id)
                self.archiver.open(archive_file_path)
            elif topic == vconst.mission_log_stop_topic:
                self.archiver.close()
            elif topic == vconst.mission_end_topic:
                pass
            elif topic == vconst.system_whoru:
                # print("WHORU")
                mid = 0
                payload_dict = json.loads(payload)
                payload_dict = vcomm.prepare_response(payload_dict, conf_request=True)
                j = vcomm.prepare_message(
                    "FastMqtt", 0, 0, vconst.system_server, payload_dict
                )
                self.queue_message_z(
                    ["message", vconst.system_server, repr(mid), j], s=s
                )
            if self.archiver is not None:
                self.archiver.archive(self.message_in_ct, server_time, payload)
        elif action == "read":
            topic = message[1]
            if topic in self.topics_last_message:
                (mid, payload) = self.topics_last_message[topic]
            else:
                mid = 0
                payload = "{}"
            self.queue_message_z(["message", topic, repr(mid), payload], s=s)
            print("READ", topic)
        elif action == "subscribe":
            topic = message[1]
            mode = message[2]
            subscription = Subscription(topic, mode, s)
            if not (topic in self.subscriptions):
                self.subscriptions[topic] = {}
            self.subscriptions[topic][
                s
            ] = subscription  # keep latest subscription if duplicate
            print("SUBSCRIPTIONS", topic, len(self.subscriptions[topic]))


class MessageArchiver:
    __slots__ = ("archive_buffer", "archive_size", "archive_file")

    def __init__(self):
        self.archive_buffer = []
        self.archive_size = 0
        self.archive_file = None

    def open(self, MissionName):
        fp = MissionName + FMQTT_LOG_EXTENSION
        self.archive_file = open(fp, "w")
        self.archive_buffer = []
        self.archive_size = 0

    def close(self):
        if self.archive_file is None:
            return
        self.write_buffer()
        self.archive_file.close()
        self.archive_file = None

    def archive(self, mid, ptime, payload):
        # message id, server publish time, json string payload
        if self.archive_file is None:
            return
        self.archive_buffer.append("{}\x00{}\x00{}\x01".format(mid, ptime, payload))
        self.archive_size += len(payload)
        if self.archive_size >= 4096:
            self.write_buffer()

    def write_buffer(self):
        if len(self.archive_buffer) < 1:
            return
        self.archive_file.write("".join(self.archive_buffer))
        self.archive_buffer = []
        self.archive_size = 0


def JsonShowTypes(payload):
    for key, value in payload.items():
        print(key, value.__class__.__name__, value)


if __name__ == "__main__":
    if "verbose" in sys.argv:
        print("verbose")
        verbose = True
    else:
        print("QUIET")
        verbose = False
    if "noarchive" in sys.argv:
        noarchive = True
    else:
        noarchive = False
    if sys.argv[1] == "m":
        s = FastMqttServer(NoArchive=noarchive, verbose=verbose)
        s.server()
    elif sys.argv[1] == "s":
        vcomm.status_info()
