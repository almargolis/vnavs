import json
import queue
import re
import socket
import threading
import time

import numpy as np

from vnavslib import vnavs_comms


# ---------------------------------------------------------------------------
# SocketWrapper construction (original test, expanded)
# ---------------------------------------------------------------------------


def test_socket():
    sw = vnavs_comms.SocketWrapper()
    assert sw.is_server is False
    assert sw.message_in_ct == 0
    assert sw.message_out_ct == 0
    assert sw.sent_ct == 0
    sw.os_socket.close()


# ---------------------------------------------------------------------------
# host_primary_ip_address()
# ---------------------------------------------------------------------------


def test_host_primary_ip_address_format():
    ip = vnavs_comms.host_primary_ip_address()
    assert re.match(r"\d+\.\d+\.\d+\.\d+$", ip)


# ---------------------------------------------------------------------------
# prepare_message()
# ---------------------------------------------------------------------------


def test_prepare_message_basic_fields():
    payload = {"heading": 90}
    result = vnavs_comms.prepare_message("nav", 1000, 1, "nav/heading", payload)
    parsed = json.loads(result)
    assert parsed["_topic"] == "nav/heading"
    assert parsed["_sender"] == "nav"
    assert parsed["_sendPid"] == 1000
    assert parsed["_sendSeq"] == 1
    assert isinstance(parsed["_sendTime"], float)
    assert parsed["heading"] == 90


def test_prepare_message_without_confirmation():
    payload = {"x": 1}
    result = vnavs_comms.prepare_message("s", 1, 1, "t", payload)
    parsed = json.loads(result)
    assert "_conf_request" not in parsed


def test_prepare_message_with_confirmation():
    payload = {"x": 1}
    result = vnavs_comms.prepare_message("s", 1, 1, "t", payload, conf_request="abc")
    parsed = json.loads(result)
    assert parsed["_conf_request"] == "abc"


def test_prepare_message_numpy_int64():
    payload = {"value": np.int64(42)}
    result = vnavs_comms.prepare_message("s", 1, 1, "t", payload)
    parsed = json.loads(result)
    assert parsed["value"] == 42
    assert isinstance(parsed["value"], int)


# ---------------------------------------------------------------------------
# prepare_response()
# ---------------------------------------------------------------------------


def test_prepare_response_copies_ack_fields():
    source = {
        "_topic": "nav/heading",
        "_sendPid": 1000,
        "_sendSeq": 5,
        "heading": 90,
    }
    resp = vnavs_comms.prepare_response(source)
    assert resp["_ackTopic"] == "nav/heading"
    assert resp["_ackPid"] == 1000
    assert resp["_ackSeq"] == 5
    assert "heading" not in resp


def test_prepare_response_empty_source():
    resp = vnavs_comms.prepare_response({})
    assert resp == {}


def test_prepare_response_with_confirmation():
    source = {"_conf_request": "req123"}
    resp = vnavs_comms.prepare_response(source, conf_request=True)
    assert resp["_isConfirmation"] == "req123"


def test_prepare_response_without_confirmation():
    source = {"_conf_request": "req123"}
    resp = vnavs_comms.prepare_response(source, conf_request=False)
    assert "_isConfirmation" not in resp


# ---------------------------------------------------------------------------
# JsonNumpyEncoder
# ---------------------------------------------------------------------------


def test_numpy_encoder_int64():
    data = {"a": np.int64(7)}
    result = json.dumps(data, cls=vnavs_comms.JsonNumpyEncoder)
    assert json.loads(result) == {"a": 7}


def test_numpy_encoder_regular_types():
    data = {"s": "hello", "n": 3.14, "lst": [1, 2]}
    result = json.dumps(data, cls=vnavs_comms.JsonNumpyEncoder)
    assert json.loads(result) == data


def test_numpy_encoder_unserializable_raises():
    try:
        json.dumps({"bad": {1, 2, 3}}, cls=vnavs_comms.JsonNumpyEncoder)
        assert False, "Should have raised TypeError"
    except TypeError:
        pass


# ---------------------------------------------------------------------------
# QueueOne
# ---------------------------------------------------------------------------


def test_queue_one_put_get():
    q = vnavs_comms.QueueOne()
    q.put("hello")
    assert q.get_nowait() == "hello"


def test_queue_one_empty_raises():
    q = vnavs_comms.QueueOne()
    try:
        q.get_nowait()
        assert False, "Should have raised queue.Empty"
    except queue.Empty:
        pass


def test_queue_one_overwrites():
    q = vnavs_comms.QueueOne()
    q.put("first")
    q.put("second")
    assert q.get_nowait() == "second"


def test_queue_one_get_clears():
    q = vnavs_comms.QueueOne()
    q.put("data")
    q.get_nowait()
    try:
        q.get_nowait()
        assert False, "Should have raised queue.Empty"
    except queue.Empty:
        pass


# ---------------------------------------------------------------------------
# SocketWrapper — process_received_packet()
#
# We subclass to capture calls to process_message(), which SocketWrapper
# expects subclasses to provide.
# ---------------------------------------------------------------------------


class _RecordingSocket(vnavs_comms.SocketWrapper):
    """SocketWrapper subclass that records process_message calls."""

    def __init__(self):
        super().__init__()
        self.received = []

    def process_message(self, s, parts):
        self.received.append(parts)


def test_process_received_packet_single_message():
    sw = _RecordingSocket()
    # "hello\x00world\x01" is one message with two fields
    sw.process_received_packet(sw.os_socket, b"hello\x00world\x01")
    assert len(sw.received) == 1
    assert sw.received[0] == ["hello", "world"]
    sw.os_socket.close()


def test_process_received_packet_multiple_messages():
    sw = _RecordingSocket()
    sw.process_received_packet(sw.os_socket, b"a\x01b\x01")
    assert len(sw.received) == 2
    assert sw.received[0] == ["a"]
    assert sw.received[1] == ["b"]
    sw.os_socket.close()


def test_process_received_packet_fragmented():
    sw = _RecordingSocket()
    # First call: incomplete message
    sw.process_received_packet(sw.os_socket, b"hel")
    assert len(sw.received) == 0
    # Second call: completes the message
    sw.process_received_packet(sw.os_socket, b"lo\x01")
    assert len(sw.received) == 1
    assert sw.received[0] == ["hello"]
    sw.os_socket.close()


def test_process_received_packet_fragment_with_complete():
    sw = _RecordingSocket()
    # One complete message plus the start of another
    sw.process_received_packet(sw.os_socket, b"first\x01sec")
    assert len(sw.received) == 1
    assert sw.received[0] == ["first"]
    # Complete the second message
    sw.process_received_packet(sw.os_socket, b"ond\x01")
    assert len(sw.received) == 2
    assert sw.received[1] == ["second"]
    sw.os_socket.close()


# ---------------------------------------------------------------------------
# SocketWrapper — queue_message_z()
# ---------------------------------------------------------------------------


def test_queue_message_z_encoding():
    sw = vnavs_comms.SocketWrapper()
    sw.queue_message_z(["topic", "payload"])
    msg = sw.output_queues[sw.os_socket].get_nowait()
    assert msg == "topic\x00payload\x00\x01"
    assert sw.message_out_ct == 1
    sw.os_socket.close()


def test_queue_message_z_adds_to_output_sockets():
    sw = vnavs_comms.SocketWrapper()
    assert sw.os_socket not in sw.output_sockets
    sw.queue_message_z(["data"])
    assert sw.os_socket in sw.output_sockets
    sw.os_socket.close()


# ---------------------------------------------------------------------------
# SocketWrapper — close_client_connection()
# ---------------------------------------------------------------------------


def test_close_client_connection_cleanup():
    sw = vnavs_comms.SocketWrapper(is_server=True)
    # Create a dummy client socket
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sw.input_sockets.append(client)
    sw.output_sockets.append(client)
    sw.output_queues[client] = queue.Queue()
    sw.fragments[client] = b"partial"

    sw.close_client_connection(client)
    assert client not in sw.input_sockets
    assert client not in sw.output_sockets
    assert client not in sw.output_queues
    assert client not in sw.fragments
    sw.os_socket.close()


# ---------------------------------------------------------------------------
# SocketWrapperClient — connect timeout
# ---------------------------------------------------------------------------


def test_client_connect_timeout():
    client = vnavs_comms.SocketWrapperClient()
    # Connect to a port that is almost certainly not listening.
    # Use a very short timeout so the test finishes quickly.
    result = client.connect(host="127.0.0.1", port=19999, timeout=0.05)
    assert result is False
    assert client.connected is False
    client.os_socket.close()


# ---------------------------------------------------------------------------
# Integration — server/client round-trip
# ---------------------------------------------------------------------------


class _EchoServer(vnavs_comms.SocketWrapperServer):
    """Server that echoes received messages back to the sender."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.received = []

    def process_message(self, s, parts):
        self.received.append(parts)
        self.queue_message_z(["echo"] + parts, s=s)


class _CollectingClient(vnavs_comms.SocketWrapperClient):
    """Client that collects received messages."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.received = []

    def process_message(self, s, parts):
        self.received.append(parts)


def test_server_client_round_trip():
    port = 14789

    server = _EchoServer(port=port)
    server.os_socket.bind(("127.0.0.1", port))
    server.os_socket.listen(5)

    server_thread = threading.Thread(target=_run_server, args=(server,), daemon=True)
    server_thread.start()

    client = _CollectingClient()
    connected = client.connect(host="127.0.0.1", port=port, timeout=2.0)
    assert connected

    client.queue_message_z(["ping", "123"])

    # Run client select loop to send and receive
    deadline = time.time() + 2.0
    while len(client.received) == 0 and time.time() < deadline:
        client.select(timeout=0.01)

    assert len(client.received) >= 1
    # The zero/one protocol appends \x00 after each field, so split()
    # produces trailing empty strings. Check the meaningful parts.
    parts = [p for p in client.received[0] if p != ""]
    assert parts == ["echo", "ping", "123"]

    client.os_socket.close()
    server._stop_event.set()
    server.os_socket.close()


def _run_server(server):
    while not server._stop_event.is_set():
        try:
            server.select(timeout=0.01)
        except Exception:
            break
