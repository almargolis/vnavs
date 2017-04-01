from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import json
import numpy
import os
import pynmea2
import serial
import sys
import time

import vnavs_mqtt
import paho.mqtt.client as mqtt

class engineer_1(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=True):
        super().__init__(Subscriptions=[], Blocking=False, Streamer=False, Verbose=Verbose)
        self.imageDir = self.config.get("Cameraman", "ImageDir")
        self.speed = 0
        self.longitude = 0
        self.latitude = 0
        self.timestamp = 0
        self.newData = False
        self.gps_port= serial.Serial(
					port = '/dev/ttyAMA0',
					baudrate = 9600,
					parity = serial.PARITY_NONE,
					stopbits = serial.STOPBITS_ONE,
					bytesize = serial.EIGHTBITS,
					timeout=1
					)

    def GetGpsData(self, gps_parsed, key):
        for ix, this_field in enumerate(gps_parsed.fields):
            if this_field[0] == key:
                return gps_parsed.data[ix]
        return None
 
    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which hands exceptions and propper shutdown.
        #
        #print("LOOP")
        gps_sentence = self.gps_port.readline()
        try:
            gps_parsed = pynmea2.parse(gps_sentence)
        except pynmea2.ParseError:
            print("PARSE ERROR")
            gps_parsed = None
        if gps_parsed is not None:
            if gps_parsed.sentence_type == 'VTG':
                new_speed = self.GetGpsData(gps_parsed, 'Speed over ground kmph')
                if (new_speed != None) and (new_speed != ''):
                    self.speed = new_speed
                    self.newData = True
                else:
                    print(gps_sentence)
            elif gps_parsed.sentence_type == 'GGA':
                self.longitude = gps_parsed.longitude
                self.latitude = gps_parsed.latitude
                self.newData = True
            elif gps_parsed.sentence_type == 'RMC':
                self.longitude = gps_parsed.longitude
                self.latitude = gps_parsed.latitude
                self.timestamp = gps_parsed.datetime
                self.newData = True
        if self.newData:
            print(self.speed, self.longitude, self.latitude)
            payload = {}
            payload['speed'] = self.speed
            payload['longitude'] = self.longitude
            payload['latitude'] = self.latitude
            payload['gps_time'] = `self.timestamp`
            self.mqttc.publish('engineer_1/status', json.dumps(payload))
            self.newData = False

if __name__ == '__main__':
    h = engineer_1()
    h.Connect()
    h.Loop()
    h.Disconnect()

