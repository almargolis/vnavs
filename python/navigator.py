from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import json
import math
import os
from geopy.distance import great_circle
import sys
import time

import vnavs_mqtt
import paho.mqtt.client as mqtt


class navigator(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=['navigator/mode', 'navigator/waypoint', 'engineer_1/status'], Blocking=False, Streamer=False, Verbose=Verbose)
        self.imageDir = self.config.get("Cameraman", "ImageDir")
        self.waypoints = []
        self.waypointIx = 0
        self.longitude = 0
        self.speed = None
        self.heading = None
        self.latitude = 0
        self.mode = 'M'			# M=manual, P=paused, C=Cones, G=GPS, (R=resume)
        self.pausedMode = None

    def HeadingToWaypoint(self, ix):
        # should be reworked using GeographicLib ??
        # Longitude are lines drawn between poles. +/- 180 degrees from Prime Meridian (Greenwich England)
        # delta Longitude is deltaX.
        # Latotude are lines drawn ~ perpendicular to longitude. Equator is 0 degrees, poles are +/- 90 degrees.
        # delta Latitude is deltaY.
        # geopy coordinates are (latitude, longitude) or (y, x)
        w = self.waypoints[ix]
        waypointLatitude = w[0]
        waypointLongitude = w[1]
        deltaY = great_circle((self.latitude, self.longitude), (w[0], self.longitude)).meters
        deltaX = great_circle((self.latitude, self.longitude), (self.latitude, w[1])).meters
        hypotenuse = great_circle((self.latitude, self.longitude), w).meters
        if deltaY < 0.00001:		# about 1 meter
            waypointHeading = 90
        else:
            tan = deltaX / deltaY
            atan = math.atan(tan)
            waypointHeading = math.degrees(atan)
            ##print("tan=%f, WH=%f" % (tan, waypointHeading))
        if self.latitude > waypointLatitude:
            deltaY = -deltaY
        if self.longitude > waypointLongitude:
            deltaX = -deltaX
            if deltaY >= 0:
                waypointHeading = 360 - waypointHeading		# quadrant IV
            else:
                waypointHeading = 180 + waypointHeading		# quadrant III
        else:
            if deltaY >= 0:
                pass						# quadrant I
            else:
                waypointHeading = 180 - waypointHeading		# quadrant II
        deltaH = waypointHeading - self.heading
        if abs(deltaH) < 3:
            steering = "AWS"
        else:
            if abs(deltaH) < 45:
                turnRadius = "1"
            else:
                turnRadius = "2"
            if deltaH < 0:
                steering = "RR-" + turnRadius
            else:
                steering = "RR" + turnRadius
            payload = {}
            payload['heading'] = steering
            self.mqttc.publish('helmsman/orders', json.dumps(payload))
        print("Path %4s dX %+03.4f dY %+03.4f dH %+03.4f H %+03.4f %2d" % (steering, deltaX, deltaY, deltaH, self.heading, self.waypointIx))
        return hypotenuse

    def rmsg_navigator_mode(self, msg):
        payload = json.loads(msg)
        mode = payload['mode']
        if mode == 'R':
            if self.pausedMode is not None:
                self.mode = self.pausedMode
                self.pausedMode = None
        elif mode == 'P':
            if self.mode in 'GC':
                self.pausedMode = self.mode
                self.mode = mode
        elif mode in 'MCG':
            self.mode = mode
            self.pausedMode = None
            self.waypointIx = 0

    def rmsg_navigator_waypoint(self, msg):
        payload = json.loads(msg)
        request = payload['request']
        if request == 'C':
            self.waypoints = []
            self.waypointIx = 0
        elif request == 'M':
            # check if not None and not same
            self.waypoints.append((self.latitude, self.longitude))
        print(self.waypoints)

    def rmsg_engineer_1_status(self, msg):
        try:
            payload = json.loads(msg)
        except ValueError:
            payload = {}
            print("JSON Error")
        self.longitude = payload['longitude']
        self.latitude = payload['latitude']
        self.speed = payload['speed']
        self.heading = payload['heading']

    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which hands exceptions and propper shutdown.
        #
        #print("LOOP")
        if (self.mode == 'G') and (len(self.waypoints) > 0):
            distance = self.HeadingToWaypoint(self.waypointIx)
            if distance < 1:
                self.waypointIx += 1
                if self.waypointIx >= len(self.waypoints):
                    self.waypointIx = 0
            
def TestNav():
    h = navigator()
    h.latitude = 37.6272
    h.longitude = -122.4540
    h.waypoints = [
			(37.6272, -122.4541),		# about 10 meters west (270 deg)
			(37.6276, -122.4522)		# about 30 meters north (0 deg)
		]
    headings = [237.39, 339.99]
    for ix in range(0, len(h.waypoints)):
        h.heading = headings[ix]
        h.HeadingToWaypoint(ix)
        h.latitude = h.waypoints[ix][0]
        h.longitude = h.waypoints[ix][1]

def TestNav2():
    h = navigator()
    h.latitude = 0
    h.longitude = 0					# start at Prime Meridian @ Equator
    h.waypoints = [
			(1, 0),				# north one latitude, heading 0
			(1, 1),				# east 1 longitude, heading 90
			(0, 1),				# south one latitude, heading 180
			(0, 0),				# west one longitude, heading 270
			(3, 1),				# north three, east one, heading 18.4349, qudrant I
			(4, 4),				# north one, east three, heading 71.5650, quadrant I
			(3, 7),				# south one, east three, heading 108.4349, quadrant II
			(0, 8),				# south three, east one, heading 161,5650, quadrant II
			(-3, 7),			# south three, west one, heading 198.4349, quadrant III
			(-4, 4),			# south one, west three, heading 251.5650, quadrant III
			(-3, 1),			# north one, west three, heading 288.4349, quadrant IV
			(0, 0)				# north three, west one, heading 341.5650, quadrant IV
		]
    headings = [0, 90, 180, 270, 
		18.4349, 71.5650, 108.4349, 161.5650,
		198.4349, 251.5650, 288.4349, 341.5650
		]
    for ix in range(0, len(h.waypoints)):
        h.heading = headings[ix]
        h.HeadingToWaypoint(ix)
        h.latitude = h.waypoints[ix][0]
        h.longitude = h.waypoints[ix][1]


def Run():
    h = navigator()
    h.Connect()
    h.Loop()
    h.Disconnect()

if __name__ == '__main__':
    #TestNav2()
    Run()
