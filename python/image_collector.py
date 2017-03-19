from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)


import json
import os
import socket
import sys
import time

import vnavs_mqtt
import paho.mqtt.client as mqtt

class archiver(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=True):
        super().__init__(Subscriptions=[], Blocking=False, Verbose=Verbose)
        self.my_ip = "192.168.8.11"
        self.my_socket = 3050
        self.xsocket = socket.socket()
        self.xsocket.bind((self.my_ip, self.my_socket))
        self.xsocket.listen(10)
        self.image_ct = 0

    def Loop(self):
        timer_ct = 0
        timer_start = time.clock()
        while True:
            sc, address = self.xsocket.accept()
            self.ArchiveOneFile(sc, address)
            timer_ct += 1
            if timer_ct >= 10:
                timer_stop = time.clock()
                print("Received %d in %f seconds" % (timer_ct, timer_stop - timer_start))
                timer_ct = 0
                timer_start = timer_stop
        self.xsocket.close()

    def ArchiveOneFile(self, sc, address):
        self.image_ct += 1
        image_sz = 0
        json_str = ''
        json_rdy = False
        socket_data = sc.recv(1024)
        while (socket_data):
            if json_rdy:
                # we are past the json packet, write the image file
                img_ix = 0
            else:
                # collect the json packet
                ix = socket_data.find(chr(26))
                if ix >= 0:
                    # this is the end of the json packet
                    json_str += socket_data[:ix]
                    img_ix = ix + 1
                    json_rdy = True
                    parms = json.loads(json_str)
                    filename = parms['filename']
                    filepath = os.path.join('temp', filename)
                    f = open(filepath,'wb')
                else:
                    # this is an intermediate part of the json packet
                    json_str += socket_data
            if json_rdy:
                image_sz += len(socket_data) - img_ix
                f.write(socket_data[img_ix:])
            socket_data = sc.recv(1024)
        f.close()
        sc.close()
        (res, mid) = self.mqttc.publish('archiver/pic_ready', json.dumps(parms))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")
        print(image_sz, filepath, json_str)


if __name__ == '__main__':
    h = archiver()
    h.Connect()
    h.Loop()
    h.Disconnect()

