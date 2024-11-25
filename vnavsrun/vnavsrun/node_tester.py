import sys
import time

from vnavslib import vnavs_node as vnode

TEST_TOPIC = "test"


#
# With TestSender and TestReceiver on the same RPI3 and the mosquitto broker
# on a second RPI3 connected via ethernet cable, the sender published
# about 1430 messages / second but the receiver only got about 315 / second.
# -- the reciver got all messages in order so it was constantly falling behind
# -- when the sender terminated, undelivered messages were discarded,
# 	so the reciever never got the last messages. This may be fixable
# 	by configuration, but doesn't matter because the reading is so slow.
#


class TestSender(vnode.VnavsNode):
    def __init__(self, verbose=False):
        super().__init__(
            subscriptions=[],
            wait_if_not_connected=False,
            broker_type="F",
            streamer=False,
            verbose=verbose,
        )
        self.msgCt = 0
        self.startTime = time.time()

    def client_loop_code(self):
        self.msgCt += 1
        self.publish(
            TEST_TOPIC,
            {
                "MessageCt": self.msgCt,
            },
        )
        if (self.msgCt % 100) == 0:
            rate = self.msgCt / (time.time() - self.startTime)
            print(f"published {self.msgCt} @ {rate} msgs/sec")


#
# This is single threaded with select_timeout_secs == None.
# Make sure to set async_delivery=True on subscriptions.
#
class TestReceiverSingleAsync(vnode.VnavsNode):
    def __init__(self, verbose=False):
        super().__init__(
            subscriptions=[
                vnode.Subscription(
                    TEST_TOPIC, handler=self.rmsg_test, async_delivery=True
                )
            ],
            wait_if_not_connected=True,
            broker_type="F",
            single_threaded=True,
            select_timeout_secs=None,
            streamer=False,
            verbose=verbose,
        )
        self.msgCt = 0
        self.startTime = time.time()

    def rmsg_test(self, msg):
        self.msgCt += 1
        if (self.msgCt % 10) == 0:
            in_msg_ct = msg["MessageCt"]
            rate = self.msgCt / (time.time() - self.startTime)
            print(
                f"Received read ct: {self.msgCt}  last msg_ct: {in_msg_ct} rate: {rate} msgs/sec)"
            )


class TestReceiverSingleSynchronous(vnode.VnavsNode):
    def __init__(self, verbose=False):
        super().__init__(
            subscriptions=[
                vnode.Subscription(
                    TEST_TOPIC, handler=self.rmsg_test, async_delivery=False
                )
            ],
            wait_if_not_connected=True,
            broker_type="F",
            single_threaded=True,
            select_timeout_secs=0.01,
            streamer=False,
            verbose=verbose,
        )
        self.msgCt = 0
        self.startTime = time.time()

    def rmsg_test(self, msg):
        self.msgCt += 1
        if (self.msgCt % 10) == 0:
            in_msg_ct = msg["MessageCt"]
            rate = self.msgCt / (time.time() - self.startTime)
            print(
                f"Received read ct: {self.msgCt}  last msg_ct: {in_msg_ct} rate: {rate} msgs/sec)"
            )


class FastMqttUtil(vnode.VnavsNode):
    def __init__(self, verbose=False):
        super().__init__(
            subscriptions=[],
            wait_if_not_connected=True,
            broker_type="F",
            streamer=False,
            verbose=verbose,
        )


if __name__ == "__main__":
    if "verbose" in sys.argv:
        print("verbose")
        verbose = True
    else:
        print("QUIET")
        verbose = False
    if sys.argv[1] == "i":
        find_server(verbose=verbose)
    elif sys.argv[1] == "s":
        n = TestSender()
        n.main_loop()
    elif sys.argv[1] == "rsa":
        n = TestReceiverSingleAsync()
        n.main_loop()
    elif sys.argv[1] == "rss":
        n = TestReceiverSingleSynchronous()
        n.main_loop()
    elif sys.argv[1] == "fpub":
        s = FastMqttUtil()
        s.Connect()
        time.sleep(1)
        s.mqttc.publish(sys.argv[2], sys.argv[3])
        time.sleep(1)
