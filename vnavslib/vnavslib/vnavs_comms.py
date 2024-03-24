import configparser
import json
import multiprocessing
import os
import queue
import select
import signal
import socket
import sys
import threading
import traceback
import time

from vnavslib import vnavs_const as vconst

stop_process = False

TCPIP_STD_BUFLEN = 4096
TCPIP_STD_BUFLEN = 8192
TCPIP_STD_BUFLEN = 1024
TCPIP_XFR_BUFLEN = 4096


def host_primary_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        s.connect((vconst.NON_ROUTABLE_IP, 1))
        ip_address = s.getsockname()[0]
    except:
        ip_address = vconst.host_LOCAL
    finally:
        s.close()
    return ip_address

def prepare_message(
    sender_name, sender_pid, sender_seq, topic, payload, conf_request=None
):
    payload["_topic"] = topic
    payload["_sender"] = sender_name
    payload["_sendTime"] = time.time()
    payload["_sendPid"] = sender_pid
    payload["_sendSeq"] = sender_seq
    if conf_request is not None:
        payload["_conf_request"] = conf_request
    j = json.dumps(payload, cls=JsonNumpyEncoder)
    return j


def prepare_response(payload, conf_request=False):
    # Prepares payload to be used as a response.
    # Copy identifier fields so recipients can match source message
    # so it knows request is completed and where to continue its process.
    # Info about original message is always there thanks to Publish()
    new_payload = {}
    if "_topic" in payload:
        new_payload["_ackTopic"] = payload["_topic"]
    if "_sendPid" in payload:
        new_payload["_ackPid"] = payload["_sendPid"]
    if "_sendSeq" in payload:
        new_payload["_ackSeq"] = payload["_sendSeq"]
    if conf_request:
        if "_conf_request" in payload:
            new_payload["_isConfirmation"] = payload["_conf_request"]
    return new_payload


class JsonNumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.int64):
            obj_out = int(obj)
            # print("JsonNumpyEncoder()", obj.__class__.__name__, obj_out.__class__.__name__)
            return obj_out
        return super().default(obj)



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
            except queue.Empty:
                # print("NO QUEUE", len(lifo))
                break  # the interprocess queue is empty
        if len(lifo) > 0:
            stream = lifo.pop()
            # print("SEND", len(lifo), len(stream))
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
                    s.send(stream[ix : ix + 1024])
                except (KeyboardInterrupt, SystemExit):
                    print("Terminated @ send() via KeyboardInterrupt")
                    # s.close()
                    return
                ix += 1024
            s.close()


#
# socket_xfer encapsulates a multi-processing point-to-point file transfer process.
# It was developed to transfer files between an RPI and a faster host for VNAVS.
# The client application just writes as if this were a reliable, single-threaded
# application. The ugly detals are completely hidden.
#
class socket_xfer:
    __slots__ = ('capture_ct', 'f',
              'os_socket_ip', 'os_socket_socket', 'queue', 'q_len', 'start', 'streamer',
              'timer_ct', 'timer_skip_ct', 'timer_start')

    def __init__(self):
        self.os_socket_ip = "192.168.8.11"
        self.os_socket_socket = 3050
        self.capture_ct = 0
        self.start = time.time()
        self.queue = multiprocessing.Queue()
        self.q_len = multiprocessing.Value("i", 0)
        self.streamer = multiprocessing.Process(
            target=Streamer,
            args=(self.queue, self.q_len, self.os_socket_ip, self.os_socket_socket),
        )
        self.streamer.daemon = True  # causes child process to terminate with its parent
        self.streamer.start()
        self.timer_ct = 0
        self.timer_skip_ct = 0
        self.timer_start = time.clock()
        self.f = open("temp.text", "w")

    def stop(self):
        self.streamer.join()

    def write(self, stream):
        self.capture_ct += 1
        self.f.write("%d\n" % (self.capture_ct))
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
            print(
                "Qd %d in %f secs SKIPPED %d"
                % (self.timer_ct, timer_stop - self.timer_start, self.timer_skip_ct)
            )
            self.timer_ct = 0
            self.timer_skip_ct = 0
            self.timer_start = timer_stop


#
# SocketWrapperServer() SocketWrapperClient()
#
# These objects encapsulate Python low level socket services with a number of idioms that
# I found necessary to make typical example code run reliably for VNAVS.
# At this point I am not positive that I wouldn't have been better off using a higher level
# object instead of writing this.
#
# Possible advantages of this object:
#     - conforms to VNAVS coding style
#     - explicit comments / handling of return states and error codes
#     - explicit python state variables
#     - optionally supports zero/one message protocol
#
# There are at least two levels of "blocking" that are often not clearly
# distinguished in socket / protocol documentation.
# Including here, until just now.
#
# Socket blocking refers to whether the OS should complete an operation before returning
# to the calling thread.
#
# Process blocking refers to whether communications should occur in the same thread as
# the main operation of the client.
#
# Non-trivial client applications will usually be process non-blocking. The network communication
# is executed in its own thread so the main application loop stays responsive to the keyboard or
# other external events. In this case, socket operations will often be blocking. Since the
# communications thread is talking to a single server and the process is often sequential, there is
# no harm in letting the OS suspend the thread until each operation is completed. That is
# probably the most efficentient way to serialize network processes. There is probably no reason
# for a process non-blocking client to use socket non-blocking functions.
#
# Server applications will usually be process blocking because all they do is deal with socket
# communications. They don't need to be responsive to a keyboard, etc. A small level of responsiveness
# can be provided via OS signals. Server socket operations will alsmost always be non-blocking
# so the server can have communications with multiple clients in-process simultaneously.
# These parallel sockets are coordinated through select(). A single threaded server is likely
# getting some benefit from multiple cores via threading inside the OS. It is possible for a server
# to utilize seperate threaads or even separate processes per client socket or group of client sockets
# but that is not supported by this object.
#
# QueueOne is an alternate queue with a max lenght of one.
#
class QueueOne:
    __slots__ = ("message",)

    def __init__(self):
        self.message = None

    def get_nowait(self):
        if self.message is None:
            raise queue.Empty
        result, self.message = self.message, None
        return result

    def put(self, message):
        self.message = message


class SocketWrapper:
    __slots__ = (
        "buffer_len",
        "config",
        "debug",
        "fragments",
        "is_server",
        "is_socket_blocking",
        "is_zero_one_protocol",
        "input_sockets",
        "message_in_ct",
        "message_out_ct",
        "os_socket",
        "output_queues",
        "output_sockets",
        "sent_ct",
        "socket_host",
        "socket_port",
        "verbose",
    )

    def __init__(
        self,
        buffer_len=TCPIP_STD_BUFLEN,
        host="",
        ini_section=None,
        is_server=False,
        is_socket_blocking=False,
        port=vconst.DEFAULT_PORT,
        is_zero_one_protocol=True,
        verbose=False,
    ):
        self.buffer_len = buffer_len
        self.config = configparser.ConfigParser()
        self.config.read_file(open(vconst.config_file_path))
        self.debug = "c"
        self.socket_host = host
        self.socket_port = port
        self.sent_ct = 0
        if ini_section is not None:
            try:
                self.socket_host = self.config.get(ini_section, "host")
                self.socket_port = int(self.config.get(ini_section, "port"))
            except configparser.NoSectionError:
                print(
                    "Ini section {} not found, using default host/port {}/{}".format(
                        ini_section, host, port
                    )
                )

        # This can be a server or client. Either way, self.os_socket is the primary socket
        #
        # Socket communications between OSX and RPI can be painfully slow, as in minutes.
        # TCP_NODELAY solved the problem. As a test, I commented it out and it remained
        # fast, so the setting may be stickly to some degree. The slowness problem had
        # persisted over many days and several reboots of both RPI and OSX, so
        # slowness was a real problem, not transient. Google finds lots if discussion
        # with try this / try that suggestions. This one made the most sense to me.
        # I could imaging Apple not caring much about custom socket protocols but
        # but  being concerned about hogging the network with lots of small packets
        # which might slow other applications. This problem was never exhibited on
        # the RPI side of the communications (RPI <-> RPI) only (RPI <-> OSX).
        #
        # On Raspbian, when killing FastMqttServer
        # with kill -HUP, it could not be restarted for a while due to
        # socket.error: [Errno 98] Address already in use
        # Trying tcpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # per: https://stackoverflow.com/questions/19071512/socket-error-errno-48-address-already-in-use
        #
        self.is_server = is_server
        self.is_zero_one_protocol = is_zero_one_protocol
        self.message_in_ct = 0
        self.message_out_ct = 0
        self.is_socket_blocking = is_socket_blocking
        self.init_socket()
        self.verbose = verbose
        self.init_select_data()

    def init_socket(self):
        # Blocking and the timeout on socket functions do the same thing. Maybe they are the same thing.
        # Blocking on (setblocking(0)) is equivalent to s.settimeout(0.0).
        # Blocking off (setblocking(1)) is equivalent to s.settimeout(None).
        # os_socket.gettimeout() returns the socket timeout. Maybe implicitly the blocking mode?
        # This is not at all the same as the timeout on select but they obviously interact in some way.
        #
        self.os_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.os_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.os_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if self.is_socket_blocking:
            self.os_socket.setblocking(1)
        else:
            self.os_socket.setblocking(0)

    def init_select_data(self):
        self.input_sockets = [self.os_socket]
        self.output_sockets = []
        self.output_queues = {}
        self.fragments = {}

    def close_client_connection(self, s):
        # This closes the connection to one of a server's clients.
        # This takes care of client clean-up for servers that are using
        # select() and output queues to handle multuple clients in one thread.
        if s in self.output_sockets:
            self.output_sockets.remove(s)
        if s in self.input_sockets:
            self.input_sockets.remove(s)
        if s in self.output_queues:
            del self.output_queues[s]
        if s in self.fragments:
            del self.fragments[s]
        s.close()

    def disconnect(self):
        self.os_socket.close()
        self.init_select_data()

    def print_error(self, loc, e):
        print(
            "Exception @ %s: %s [%s] %s"
            % (loc, e.__class__.__name__, e.errno, e.strerror)
        )

    def process_received_packet(self, s, data):
        # This colates messages using zero/one protocol.
        # It concatenates TCP packets until a complete messsage is available.
        # Messages are identified by a final \x01 character.
        # Messages are delivered to the application process_message()
        # method with a list of fields values. Fields are separated
        # by \x00 characters.
        # This is completely safe only for ASCII protocols, but may work
        # work with UTF-8 since Python hides lots of that (but not verified).
        if s in self.fragments:
            data = self.fragments[s] + data
            del self.fragments[s]
        messages = data.split(b"\x01")  # split data block into messages
        # print("SocketWrapper.process_received_packet()", data, "**", messages)
        if data[-1] != b"\x01":
            # the last message isn't complete, save the fragment
            fragment = messages.pop()
            self.fragments[s] = fragment
        for this_message in messages:
            this_message = this_message.decode("utf-8")
            if this_message == "":
                # This happens routinely if the last character of data is \x01.
                # split() always splits, so it creates an empty string at the end of the list.
                continue
            parts = this_message.split("\x00")
            # print("SocketWrapper.process_received_packet()", this_message, parts)
            self.process_message(s, parts)

    def queue_message(self, message, s=None, QueueClass=queue.Queue):
        # message is a string
        # print("ZZZ - Q request")
        if s is None:  # This should only be true if self.is_server is False
            s = self.os_socket
        if not s in self.output_queues:
            self.output_queues[s] = QueueClass()
        self.output_queues[s].put(message)
        self.message_out_ct += 1
        if s not in self.output_sockets:
            self.output_sockets.append(s)

    def queue_message_z(self, parts, s=None, QueueClass=queue.Queue):
        msg_parts = []
        for this in parts:
            msg_parts.append(this)
            msg_parts.append("\x00")
        msg_parts.append("\x01")
        # print("YYY", msg_parts)
        self.queue_message("".join(msg_parts), s=s, QueueClass=QueueClass)

    def select(self, timeout=1.0):
        # If this is a server and the client connection fails, we want to clean up that connection and
        # continue serving. Potentially could want to nofify someone.
        # If this is a client, we want to neaten things up but re-raise the exception because the
        # main flow of the client is probably disrupted.
        #
        # OS select() waits for inputs, just as you would casually expect, so it is safe to have all inout sockets
        # in the list. Output sockets are ready whenever the buffer is empty, so if you leave an inactive socket
        # in the output list, select returns immediately because it is writable. Therefore, output sockets should
        # only be in the list when you actually have something to write. If you are a no-timeout select when that
        # socket gets added to the output list, nothing happens immediatly because the OS doesn't know about it.
        # The new output message will languish until something else releases the select. Because of this, it should
        # be fairly unusual to call select with no timeout.
        #
        # timeout=None blocks indefinately, timeout=0.0 polls and return immediately, potentially with three empty lists
        #
        # print('select waiting for the next event', self.input_sockets, self.output_sockets, timeout)
        readable, writable, exceptional = select.select(
            self.input_sockets, self.output_sockets, self.input_sockets, timeout
        )
        for s in readable:
            # print("select() READABLE")
            if self.is_server and (s is self.os_socket):
                # A "readable" server socket is ready to accept a connection
                connection, client_address = s.accept()
                connection.setblocking(0)
                self.input_sockets.append(connection)
                if self.verbose or ("c" in self.debug):
                    print(
                        "new connection from",
                        client_address,
                        "total connections",
                        len(self.input_sockets),
                    )
            else:
                try:
                    data = s.recv(self.buffer_len)  # data is bytes
                    # print("SocketWrapper.select() READ ", data)
                except socket.error as e:
                    # I have seen e.errno = 54 and 104 as] "Connection reset by peer"
                    self.print_error("select:readable", e)
                    if self.is_server:
                        if s is self.os_socket:
                            self.disconnect()
                            return
                        else:
                            self.close_client_connection(s)
                        data = None
                    else:
                        self.disconnect()
                        raise
                if data:
                    if self.is_zero_one_protocol:
                        self.process_received_packet(s, data)
                    else:
                        self.RecvData(s, data)
                else:
                    # Interpret empty result as closed connection
                    self.close_client_connection(s)
        for s in writable:
            # print("SOMETHING WRITEABLE")
            try:
                next_msg = self.output_queues[s].get_nowait()
            except queue.Empty:
                # print("No messages waiting so stop checking for writability.")
                self.output_sockets.remove(s)
            except KeyError:
                # This happened to a client *mission_control.py). Apparently when FastMqtt crashed.
                print("WRITEABLE - no socket")
                pass  # socket buffer available, but no messages to send
            else:
                try:
                    # print("select() trying to send:", next_msg)
                    if not isinstance(next_msg, bytes):
                        next_msg = next_msg.encode(
                            "utf-8"
                        )  # convert to bytes for Python 3.x
                    s.send(next_msg)
                    self.sent_ct += 1
                    if self.verbose:
                        print("SEND", next_msg)
                except socket.error as e:
                    self.print_error("select:writeable", e)
                    if self.is_server:
                        # socket.error: [Errno 104] Connection reset by peer (I ctrl-C client)
                        self.close_client_connection(s)
                    else:
                        self.disconnect()
                        raise
        for s in exceptional:
            print("EXCEPTIONAL")
            if self.is_server:
                self.close_client_connection(s)
            else:
                self.disconnect()
                raise

    def select_forever(self, MaxAllowableWriteLatency=0.001):
        # This error 9 occurs in the OS select call for a client if the server goes
        # away. That kills the SocketWrapper thread but leaves the main thread
        # running but not communicating. This is now trapped in Loop() by checking
        # thread.is_alive().
        # error: [Errno 9] Bad file descriptor
        while True:
            self.select(timeout=MaxAllowableWriteLatency)

#def cleanup(signum, stack_frame)


class SocketWrapperServer(SocketWrapper):
    __slots__ = ()

    def __init__(
        self,
        buffer_len=TCPIP_STD_BUFLEN,
        host="",
        ini_section=None,
        is_zero_one_protocol=True,
        port=vconst.DEFAULT_PORT,
        verbose=False,
    ):
        # if ini_section is specified, it is used. Else specify host/port. host of '' binds to all avalable networks.
        super().__init__(
            buffer_len=buffer_len,
            host="",
            ini_section=ini_section,
            is_zero_one_protocol=is_zero_one_protocol,
            is_server=True,
            is_socket_blocking=False,
            port=port,
            verbose=verbose,
        )
        #signal.signal(signal.SIGHUP, cleanup)

    def server(self, host=None, port=None):
        if host is not None:
            self.socket_host = host
        if port is not None:
            self.socket_port = port
        self.os_socket.bind((self.socket_host, self.socket_port))
        self.os_socket.listen(5)
        if self.socket_host == "":
            displayhost = "INADDR_ANY"
        else:
            displayhost = self.socket_host
        print("Server listening on host %s, port %s." % (displayhost, self.socket_port))
        print("Server listening on port %s." % (repr(self.os_socket.getsockname()),))
        while True:
            self.select(timeout=None)


class SocketWrapperClient(SocketWrapper):
    __slots__ = ("connected", "connect_in_progress", "thread")

    def __init__(
        self,
        buffer_len=TCPIP_STD_BUFLEN,
        ini_section=None,
        is_zero_one_protocol=True,
        verbose=False,
    ):
        super().__init__(
            buffer_len=buffer_len,
            ini_section=ini_section,
            is_zero_one_protocol=is_zero_one_protocol,
            is_socket_blocking=False,
            verbose=verbose,
        )
        self.connected = False
        self.connect_in_progress = False
        self.thread = None

    # connect()
    #
    # Operation of connect in non-blocking mode is a bit surprising:
    #
    # If the connection cannot be established immediately and O_NONBLOCK is set for the file descriptor
    # for the socket, connect() will fail and set errno to [EINPROGRESS], but the connection request
    # will not be aborted, and the connection will be established asynchronously. Subsequent calls
    # to connect() for the same socket, before the connection is established, fail and set
    # errno to [EALREADY].
    #
    # The above applies to both OSX and Rapbian, but the specific error numbers are different.
    #
    # Connect may be called redundently due to the asynchronous nature of socket communication
    # in multiple application and OS threads. Once connected, don't do anything here,
    # assuming this is some sort of race condition.
    #
    # As this has evolved, clients are now always socket i/o blocking. I have left some
    # of the non-blocking code in place because it is hard-won knowledge that may be useful
    # again. Client socket operations are almost always sequential, so they might as well be
    # blocking. This client supports threading so the main applicaion loop runs even when
    # socket functions are blocked.
    #
    def connect_async(self, host=None, port=None, keepalive=60):
        if host is not None:
            self.socket_host = host
        if port is not None:
            self.socket_port = port
        try:
            print("connect_async()", self.socket_host, self.socket_port)
            self.os_socket.connect((self.socket_host, self.socket_port))
            self.connected = True
            print("connect_async() Successful")
            return True
        except socket.error as e:
            if e.errno in [22, 36, 37, 48, 56, 61, 65, 111, 114, 115]:
                # BlockingIOError started appearing in exception messages instead of socket_error
                # in Raspbian Stretch / Python3.5. Not sure if any action needed.
                #
                # Succesful non-blocking connection innitiaion
                # raises 36 under OSX or 115 under Raspbian.
                # Repeated attemps raises 37 under OSX or 115 under Raspbian
                # without disturbing connection.
                # This is not an error. Just a non-blocking indication that the
                # connection process has been started or is continuing.
                #
                # Error 56 signifies success, its not an error.
                # Otherwise, we could check for completion with poll or select
                # or maybe poll2 or select2. I saw comment about these but haven't tested.
                #
                # Under Raspbian Stretch, got 114 when connected to wrong WLAN so there
                # was no such ip address or port.
                #
                # If the server is unreachable (no route / on wrong network), OSX reports
                # 36 and then 37.
                #
                # If server is down, OSX reports 36 then 61, then 22. Error 22 then
                # repeats and the socket never connects, even when the server becomes available.
                # In a long loop of failures waiting for the server to come up,
                # OSX sometimes reports 37 after 36 instead of 61.
                # Raspbian reports 111 and then 115 repeated and smoothly connects
                # whenever the server becomes available.
                #
                # socket.error: [Errno 22] Invalid argument
                # socket.error: [Errno 36] Operation now in progress
                # socket.error: [Errno 37] Operation already in progress
                # socket.error: [Errno 48] Address already in use
                #   #48 experienced 3/24/24 after #65 on program restarts.
                #   This happened repeatedly on ports that had been fine
                #   repeatedly until I added 65 to the exception list.
                #   Communications seemed OK after adding 48 and 65 to lsit.
                # socket error: [Errno 56] Socket is already connected
                # socket.error: [Errno 61] Connection refused
                # socket.error: [Errno 65] No route to host
                #   #65 experienced 3/24/24, MACOS on client attempting to connect
                #   to non-existant server. While scanning for a server.
                #   Other non-existant servers did not cause this error.
                #   Ping to that ip just returned a normal looking timeout.
                # socket.error: [Errno 111] Connection refused
                # socket.error: [Errno 114] Operation already in progress (new, Raspbian Stretch)
                # socket.error: [Errno 115] Operation now in progress
                if e.errno in [56]:
                    self.connected = True
                    self.connect_in_progress = False
                    return True
                else:
                    if e.errno == 22:
                        self.init_socket()
                    self.connected = False
                    self.connect_in_progress = True
                    return False  # not connected but not a hard failure
            else:
                self.print_error("connect_async()", e)
                raise

    def connect(self, host=None, port=None, keepalive=60, timeout=None):
        # This is a blocking connect()
        # It is safe to call this redundantly after connect_async() starts
        # the process but the application has no other work to do.
        # Fast LAN connect times seem to be a few tens of miliseconds, a few seconds
        # is not that unusual talking to busy servers over slow connections.
        # The logic of blocking / non-blocking socket i/o is a bit different for
        # connect than data transfers. The original connect happens before the
        # new process thread is started. connect_async() allows the application to
        # remain respomsive during start-up.
        start_time = time.time()
        while not self.connected:
            self.connect_async(host=host, port=port, keepalive=keepalive)
            if not self.connected:
                if timeout is not None:
                    if (time.time() - start_time) > timeout:
                        return False
                print("SocketWrapperClient.connect() waiting for connection")
                time.sleep(0.01)
        return True

    def select_thread_start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.select_forever)
            self.thread.start()
        else:
            if not self.thread.is_alive():
                self.thread.start()

    def select_thread_stop(self):
        if self.thread is not None:
            self.thread.stop()
            self.thread = None

    def blocking_write_socket(self, msg):
        # For clients that want to block while sending
        retry_ct = 0
        while retry_ct < 10:
            try:
                self.os_socket.sendall(msg)
                return True
            except socket.error as e:
                self.print_error("blocking_write_socket", e)
                # socket.error: [Errno 11] Resource temporarily unavailable
                # socket.error: [Errno 32] Broken pipe
                # need to check Errno - kept running even when server died
                retry_ct += 1
        return False




def status_info():
    print("This host IP Address:", host_primary_ip_address())

