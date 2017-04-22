from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

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

SEND_POSITION_PERIOD = 0.05
SEND_POSITION_PERIOD = 0.1			# sense has is far noisier at high read rates
SEND_POSITION_PERIOD = 0.3			# sense has is far noisier at high read rates
SEND_POSITION_PERIOD = 0.05
METERS_PER_SECOND_PER_KNOT = 0.514444

class engineer_1(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=[], Blocking=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.imageDir = self.config.get("Cameraman", "ImageDir")
        self.speed = 0
        self.heading = 0
        self.longitude = 0
        self.latitude = 0
        self.goal_longitude = None
        self.goal_latitude = None
        self.goal_run = False
        self.gps_buffer = ''			# read buffer
        self.gps_buffer_next = -1		# index of first <cr><lf>
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
					timeout=SEND_POSITION_PERIOD / 10
					)
        self.sense = SenseHat()
        self.sense.set_imu_config(False, True, False)
        self.last_position_message_time = time.time()

    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which handles exceptions and propper shutdown.
        #
        if self.gps_buffer_next >= 0:
            pass				# process buffered sentence, don't read, risking timeout period
        else:
            self.gps_buffer += self.gps_port.read(size=1024)
            self.gps_buffer_next = self.gps_buffer.find('\r\n')
        if self.gps_buffer_next < 0:
            gps_sentence = None
            gps_parsed = None
        else:
            gps_sentence = self.gps_buffer[:self.gps_buffer_next+2]
            self.gps_buffer = self.gps_buffer[self.gps_buffer_next+2:]
            self.gps_buffer_next = self.gps_buffer.find('\r\n')
            try:
                gps_parsed = pynmea2.parse(gps_sentence)
            except pynmea2.ParseError:
                print("PARSE ERROR")
                gps_parsed = None
        if gps_parsed is not None:
            if gps_parsed.sentence_type == 'GSA':
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
                print("RMC %s %s %s %4.7f %s %s %4.7f Hdg %4.2f" % (
					self.gps_status, gps_parsed.data[2], gps_parsed.data[3], self.latitude, 
					gps_parsed.data[4], gps_parsed.data[5], self.longitude,
					self.heading))
                if self.goal_run:
                    self.PathToGoal(gps_parsed)
        if self.newData:
            # we have new GPS Data
            #print(self.speed, self.longitude, self.latitude)
            self.orientation = self.sense.get_orientation_degrees()
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
            self.Publish('gps', payload)
            self.stats.Count('GpsMsg')
            self.newData = False
            self.last_position_message_time = time.time()
        elif (time.time() - self.last_position_message_time) > SEND_POSITION_PERIOD:
            # send only IMU Data if not GPS updates available
            self.orientation = self.sense.get_orientation_degrees()
            payload = {}
            payload['yaw'] = self.orientation['yaw']
            self.Publish('imu', payload)
            self.last_position_message_time = time.time()
            self.stats.Count('ImuMsg')
        self.stats.Print('MSGS')

def TestImu():
    sense = SenseHat()
    p = sense.get_orientation_degrees()
    while True:
        o = sense.get_orientation_degrees()
        print("IMU P: {:+09.4f}  R: {:+09.4f}  Y: {:+09.4f} {:+09.4f}".format(o['pitch'], o['roll'], o['yaw'], p['yaw']-o['yaw']))
        p = o
        time.sleep(0.1)

def RunNode():
    h = engineer_1()
    h.Loop()
    h.Disconnect()

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        RunNode()
    elif sys.argv[1] == 'testimu':
        TestImu()
