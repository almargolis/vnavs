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
        super().__init__(Subscriptions=[], SingleThreaded=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.imageDir = self.config.get("Cameraman", "ImageDir")
        self.heading = 0
        self.longitude = 0
        self.latitude = 0
        self.goal_longitude = None
        self.goal_latitude = None
        self.goal_run = False
        self.gps_buffer = ''			# read buffer
        self.gps_buffer_next = -1		# index of first <cr><lf>
        self.gps_quality = 'F'			# A=good, F=bad
        self.gps_speed = 0
        self.gps_status = 'X'			# A=valid, V=invalid
        self.gps_differential = 'X'		# A=autonomous, D=differeential GPS
        self.gps_mode = '1'			# 1=no fix, 2=2D < 4 satelites, 3=3D >= 4 satelites 
        self.timestamp = 0
        self.newGpsData = False
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
        self.acc_speed_forward = 0
        self.acc_dist_forward = 0
        self.acc_speed_sideways = 0
        self.acc_speed_last_time = None

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
        #
        # Estimate speed using accelerometer
        #
        if self.acc_speed_last_time is None:
            self.acc_speed_last_time = time.time()
        now = time.time()
        acc_interval = now - self.acc_speed_last_time
        self.acc_speed_last_time = now
        if self.gps_speed < 0.03:
            self.acc_speed_forward = 0
            self.acc_speed_sideways = 0
        else:
            accel = self.sense.get_accelerometer_raw()
            self.acc_speed_forward += (accel['x'] * acc_interval)
            self.acc_speed_sideways += (accel['y'] * acc_interval)
        self.acc_dist_forward += self.acc_speed_forward * acc_interval
        #
        if gps_parsed is not None:
            if gps_parsed.sentence_type == 'GSA':
                # This might help determine if readings are meaningful
                # https://en.wikipedia.org/wiki/Dilution_of_precision_(navigation)
                # wikipedia numbers seem off. Indoors getting garbage with numbers just over 1.5
                # need to consider mode (prefer D), number ot satelites and dilution.
                # Outdoors, maybe only when moving, some of the dilution numbers dropped below 1.
                cksum_mark = gps_sentence.rfind('*')
                gps_data = gps_sentence[:cksum_mark].split(',')
                mode1 = gps_data[1]		# A(utomatic) or M(anual 2D/3D - s/b A
                mode2 = gps_data[2]		# 1=no fix, 2=2D < 4 satelites, 3=3D >= 4 satelites 
                satCt = 0
                for ix in range(3,15):
                    if gps_data[ix] != '':
                        satCt += 1
                # DOP: Dilution of Precision < 1.0 is ideal but hard to get
                posDOP = float(gps_data[15])		# position (overall ?)
                horzDOP = float(gps_data[16])		# horizontal
                vertDOP = float(gps_data[17])		# vertical
                if mode2 == '3':
                    if (posDOP < 1.0) or (horzDOP < 1.0) or (vertDOP < 1.0):
                        self.gps_quality = 'A'
                    else:
                        self.gps_quality = 'B'
                elif mode2 == '2':
                    self.gps_quality = 'C'
                else:
                    self.gps_quality = 'F'
                self.gps_mode = mode2
                        
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
                    self.gps_speed = speedKnots * METERS_PER_SECOND_PER_KNOT
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
                self.gps_differential = gps_parsed.data[11]	# A=autonomous, D=differeential GPS
                self.newGpsData = True
                """
                print("RMC %s %s %s %4.7f %s %s %4.7f Hdg %4.2f Quality %s" % (
					self.gps_status, gps_parsed.data[2], gps_parsed.data[3], self.latitude, 
					gps_parsed.data[4], gps_parsed.data[5], self.longitude,
					self.heading, self.gps_quality))
                """
                if self.goal_run:
                    self.PathToGoal(gps_parsed)
        if self.newGpsData or ((time.time() - self.last_position_message_time) > SEND_POSITION_PERIOD):
            # always send accelerometer data
            self.orientation = self.sense.get_orientation_degrees()
            payload = {}
            payload['pitch'] = self.orientation['pitch']
            payload['roll'] = self.orientation['roll']
            payload['yaw'] = self.orientation['yaw']		# s/b ~ gps heading ??
            payload['acc_speed_f'] = self.acc_speed_forward
            payload['acc_speed_s'] = self.acc_speed_sideways
            payload['acc_dist_f'] = self.acc_dist_forward
            payload['acc_interval'] = acc_interval
            if self.newGpsData:
                # we have new GPS Data
                #print(self.gps_speed, self.longitude, self.latitude)
                payload['gps_speed'] = self.gps_speed
                payload['heading'] = self.heading
                payload['quality'] = self.gps_quality
                payload['longitude'] = self.longitude
                payload['latitude'] = self.latitude
                payload['gps_time'] = `self.timestamp`
                payload['gps_mode'] = self.gps_mode
                payload['gps_differential'] = self.gps_differential
                self.newGpsData = False
                topic = 'gps'
            else:
                topic = 'imu'
            self.Publish(topic, payload)
            self.last_position_message_time = time.time()
            self.stats.Count(topic + 'Msg')
            #print("ACCC %+8.4f %+8.4f GPS: %+8.4f" % (self.acc_speed_forward, self.acc_speed_sideways, self.gps_speed))
        self.stats.Print('MSGS')
        print("DIST", self.acc_dist_forward)

def TestImu():
    sense = SenseHat()
    p = sense.get_orientation_degrees()
    while True:
        o = sense.get_orientation_degrees()
        print("IMU P: {:+09.4f}  R: {:+09.4f}  Y: {:+09.4f} {:+09.4f}".format(o['pitch'], o['roll'], o['yaw'], p['yaw']-o['yaw']))
        p = o
        time.sleep(0.1)

def TestSensors():
    sense = SenseHat()
    v = {}
    for s in 'gma':
        for a in 'xyz':
            v[s+a] = [None, None]
    t = time.time()
    prev_time = t
    speed = 0
    max_speed = 0
    #
    while True:
        n = {}
        n['g'] = sense.get_gyroscope_raw()
        n['m'] = sense.get_compass_raw()
        n['a'] = sense.get_accelerometer_raw()
        #
        now = time.time()
        acc_interval = now - prev_time
        prev_time = now
        speed += (n['a']['x'] + 0.062) * acc_interval * 32.0
        if speed > max_speed:
            max_speed = speed
        #
        for s in 'gma':
            d = n[s]
            for a in 'xyz':
                if v[s+a][0] is None:
                    v[s+a][0] = d[a]
                    v[s+a][1] = d[a]
                if d[a] < v[s+a][0]:
                    v[s+a][0] = d[a]
                if d[a] > v[s+a][1]:
                    v[s+a][1] = d[a]
        if (time.time() - t > 5):
            break
    for s in 'gma':
        for a in 'xyz':
            print("%s %s %+8.4f %+8.4f" % (s, a, v[s+a][0], v[s+a][1]))
    print("SPEED", speed, max_speed)
    



def RunNode():
    h = engineer_1()
    h.Loop()
    h.Disconnect()

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        RunNode()
    elif sys.argv[1] == 'testimu':
        TestImu()
    elif sys.argv[1] == 'testsen':
        TestSensors()
