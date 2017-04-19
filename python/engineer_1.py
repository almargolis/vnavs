from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import json
import os
from geopy.distance import great_circle
import pynmea2
import serial
import sys
import time

from sense_hat import SenseHat
#import sense_hat.sense_hat
#import SenseHat


import vnavs_mqtt
import paho.mqtt.client as mqtt

METERS_PER_SECOND_PER_KNOT = 0.514444

class engineer_1(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=['engineer_1/goal', 'engineer_1/start', 'engineer_1/stop'], Blocking=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.imageDir = self.config.get("Cameraman", "ImageDir")
        self.speed = 0
        self.heading = 0
        self.longitude = 0
        self.latitude = 0
        self.goal_longitude = None
        self.goal_latitude = None
        self.goal_run = False
        self.gps_quality = 'F'			# A=good, F=bad
        self.gps_status = 'X'			# A=valid, V=invalid
        self.gps_mode = 'X'			# A=autonomous, D=differeential GPS
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
        self.sense = SenseHat()
        self.sense.set_imu_config(False, True, False)

    def GetGpsData(self, gps_parsed, key):
        for ix, this_field in enumerate(gps_parsed.fields):
            if this_field[0] == key:
                return gps_parsed.data[ix]
        return None
 
    def PathToGoal(self, p):
        # should be reworked using GeographicLib
        hypotenuse = great_circle((self.latitude, self.longitude), (self.goal_latitude, self.goal_longitude)).meters
        deltaY = great_circle((self.latitude, self.longitude), (self.goal_latitude, self.longitude)).meters
        if self.latitude > self.goal_latitude:
            deltaY = -deltaY
        deltaX = great_circle((self.latitude, self.longitude), (self.latitude, self.goal_longitude)).meters
        if self.longitude > self.goal_longitude:
            deltaX = -deltaX
        if deltaX != 0:
            slope = deltaY / deltaX
        else:
            slope = 999
        if abs(slope) > 3:
            heading = "AWS"
        else:
            if slope < 0:
                heading = "R-2"
            else:
                heading = "R-2"
        print("Path %4s %3.4f %3.4f %3.4f %3.4f %s %s %s" % (heading, deltaX, deltaY, slope, hypotenuse, p.data[6], p.data[7], p.data[11]))

    def rmsg_engineer_1_start(self, msg):
        self.goal_run = True

    def rmsg_engineer_1_stop(self, msg):
        self.goal_run = False

    def rmsg_engineer_1_goal(self, msg):
        self.goal_longitude = self.longitude
        self.goal_latitude = self.latitude
        self.goal_run = True
        return
        try:
            orders = json.loads(msg)
        except ValueError:
            orders = {}
            print("JSON Error")
        if 'speed' in orders:
            print("SPEED", orders['speed'])
            self.GetGoalSpeed(orders['speed'])

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
                    pass
                    #self.speed = new_speed
                    #self.newData = True
                else:
                    print(gps_sentence)
            #elif gps_parsed.sentence_type == 'GGA':
            #    self.longitude = gps_parsed.longitude
            #    self.latitude = gps_parsed.latitude
            #    self.newData = True
            elif gps_parsed.sentence_type == 'GSA':
                # This might help determine if readings are meaningful
                # https://en.wikipedia.org/wiki/Dilution_of_precision_(navigation)
                # wikipedia numbers seem off. Indoors getting garbage with numbers just over 1.5
                # need to consider mode (prefer D), number ot satelites and dilution.
                # Outdoors, maybe only when moving, some of the dilution numbers dropped below 1.
                cksum_mark = gps_sentence.rfind('*')
                gps_data = gps_sentence[:cksum_mark].split(',')
                satCt = 0
                for ix in range(3,15):
                    if gps_data[ix] != '':
                        satCt += 1
                posDOP = gps_data[15]
                horzDOP = gps_data[16]
                vertDOP = gps_data[17]
                if (posDOP < 1) or (horzDOP < 1.0) or (vertDOP < 1.0):
                    self.gps_quality = 'A'
                else:
                    self.gps_quality = 'F'
                        
            elif gps_parsed.sentence_type == 'RMC':
                self.longitude = gps_parsed.longitude
                self.latitude = gps_parsed.latitude
                try:
                    self.timestamp = gps_parsed.datetime
                except:
                    # this sometimes fails. Maybe just indoors.
                    self.timestamp = None
                self.gps_status = gps_parsed.data[1]	# A=valid, V=invalid
                speedRaw = gps_parsed.data[6].strip()
                try:
                    speedKnots = float(speedRaw)
                    self.speed = speedKnots * METERS_PER_SECOND_PER_KNOT
                except ValueError:
                    print("Invalid RMC speed", `speedRaw`)
                heading_raw = gps_parsed.data[7].strip()
                if heading_raw == '':
                    pass				# None? only saw it at startup now
                else:
                    try:
                        self.heading = float(heading_raw)	# degrees clockwise from North
                    except ValueError:
                        print("Invalid RMC heading", `heading_raw`)
                self.gps_mode = gps_parsed.data[11]	# A=autonomous, D=differeential GPS
                self.newData = True
                print("RMC", self.gps_status, gps_parsed.data[2], gps_parsed.data[3], self.latitude, gps_parsed.data[4], gps_parsed.data[5], self.longitude)
                if self.goal_run:
                    self.PathToGoal(gps_parsed)
        self.orientation = self.sense.get_orientation_degrees()
        if self.newData:
            #print(self.speed, self.longitude, self.latitude)
            payload = {}
            payload['pitch'] = self.orientation['pitch']
            payload['roll'] = self.orientation['roll']
            payload['yaw'] = self.orientation['yaw']
            payload['speed'] = self.speed
            payload['heading'] = self.heading
            payload['quality'] = self.gps_quality
            payload['longitude'] = self.longitude
            payload['latitude'] = self.latitude
            #payload['gps_time'] = `self.timestamp`
            self.mqttc.publish('engineer_1/status', json.dumps(payload))
            self.newData = False

if __name__ == '__main__':
    h = engineer_1()
    h.Loop()
    h.Disconnect()

