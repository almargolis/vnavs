from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import json
import multiprocessing
import os
import Queue
import select
import socket
import sys
import threading
import traceback
import time

import paho.mqtt.client as mqtt

import vnavs_const as vconst

if sys.version_info[0] < 3:
    import ConfigParser
else:
    import configparser as ConfigParser

config_file_path = os.path.expanduser("~/vnavs.ini")
handler_method_prefix = 'rmsg_'
wildcard_method_name = handler_method_prefix + 'wildcard'

stop_process = False

TCPIP_STD_BUFLEN = 1024
TCPIP_XFR_BUFLEN = 4096
FAST_MQTT_PORT = 4000
DEFAULT_PORT = 3000
HOST_LOCAL = '127.0.0.1'
ARG_HOST = 'host'
ARG_PORT = 'port'
ARG_LOCAL = 'local'
ARG_IMAGE_DIR = 'imagedir'
ARG_IMAGE_GET = 'imageget'
ARG_TRUE = 'true'
ARG_FALSE = 'false'
ARG_CWD = 'cwd'

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
            #print("SEND", len(lifo), len(stream))
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
        self.os_socket_ip = "192.168.8.11"
        self.os_socket_socket = 3050
        self.capture_ct = 0
        self.start = time.time()
        self.queue = multiprocessing.Queue()
        self.q_len = multiprocessing.Value('i', 0)
        self.streamer = multiprocessing.Process(target=Streamer, args=(self.queue, self.q_len, self.os_socket_ip, self.os_socket_socket))
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

#
# SocketWrapperServer() SocketWrapperClient()
#
# These objects enccapsulates Python low level socket services with a number of idioms that
# I found necessary to make typical example code run reliably for VNAVS.
# At this point I am not positive that I wouldn't have been better off using a higher level
# object instead of writing this.
#
# Possible advantages of this object:
#     - confirms to VNAVS coding style
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
# Non-trivial client applications wll usually be process non-blocking. The network communication
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

class SocketWrapper(object):
    def __init__(self, BufferLen=TCPIP_STD_BUFLEN, Host='', IniSection=None, IsServer=False, IsSocketBlocking=False, Port=DEFAULT_PORT, IsZeroOneProtocol=True,
					Verbose=False):
        self.buffer_len = BufferLen
        self.config = ConfigParser.SafeConfigParser()
        self.config.readfp(open(config_file_path))
        self.socket_host = Host
        self.socket_port = Port
        if IniSection is not None:
            try:
                self.socket_host = self.config.get(IniSection, "Host")
                self.socket_port = int(self.config.get(IniSection, "Port"))
            except ConfigParser.NoSectionError:
                print("Ini section {} not found, using default host/port {}/{}".format(IniSection, Host, Port))

        # This can be a server or client. Either way self.os_socket is the primary socket
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
        self.isServer = IsServer
        self.isZeroOneProtocol = IsZeroOneProtocol
        self.message_out_ct = 0
        self.is_socket_blocking = IsSocketBlocking
        self.InitSocket()
        self.verbose = Verbose
        self.InitSelectData()

    def InitSocket(self):
        self.os_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.os_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if self.is_socket_blocking:
            self.os_socket.setblocking(1)
        else:
            self.os_socket.setblocking(0)

    def InitSelectData(self):
        self.inputSockets = [ self.os_socket ]
        self.outputSockets = []
        self.outputQueues = {}
        self.fragments = {}

    def CloseClientConnection(self, s):
        # This closes the connection to one of a server's clients.
        # This takes care of client clean-up for servers that are using
        # select() and ouytput queues to handle multuple clients in one thread.
        if s in self.outputSockets:
            self.outputSockets.remove(s)
        if s in self.inputSockets:
            self.inputSockets.remove(s)
        if s in self.outputQueues:
            del self.outputQueues[s]
        if s in self.fragments:
            del self.fragments[s]
        s.close()

    def Disconnect(self):
        self.os_socket.close()
        self.InitSelectData()

    def PrintError(self, loc, e):
        print("Exception @ %s: %s [%s] %s" % (loc, e.__class__.__name__, e.errno, e.strerror))

    def ProcessReceivedPacket(self, s, data):
        # This colates messages using zero/one protocol.
        # It concatenates TCP packets until a complete messsage is available.
        # Messages are identified by a final \x01 character.
        # Messages are delivered to the application ProcessMessage()
        # method with a list of fields values. Fields are separated
        # by \x00 characters.
        # This is completely safe only for ASCII protocols, but may work
        # work with UTF-8 since Python hides lots of that (but not verified).
        if s in self.fragments:
            data = self.fragments[s] + data
            del self.fragments[s]
        messages = data.split('\x01')
        #print("PRC", data, "**", messages)
        if data[-1] != '\x01':
            # the last message isn't complete, save the fragment
            fragment = messages.pop()
            self.fragments[s] = fragment
        for this_message in messages:
            if this_message == '':
                # This happens routinely if the last character of data is \x01.
                # split() always splits, so it creates an empty string at the end of the list.
                continue
            parts = this_message.split('\x00')
            #print("RCV", parts)
            self.ProcessMessage(s, parts)

    def QueueMessage(self, message, s=None):
        if s is None:				# This should only be true if self.isServer is False
            s = self.os_socket
        if not s in self.outputQueues:
            self.outputQueues[s] = Queue.Queue()
        self.outputQueues[s].put(message)
        self.message_out_ct += 1
        if s not in self.outputSockets:
            self.outputSockets.append(s)

    def QueueMessageZ(self, parts, s=None):
        msg_parts = []
        for this in parts:
            msg_parts.append(this)
            msg_parts.append('\x00')
        msg_parts.append('\x01')
        self.QueueMessage(''.join(msg_parts), s=s)

    def Select(self, timeout=1.0):
        # If this is a server and the client connection fails, we want to clean up that connection and
        # continue serving. Potentially could want to nofify someone.
        # If this is a client, we want to neaten things up but re-raise the exception because the
        # main flow of the client is probably disrupted.
        #
        # OS select() waits for inputs, just as you would casually expect, so it is safe to have all inout sockets
        # in the list. Output sockets are ready whenever the buffer is empty, so if you leave an inactive socket
        # in the output list, select returns immediately because it is writable. Therefore, output sockets should
        # only be in hte list when you actually have something to write.n If you are a no-timeout select when that
        # socket gets added to the output list, nothing happens immediatly because the OS doesn't know about it.
        # The new output message will languish until something else releases the select. Because of this, it should
        # be fairly unusual to call select with no timeout.
        #
        # timeout=None blocks indefinately, timeout=0.0 polls and return immediately, potentially with three empty lists
        #
        #print('SELECT waiting for the next event', self.inputSockets, self.outputSockets, timeout)
        readable, writable, exceptional = select.select(self.inputSockets, self.outputSockets, self.inputSockets, timeout)
        for s in readable:
            #print("READABLE")
            if self.isServer and (s is self.os_socket):
                # A "readable" server socket is ready to accept a connection
                connection, client_address = s.accept()
                connection.setblocking(0)
                self.inputSockets.append(connection)
                if self.verbose:
                    print('new connection from', client_address, 'total connections', len(self.inputSockets))
            else:
                try:
                    data = s.recv(self.buffer_len)
                except socket.error as e:
                    # I have seen e.errno = 54 and 104 as] "Connection reset by peer"
                    self.PrintError('Select:readable', e)
                    if self.isServer:
                        if s is self.os_socket:
                            self.disconnect()
                            return
                        else:
                            self.CloseClientConnection(s)
                        data = None
                    else:
                        self.Disconnect()
                        raise
                if data:
                    if self.isZeroOneProtocol:
                        self.ProcessReceivedPacket(s, data)
                    else:
                        self.RecvData(s, data)
                else:
                    # Interpret empty result as closed connection
                    self.CloseClientConnection(s)
        for s in writable:
            #print("SOMETHING WRITABLE")
            try:
                next_msg = self.outputQueues[s].get_nowait()
            except Queue.Empty:
                # No messages waiting so stop checking for writability.
                self.outputSockets.remove(s)
            except KeyError:
                # This happened to a client *mission_control.py). Apparently when FastMqtt crashed.
                print("WRITEABLE - no socket")
                pass			# socket buffer available, but no messages to send
            else:
                try:
                    s.send(next_msg)
                    if self.verbose:
                        print("SEND", next_msg)
                except socket.error as e:
                    self.PrintError('Select:writeable', e)
                    if self.isServer:
                        # socket.error: [Errno 104] Connection reset by peer (I ctrl-C client)
                        self.CloseClientConnection(s)
                    else:
                        self.disconnect()
                        raise
        for s in exceptional:
            print("EXCEPTIONAL")
            if self.isServer:
                self.CloseClientConnection(s)
            else:
                self.disconnect()
                raise

    def SelectForever(self, MaxAllowableWriteLatency=0.001):
        # This error 9 occurs in the OS select call for a client if the server goes
        # away. That kills the SocketWrapper thread but leaves the main thread
        # running but not communicating. This is now trapped in Loop() by checking
        # thread.is_alive().
        # error: [Errno 9] Bad file descriptor
        while True:
            self.Select(timeout=MaxAllowableWriteLatency)

class SocketWrapperServer(SocketWrapper):
    def __init__(self, BufferLen=TCPIP_STD_BUFLEN, Host='', IniSection=None, IsZeroOneProtocol=True, Port=DEFAULT_PORT, Verbose=False):
        # if IniSection is specified, it is used. Else specify Host/Port. Host of '' binds to all avalable networks.
        super().__init__(BufferLen=BufferLen, Host='', IniSection=IniSection, IsZeroOneProtocol=IsZeroOneProtocol, IsServer=True, IsSocketBlocking=False, Port=Port, Verbose=Verbose)

    def Serve(self, host=None, port=None):
        if host is not None:
            self.socket_host = host
        if port is not None:
            self.socket_port = port
        self.os_socket.bind((self.socket_host, self.socket_port))
        self.os_socket.listen(5)
        if self.socket_host == '':
            displayHost = 'INADDR_ANY'
        else:
            displayHost = self.socket_host
        print("Server listening on host %s, port %s." % (displayHost, self.socket_port))
        print("Server listening on port %s." % (`self.os_socket.getsockname()`))
        while True:
            self.Select(timeout=None)

class SocketWrapperClient(SocketWrapper):
    def __init__(self, BufferLen=TCPIP_STD_BUFLEN, IniSection=None, IsZeroOneProtocol=True, Verbose=False):
        super().__init__(BufferLen=BufferLen, IniSection=IniSection, IsZeroOneProtocol=IsZeroOneProtocol, IsSocketBlocking=False, Verbose=Verbose)
        self.connected = False
        self.connect_in_progress = False
        self.thread = None
        self.verbose = Verbose

    # connect()
    #
    # Operation of connect in non-blocking mode is a bit surprising:
    #
    # If the connection cannot be established immediately and O_NONBLOCK is set for the file descriptor
    # for the socket, connect() shall fail and set errno to [EINPROGRESS], but the connection request
    # shall not be aborted, and the connection shall be established asynchronously. Subsequent calls
    # to connect() for the same socket, before the connection is established, shall fail and set
    # errno to [EALREADY].
    #
    # The above applies to both OSX and Rapbian, but the specific error numbers are different.
    #
    # Connect may be called redundently due to the asynchronous nature of socket communication
    # in multiple application and OS threads. Once connected, don't do anything here,
    # assuming this is some sort of race condition.
    #
    # As this has eveolved, clients are now always socket i/o blocking. I have left some
    # of the non-blocking code in place because it is hard-won knowledge that may be useful
    # again. Client socket operations are almost always sequential, so they might as well be
    # blocking. This client supports threading so the main applicaion loop runs even when
    # socket functions are blocked.
    #
    def ConnectAsync(self, host=None, port=None, keepalive=60):
        if host is not None:
            self.socket_host = host
        if port is not None:
            self.socket_port = port
        try:
            self.os_socket.connect((self.socket_host, self.socket_port))
            self.connected = True
            print("ConnectAsync() DirectConnect")
            return True
        except socket.error as e:
            self.PrintError("ConnectAsync()", e)
            if e.errno in [22, 36, 37, 56, 61, 111, 115]:
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
                # socket error: [Errno 56] Socket is already connected
                # socket.error: [Errno 61] Connection refused
                # socket.error: [Errno 111] Connection refused
                # socket.error: [Errno 115] Operation now in progress
                if e.errno == 56:
                    self.connected = True
                    self.connect_in_progress = False
                    return True
                else:
                    if e.errno == 22:
                        self.InitSocket()
                    self.connected = False
                    self.connect_in_progress = True
                    return False				# not connected but not a hard failure
            else:
                raise

    def Connect(self, host=None, port=None, keepalive=60, timeout=None):
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
            self.ConnectAsync(host=host, port=port, keepalive=keepalive)
            if not self.connected:
                if timeout is not None:
                    if (time.time() - start_time) > timeout:
                        return False
                time.sleep(0.01)
        return True

    def SelectThreadStart(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.SelectForever)
            self.thread.start()
        else:
            if not self.thread.is_alive():
                self.thread.start()

    def SelectThreadStop(self):
        if self.thread is not None:
            self.thread.stop()
            self.thread = None

    def BlockingWriteSocket(self, msg):
        # For clients that want to block while sending
        retry_ct = 0
        while retry_ct < 10:
            try:
                self.os_socket.sendall(msg)
                return True
            except socket.error as e:
                self.PrintError('BlockingWriteSocket', e)
                # socket.error: [Errno 11] Resource temporarily unavailable
                # socket.error: [Errno 32] Broken pipe
                # need to check Errno - kept running even when server died
                retry_ct += 1
        return False

class FileServer(SocketWrapperServer):
    def __init__(self, Verbose=True):
        super().__init__(BufferLen=TCPIP_XFR_BUFLEN, IniSection="FileServer", Verbose=Verbose)
        self.imageDir = self.config.get("Cameraman", "ImageDir")

    def ProcessMessage(self, s, message):
        fn = message[0]
        fp = os.path.join(self.imageDir, fn)
        print("FS", fn, fp, message)
        try:
            f = open(fp, 'rb')
            c = f.read()
            f.close()
        except IOError as e:
            # IOError: [Errno 2] No such file or directory: '/bot1/images/R20170513114208_0_11202.jpeg'
            if e.errno == 2:
                self.QueueMessage('0\x00', s=s)
                return
            else:
                raise
        print("SEND FILE", fp, len(c))
        ix = 0
        while ix < len(c):
            rec = c[ix:ix+self.buffer_len]
            if ix == 0:
                rec = `len(c)` + '\x00' + rec
            self.QueueMessage(rec, s=s)
            ix += self.buffer_len

class FileClient(SocketWrapperClient):
    def __init__(self, Verbose=False):
        super().__init__(BufferLen=TCPIP_XFR_BUFLEN, IniSection="FileClient", IsZeroOneProtocol=False, Verbose=Verbose)
        self.Init()

    def Init(self):
        self.file_name = None
        self.file_out = None
        self.buffer = ""
        self.file_received = False

    def GetFile(self, filename, path=None, timeout=30.0):
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
            # inconsistency of block / no block. Or one of hte OSes trying to be polite.
            time.sleep(1)
            print("FC TRY CONNECT", self.socket_host, self.socket_port)
            self.Connect()
        #print("FC CONNECTED")
        self.file_name = filename
        if path is None:
            self.file_path = filename
        else:
            self.file_path = path
        self.file_out = open(self.file_path, "wb")
        self.buffer = bytearray()
        self.buf_sum = 0
        self.QueueMessageZ([filename])
        start_time = time.time()
        while (not self.file_received) and ((time.time() - start_time) < timeout):
            self.Select(timeout=0.1)
        self.file_out.close()
        #print("DONE", time.time() - start_time)
        return self.file_received

    def RecvData(self, s, data):
        self.buffer += data
        self.buf_sum += len(data)
        p = self.buffer.find('\x00')
        #print("RCV DATA", len(data), len(self.buffer), self.buf_sum)
        if p > 0:
            file_len = int(self.buffer[:p])
            #print("FILE LEN", file_len)
            buf_len = p + file_len + 1
            if len(self.buffer) == buf_len:
                self.file_out.write(self.buffer[p+1:])
                self.file_out.close()
                self.file_received = True
                #print("File Received")

class MessageArchiver(object):
    def __init__(self):
        self.archive_buffer = []
        self.archive_size = 0
        self.archive_file = None

    def Open(self, MissionName):
        fp = MissionName + 'nav'
        self.archive_file = open(fp, 'w')
        self.archive_buffer = []
        self.archive_size = 0

    def Close(self):
        if self.archive_file is None:
            return
        self.WriteBuffer()
        self.archive_file.close()
        self.archive_file = None

    def Archive(self, mid, ptime, payload):
        # message id, server publish time, json string payload
        if self.archive_file is None:
            return
        self.archive_buffer.append("{}\x00{}\x00{}\x01".format(mid, ptime, payload))
        self.archive_size += len(payload)
        if self.archive_size >= 4096:
            self.WriteBuffer()

    def WriteBuffer(self):
        if len(self.archive_buffer) < 1:
            return
        self.archive_file.write(u"".join(self.archive_buffer))
        self.archive_buffer = []
        self.archive_size = 0

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
class FastMqttServer(SocketWrapperServer):
    def __init__(self, Verbose=False):
        super().__init__(IniSection="MqttFastServer", Port=FAST_MQTT_PORT, Verbose=Verbose)
        self.mqttPayloads = {}
        self.subscriptions = {}
        self.message_in_ct = 0
        self.message_out_ct = 0
        self.archiver = MessageArchiver()

    def ProcessMessage(self, s, message):
        if message[0] == '':
            return
        action = message[0]
        if action == 'publish':
            self.message_in_ct += 1
            server_time = time.time()
            topic = message[1]
            payload = message[2]
            self.mqttPayloads[topic] = (self.message_in_ct, payload)
            if self.verbose:
                print("PUBLISH", topic, self.subscriptions)
            if topic in self.subscriptions:
                newSubscriptionList = []
                for sendSocket in self.subscriptions[topic]:
                    if sendSocket in self.inputSockets:
                        # we get here for subscription by still-connected sockets
                        newSubscriptionList.append(sendSocket)
                        self.QueueMessageZ(['message', topic, `self.message_in_ct`, payload], s=sendSocket)
                        print("PUBLISH", topic, "Queued")
                    else:
                        print("PUBLISH", topic, "Socket unknown")
                self.subscriptions[topic] = newSubscriptionList		# scrubbed of closed connections
            else:
                print("PUBLISH", topic, "No Subscribers")
            if topic == vconst.mission_begin_topic:
                payload_dict = json.loads(payload)
                mode = payload_dict['mode']
                mission_name = payload_dict['mission_name']
                self.archiver.Open(mission_name)
            if topic == vconst.mission_end_topic:
                self.archiver.Close()
            self.archiver.Archive(self.message_in_ct, server_time, payload)
        elif action == 'read':
            topic = message[1]
            if topic in self.mqttPayloads:
                (mid, payload) = self.mqttPayloads[topic]
            else:
                mid = 0
                payload = '{}'
            self.QueueMessageZ(['message', topic, `mid`, payload], s=s)
            print("READ", topic)
        elif action == 'subscribe':
            topic = message[1]
            if topic in self.subscriptions:
                if s not in self.subscriptions[topic]:
                    self.subscriptions[topic].append(s)
            else:
                self.subscriptions[topic] = [s]
            print("SUBSCRIPTIONS", topic, len(self.subscriptions[topic]))

class FastMqttClient(SocketWrapperClient):
    # Many of these function names are lower case to be consistent with paho.mqtt.client.
    def __init__(self, Verbose=False):
        super().__init__(IniSection="MqttBroker", Verbose=Verbose)
        self.on_message = None
        self.on_connect = None

    def connect(self, **kwargs):
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

    def subscribe(self, topic, qos, timeout=1.0):
        packet_sent = False
        start_time = time.time()
        while not packet_sent:
            try:
                print("SUBSCRIBE", topic)
                self.QueueMessageZ(['subscribe', topic])
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
    # This object reconiles any unavoidable differences so mqtt_node works
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
def LaunchNode(node_class):
    n = node_class()
    n.Loop()

class mqtt_node(object):
    __slots__ = ('args', 'automatically_connect', 'block_if_not_connected', 'broker_timeout', 'broker_type',
					'config', 'debug', 'exception_ct', 'exception_last_time',
					'handlers', 'imageDir', 'lastSocketError', 'loop_sleep', 'pendingReads', 'arrivedReads',
					'readers', 'select_timeout', 'single_threaded', 'node_name', 'stats', 'streamer', 'subscriptions',
					'verbose', 'vnavs_mid', 'vnavs_pid', 'wildcard_handler')
    def __init__(self, node_name=None, Subscriptions=[], Readers=[],
				AutomaticallyConnect=True, BlockIfNotConnected=True, SingleThreaded=False, SelectTimeoutSecs=1.0, BrokerType='M', Streamer=False, Verbose=True):
        # AutomaticallyConnect is for nodes that don't want automatic connection managment. Such as darkroom which may run stand-alone or
        #	switch between cameras / bots manually.
        # BlockIfNotConnected is for nodes that only need to run when connected to a message server. DoLoop() is what is blocked.
        #	If set to false, the node to code around communications activities.
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
        self.readers = Readers
        self.subscriptions = Subscriptions
        self.handlers = {}
        self.wildcardHandler = None
        self.broker_type = BrokerType
        self.InitMqttClient()
        self.broker_timeout = 60
        self.debug = 0
        self.exception_last_time = 0
        self.exception_ct = 0
        self.loop_sleep = 0			# set if we don't want to slow loop frequency
        self.lastSocketError = None
        self.pendingReads = {}
        self.arrivedReads = {}
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
            self.mqttc.connect(host=self.socket_host, port=self.socket_port)
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

    def RegisterMessageHandlers(self):
        self.handlers = {}
        self.wildcardHandler = getattr(self, wildcard_method_name, None)
        topics = self.subscriptions + self.readers
        for this_topic in topics:
            handler_name = handler_method_prefix + this_topic.replace('/', '_')
            handler_method = getattr(self, handler_name, None)
            if handler_method is None:
                if self.wildcardHandler is None:
                    print("No message handler for topic '%s'" % (this_topic))
            self.handlers[this_topic] = handler_method
            if this_topic in self.subscriptions:
                self.mqttc.subscribe(this_topic, 0)

    def Get(self, topic, timeout=1.0):
        # Get the most recent message without repeats and automatically request more.
        # Expect frequent None
        if not self.mqttc.connected:
            # for now, silently ignore publish errors. Need to do better
            return
        if topic in self.arrivedReads:
            payload = self.arrivedReads[topic]
            del self.arrivedReads[topic]
            return payload
        self.Read(topic)
        return None

    def Read(self, topic, timeout=1.0):
        if not self.mqttc.connected:
            # for now, silently ignore publish errors. Need to do better
            return
        # maybe check if its in subscription / reader list
        if topic in self.pendingReads:
            t = self.pendingReads[topic]
            if (time.time() - t) < timeout:
                return					# read still reasonably pending
            print("TIMEOUT", topic)
        self.mqttc.read(topic)
        # error messages ???
        self.pendingReads[topic] = time.time()

    def Publish(self, topic, payload, Ack_Topic=None):
        # payload is a dict to be converted to JSON)
        if not self.mqttc.connected:
            # for now, silently ignore publish errors. Need to do better
            return
        payload['_topic'] = topic
        payload['_sender'] = self.node_name
        payload['_sendTime'] = time.time()
        payload['_sendPid'] = self.vnavs_pid
        if Ack_Topic is not None:
            payload['_ack'] = Ack_Topic
        self.vnavs_mid += 1
        payload['_sendSeq'] = self.vnavs_mid
        res, mid = self.mqttc.publish(topic, json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def PrepareResponse(self, payload):
        # Prepares payload to be used as a response.
        # Copy identifier fields so recipients can match source message
        # so it knows request is completed and where to continue its process.
        # Info about original message is always there thanks to Publish()
        sourceTopic = payload['_topic']
        sourceSender = payload['_sender']
        payload['_ackSourceTopic'] = sourceTopic
        payload['_ackSourceSender'] = sourceSender
        if '_sendPid' in payload:
            payload['_ackPid'] = payload['_sendPid']
        if '_sendSeq' in payload:
            payload['_ackSeq'] = payload['_sendSeq']

    def PublishAck(self, payload, error=None):
        self.PrepareResponse(payload)
        if '_sender' not in payload:
            print("SENDER", payload)
        sender = payload['_sender']
        if not ('_ack' in payload):
            # ack was not requested, so only send if there was an error
            if error is None:
                return
            payload['_ackStatus'] = error
            self.Publish(vconst.system_message_error_topic, payload)
            return
        # An ack was requested
        topic = payload['_ack']
        if error is None:
            error = 'ack'
        payload['_ackStatus'] = error
        del payload['_ack']				# ack not needed, avoids ack-ing ack loops
        self.Publish(topic, payload)

    def on_connect(self, client, userdata, flags, rc):
        print("on_connect() rc: " + str(rc))
        self.RegisterMessageHandlers()

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
        handler_method = self.handlers[message.topic]
        #
        if message.topic in self.pendingReads:
            del self.pendingReads[message.topic]
            self.arrivedReads[message.topic] = payload
            return
        if handler_method is None:
            if self.wildcardHandler is not None:
                error = self.wildcardHandler(message.topic, payload)
            else:
                error = ' no handler for topic'
        else:
            error = handler_method(payload)
        # Acks get sent automagically as needed.
        # Only a small percentage of messages get ack-ed, based on
        # the state of error and the _ack payload property.
        self.PublishAck(payload, error=error)

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
    elif sys.argv[1] == 'f':
        s = FileServer(Verbose=verbose)
        s.Serve()
    elif sys.argv[1] == 'm':
        s = FastMqttServer(Verbose=verbose)
        s.Serve()
    elif sys.argv[1] == 'fpub':
        s = FastMqttUtil()
        s.Connect()
        time.sleep(1)
        s.mqttc.publish(sys.argv[2], sys.argv[3])
        time.sleep(1)
