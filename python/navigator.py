from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import cv2
import math
import numpy as np
import os
from geopy.distance import great_circle
import sys
import time

import vnavs_mqtt
import OpticChiasm

WAYPOINT_WINDOW_METERS = 2.0
STEER_STRAIGHT_HEADING = 10.0
STEER_SHARP_HEADING = 90.0
FORWARD_VERY_SLOW = 6
FORWARD_SLOW = 4		# too slow for court (maybe depends on battery)
FORWARD_SLOW = 6		# OK slow for court 
FORWARD_SLOW = 16		# this is what it took to move well on grass at robogames
FORWARD_FAST = 10
FORWARD_FAST = 14
FORWARD_FAST = 8
FORWARD_FAST = 20		# robgames on grass
FORWARD_FAST_METERS = 10
REVERSE_SLOW = -4
STOP_SPEED = 0
STOP_SECONDS = 2
MAX_TIMED_MANUEVER_SECONDS = 10
Y_TURN_LIMIT = 160
INITIAL_GPS_WAIT = 3
OVERSTEER_ADJUSTMENT = 0.5

class Mission(object):
    def __init__(self, MissionDir, MissionName=None):
        self.missionDir = MissionDir
        self.missionName = None
        self.Init(MissionName=MissionName)

    def Init(self, MissionName=None):
        if MissionName is not None:
            # If supplied, this is a permanent change.
            # But keep previous if not specified, this is a reset.
            self.missionName = MissionName
        if self.missionName is None:
            self.missionName = 'test'
        self.waypoints = []
        self.waypointIx = 0
        self.navpoints = []
        self.LoadMission()

    def LoadMission(self, MissionName=None):
        print("LOAD", self.missionDir, self.missionName, MissionName)
        mission_name = self.missionName
        if MissionName is not None:
            mission_name = MissionName
        fp = os.path.join(self.missionDir, mission_name) + '.mis'
        f = open(fp, "r")
        for this in f.readlines():
            parts = this.split(',')
            if parts[0] == 'W':
                self.waypoints.append(('W', (float(parts[1]), float(parts[2]))))
            elif parts[0] == 'M':			# Magic
                    self.waypoints.append(('M', parts[1]))

    def WayPoints(self):
        waypoints = []
        for p in self.waypoints:
            if p[0] == 'W':
                waypoints.append(p[1])
        return waypoints

    def SaveMission(self, MissionName=None):
        mission_name = self.missionName
        if MissionName is not None:
            mission_name = MissionName
        fp = os.path.join(self.missionDir, mission_name) + '.mis'
        f = open(fp, "w")
        for p in self.waypoints:
            f.write(u'W,%f,%f\n' % (p[1][0], p[1][1]))
        f.close

    def SaveNavigation(self, MissionName=None):
        mission_name = self.missionName
        if MissionName is not None:
            mission_name = MissionName
        fp = os.path.join(self.missionDir, mission_name) + '.nav'
        f = open(fp, "w")
        for p in self.waypoints:
            if p[0] == 'W':
                f.write(u'W,%s,%s\n' % (p[1][0], p[1][1]))
            elif p[0] == 'M':
                f.write(u'M,%s\n' % (p[1]))
        for p in self.navpoints:
            f.write(u'N,%f,%f,%s\n' % (p[0][0], p[0][1], p[1]))
        f.close()

class NavStep(object):
    def __init__(self):
        self.Init()

    def Init(self):
        # When we have multiple steps, all the intermediate steps must either have
        # hardKeepSeconds > 0 or untrustedGpsUpdates < 0 with yaw settings to cancel
        # the operation.
        self.steering = 'A0'
        self.speed = 0
        self.startingYaw = None
        self.deltaYawGoal = None
        self.untrustedGpsUpdates = 0
        self.hardKeepSeconds = 0
        self.softKeepSeconds = 0
        self.hardTimeLimit = 0
        self.softTimeLimit = 0

class navigator(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=['navigator/mode', 'navigator/service',
					'engineer_1/gps', 'engineer_1/imu',
					'cameraman/last'
					],
					Readers=[],
					Blocking=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.imageDir = self.config.get("Cameraman", "ImageDir")
        self.missionDir = self.config.get("Pilot", "MissionDir")
        self.longitude = 0
        self.speed = None
        self.heading = None
        self.imageFn = None
        self.imageRequested = None
        self.latitude = 0
        self.pausedMode = None
        self.missionName = None
        self.new_gps_payload = None
        self.new_imu_payload = None
        self.new_mode_payload = None
        self.serviceNames = ['ClearWaypoints', 'MarkWaypoint', 'SaveWaypoints', 'MakeWaypointMap']
        self.serviceRequests = []
        self.gpsReadyForNavigation = False
        #self.gpsRequested = False
        self.Init()

    def Init(self, MissionName=None):
        self.nav = NavStep()
        self.navSteps = []
        self.mode = "M"
        self.mission = Mission(self.missionDir, MissionName=MissionName)

    def NavigateTowardWaypoint(self, ix):
        # should be reworked using GeographicLib ??
        # Longitude are lines drawn between poles. +/- 180 degrees from Prime Meridian (Greenwich England)
        # delta Longitude is deltaX.
        # Latitude are lines drawn ~ perpendicular to longitude. Equator is 0 degrees, poles are +/- 90 degrees.
        # delta Latitude is deltaY.
        # geopy coordinates are (latitude, longitude) or (y, x)
        if self.heading is None:
            # we aren't receiving GPS info. Can't navigate.
            print("NO HEADING - can't navigate.")
            return None
        w = self.mission.waypoints[ix][1]			# Assume this is a navigation waypoint W
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
        deltaHeading = waypointHeading - self.heading
        if deltaHeading < -180:
            deltaHeading = deltaHeading + 360
        elif deltaHeading > 180:
            deltaHeading = deltaHeading - 360
        if abs(deltaHeading) < STEER_STRAIGHT_HEADING:
            self.nav.Init()
            self.nav.steering = "A0"
            if hypotenuse > 10:
                self.nav.speed = FORWARD_FAST
            else:
                self.nav.speed = FORWARD_SLOW
        else:
            # deltaHeading is +/- 180 degrees, map to +/- 60 steering order.
            # this should query the helmsman for this bots range instead of assuming 60.
            # The signs of headings and steering command are the same. Negative means
            # the waypoint is to the left, positive is to the right.
            if abs(deltaHeading) <= Y_TURN_LIMIT:
                # make the direct turn
                self.nav.Init()
                self.nav.steering = 'A' + str(int(deltaHeading / 3))
                if (hypotenuse > 10) and (abs(deltaHeading) < 20):
                    self.nav.speed = FORWARD_FAST
                else:
                    self.nav.speed = FORWARD_SLOW
                if abs(deltaHeading) > 45:
                    pass
                    #self.nav.untrustedGpsUpdates = 1		# give GPS time to settle after tight turn
                self.nav.softKeepSeconds = 2 
                self.nav.speed = FORWARD_SLOW
                self.nav.startingYaw = self.yaw
                self.nav.deltaYawGoal = deltaHeading
            else:
                self.nav.speed = STOP_SPEED
                self.nav.hardKeepSeconds = STOP_SECONDS
                step = NavStep()
                # Note: this steering direction is reversed, but yaw is not.
                step.steering = 'A' + str(int(-deltaHeading / 3))
                step.speed = REVERSE_SLOW
                step.startingYaw = self.yaw
                step.deltaYawGoal = deltaHeading * OVERSTEER_ADJUSTMENT
                step.untrustedGpsUpdates = -1
                self.navSteps = [step]
                #
                step = NavStep()
                step.steering = 'A0'
                step.speed = STOP_SPEED
                step.hardKeepSeconds = STOP_SECONDS
                step.untrustedGpsUpdates = -1
                self.navSteps.append(step)
                #
                step = NavStep()
                step.steering = 'A' + str(int(deltaHeading / 3))
                step.speed = FORWARD_SLOW
                step.startingYaw = self.yaw
                step.deltaYawGoal = deltaHeading * OVERSTEER_ADJUSTMENT
                step.untrustedGpsUpdates = 1
                self.navSteps.append(step)

        self.PublishNavigation()
        self.mission.navpoints.append(((self.latitude, self.longitude), self.nav.steering))
        print("Path (%s, %s) -> %s" % (self.latitude, self.longitude, self.mission.waypoints[self.mission.waypointIx]))
        print("Path %4s dX %+03.4f dY %+03.4f Hyp %+03.2f difHdg %+03.4f GpsHdg %+03.4f HdgToW %03.4f %2d" % (self.nav.steering, deltaX, deltaY, hypotenuse,
					deltaHeading, self.heading, waypointHeading, self.mission.waypointIx))
        return hypotenuse

    def PublishNavigation(self):
        payload = {}
        payload['heading'] = self.nav.steering
        payload['speed'] = self.nav.speed
        payload['timer'] = 6
        self.Publish('orders', payload, source='helmsman')
        if self.nav.untrustedGpsUpdates < 0:
            # this could be dangerous, skipping navigation indefinately
            if self.nav.hardKeepSeconds <= 0:
                # we intend to end the manuever with IMU yaw, this keeps us safe
                self.nav.hardKeepSeconds = MAX_TIMED_MANUEVER_SECONDS
        if self.nav.softKeepSeconds > 0:
            self.nav.softTimeLimit = time.time() + self.nav.softKeepSeconds
        if self.nav.hardKeepSeconds > 0:
            self.nav.hardTimeLimit = time.time() + self.nav.hardKeepSeconds

    def rmsg_cameraman_last(self, payload):
        self.imageFn = payload['filename']
        if self.imageFn == '':
            self.imageFn
        print("LAST", payload)

    def rmsg_navigator_mode(self, payload):
        new_mode = payload['mode']
        if new_mode not in "GMPR":
            return 'invalid mode'
        self.new_mode_payload = payload
        print("MODE_MSG", payload)

    def ChangeMode(self):
        payload = self.new_mode_payload
        self.new_mode_payload = None
        if payload is None:
            return
        mode = payload['mode']
        print("MODE", mode)
        if mode == 'R':
            if self.pausedMode is not None:
                self.mode = self.pausedMode
                self.pausedMode = None
        elif mode == 'P':
            if self.mode in 'GC':
                self.pausedMode = self.mode
                self.mode = mode
        elif mode in 'MG':
            if (mode == "G") and (self.mode != "G"):
                # Start a mission
                mission_name = payload['missionName']
                self.Init(MissionName=mission_name)
                self.nav.steering = 'A0'
                self.nav.speed = FORWARD_SLOW
                if self.mission.waypoints[self.mission.waypointIx][0] == "W":
                    self.nav.untrustedGpsUpdates = INITIAL_GPS_WAIT		# allow gps to settle
                    self.PublishNavigation() 
            print("MISSION", self.mission.waypoints)
            if (mode == "M") and (self.mode == "G"):
                # end of gps naviagion
                self.nav.Init()
                self.PublishNavigation()
                self.mission.SaveNavigation()
            self.mode = mode
            self.pausedMode = None

    def rmsg_navigator_service(self, payload):
        request = payload['request']
        if request not in self.serviceNames:
            return 'unknown service'
        self.serviceRequests.append(payload)

    def ProcessServiceRequest(self):
        if len(self.serviceRequests) < 1:
            return
        payload = self.serviceRequests.pop(0)
        print("PROCESS", payload)
        request = payload['request']
        self.PrepareResponse(payload)
        payload['MissionName'] = self.mission.missionName
        payload['WaypointCt'] = len(self.mission.waypoints)
        if request == 'ClearWaypoints':
            self.mission.Init()
        elif request == 'MarkWaypoint':
            self.mission.waypoints.append(('W', (self.latitude, self.longitude)))
        elif request == 'SaveWaypoints':
            if 'MissionName' in payload:
                mission_name = payload['MissionName']
            else:
                mission_name = None
            self.mission.SaveMission(MissionName=mission_name)
        elif request == 'MakeWaypointMap':
            mission_map = MissionMap(waypoints=self.mission.Waypoints())
            map_fn = 'Map_%s_%s_%s.jpeg' % (payload['_sender'], payload['_sendPid'], payload['_sendSeq'])
            map_fp = os.path.join(self.imageDir, map_fn)
            mission_map.SaveMap(map_fp)
            payload['filename'] = map_fn
            payload['captureFormat'] = 'jpeg'

        self.Publish('status', payload)

    def rmsg_engineer_1_gps(self, payload):
        self.new_gps_payload = payload

    def LoadGpsPayload(self):
        payload = self.new_gps_payload
        if payload is None:
            return False
        self.new_gps_payload = None
        self.longitude = payload['longitude']
        self.latitude = payload['latitude']
        self.speed = payload['speed']
        self.heading = payload['heading']
        self.yaw = payload['yaw']
        #self.gpsRequested = False
        self.gpsReadyForNavigation = True
        self.stats.Count('GpsRcv')
        return True

    def rmsg_engineer_1_imu(self, payload):
        self.new_imu_payload = payload

    def LoadImuPayload(self):
        payload = self.new_imu_payload
        if payload is None:
            return False
        self.new_imu_payload = None
        self.yaw = payload['yaw']
        self.stats.Count('ImuRcv')

    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which handles exceptions and propper shutdown.
        #
        # Handle message data within this thread.
        #
        self.ChangeMode()
        if not self.LoadGpsPayload():
            self.LoadImuPayload()
        # We might not want to ProcessSerivceRequest() here if any of them take much time.
        # Maybe only run when in paused or manual mode.
        self.ProcessServiceRequest()
        #
        if not self.mqttcConnected:
            return
        if (self.mode == 'G') and (len(self.mission.waypoints) > 0) and (self.mission.waypoints[self.mission.waypointIx][0] == "M"):
            #print("MAGIC")
            if self.imageFn is None:
                if (self.imageRequested is None) or ((time.time() - self.imageRequested) > 1.0):
                    print("REQUEST IMAGE")
                    self.Publish('ask_last', {}, source='cameraman')
                    self.imageRequested = time.time()
                return
            fp = os.path.join(self.imageDir, self.imageFn)
            print("image", fp)
            im = cv2.imread(fp)
            if im is None:
                print("IM RETRY")
                time.sleep(0.5)
                im = cv2.imread(fp)
                if im is None:
                    return
            r = OpticChiasm.Robogames(im, [OpticChiasm.HSV_MASK_YELLOW])
            r.ProcessLines()
            r.FilterLines()
            r.SelectLines()
            outFn = 'X' + self.imageFn[1:]
            outFp = os.path.join(self.imageDir, outFn)
            cv2.imwrite(outFp, r.annotated)
            payload = {}
            payload['filename'] = outFn
            self.Publish('pic_ready', payload, source='cameraman')
            if len(r.rectangles) > 0:
                self.nav.speed = FORWARD_VERY_SLOW
            else:
                self.nav.speed = STOP_SPEED
            self.PublishNavigation()
            self.imageFn = None
            self.imageRequested = False
            return
        if (self.nav.hardTimeLimit > 0) or self.gpsReadyForNavigation:
            print("TL {} GPS Rdy: {}".format(self.nav.hardTimeLimit, self.gpsReadyForNavigation))
        if self.nav.hardTimeLimit > 0:
            # if there is a time limit, just follow those orders until they expire.
            # if there is an unexpired time limit, untrustedGpsUpdates is ignored, we don't get that far.
            if  self.nav.hardTimeLimit > time.time():
                # we want to maintain the the current navigation orders until completed by yaw or time
                if not self.CheckYawForCompletedManuever():
                    return				# not ended, continue timed order
            # the current navigation has expired or ended by IMU yaw, deal with it.
            if len(self.navSteps) > 0:
                self.nav = self.navSteps.pop(0)
                self.PublishNavigation()
                return				# new orders came from stack
            self.nav.hardTimeLimit = 0
        check_yaw = True
        if self.gpsReadyForNavigation:
            if self.nav.untrustedGpsUpdates != 0:
                # We are in a manuever where GPS hasn't caught up, like startup or reversing direction.
                # We might be counting down to zero, or might have started negative, in
                # which case we ignore GPS till reset.
                # GPS values ARE being recorded, just not used for navigation.
                self.nav.untrustedGpsUpdates -= 1
                self.gpsReadyForNavigation = False
        if self.gpsReadyForNavigation:
            if (self.mode == 'G') and (len(self.mission.waypoints) > 0):
                print("GPS")
                check_yaw = False
                self.stats.Count('GpsPrc')
                distance = self.NavigateTowardWaypoint(self.mission.waypointIx)
                if distance <= WAYPOINT_WINDOW_METERS:
                    self.mission.waypointIx += 1
                    if self.mission.waypointIx >= len(self.mission.waypoints):
                        self.mission.waypointIx = 0
                    distance = self.NavigateTowardWaypoint(self.mission.waypointIx)		# navigate toward new waypoint immediately
            self.gpsReadyForNavigation = False
        if check_yaw and self.CheckYawForCompletedManuever():
            print("IMU")
            self.nav.Init()
            self.nav.speed = FORWARD_SLOW
            self.PublishNavigation()
        self.stats.Print("MSGS")


    def CheckYawForCompletedManuever(self):
        ## ************** ##
        # Need to track how far we have been moving in same direction. If we overshoot
        # past folding point we get stuck in circle.
        #
        if self.nav.startingYaw is None:
            return False				# there is nothing to complete
        if self.yaw is None:
            return False				# probably an error, no IMU data arriving
        yawDeltaSoFar = self.yaw - self.nav.startingYaw
        print("IMU YAW {:+8.4f} Goal Delta: {:+8.4f} Progress: {:+8.4f}".format(self.yaw, self.nav.deltaYawGoal, yawDeltaSoFar))
        if self.nav.deltaYawGoal < 0:
            # we are turning left. Heading going down in value.
            # Possibly wrapping from 0 to 359
            if self.yaw > self.nav.startingYaw:
                # we have probably wrapped 0/360, but it could be noise or wind
                try:
                    if (self.yaw - self.nav.startingYaw) > 30:
                        # it's a significant difference, not noise
                        yawDeltaSoFar -= 360
                except TypeError:
                    # not sure how this happened!
                    print("TYPE ERROR")
                    pass
            if yawDeltaSoFar <= self.nav.deltaYawGoal:
                # we have gone more negative, further left
                return True				# manuever completed
            else:
                return False			# manuever continuing
        else:
            # we are turning right, Heading going up in value.
            # Possibly wrapping from 359 to 0
            if self.yaw < self.nav.startingYaw:
                if (self.yaw - self.nav.startingYaw) < -30:
                    yawDeltaSoFar += 360
            if yawDeltaSoFar >= self.nav.deltaYawGoal:
                return True				# manuever completed
            else:
                return False			# manuever continuing

class MissionMap(object):
    def __init__(self, waypoints=None, navpoints=None):
        self.waypoints = waypoints
        self.navpoints = navpoints
        self.InitMap()
        self.FindExtentsLatLong()
        self.mapOriginLongitudeX = 0
        self.mapOriginLatitudeY = 0
        self.waypointColor = "red"
        self.waypointColor = (0, 0, 255)		# red BGR
        self.navpointColor = "green"
        self.navpointColor = (0, 255, 0)

    def FindExtentsLatLong(self, waypoints=None, navpoints=None):
        # waypoints are (latitude, longitude) or (y, x)
        if waypoints is not None:
            self.waypoints = waypoints
        if navpoints is not None:
            self.navpoints = navpoints
        print("FORMAT MAP", self.waypoints)
        plot_points = []
        if self.waypoints is not None:
            plot_points = self.waypoints
        if self.navpoints is not None:
            plot_points += self.navpoints
        if len(plot_points) < 2:
            return
        minLongitudeZ = None
        maxLongitudeZ = None
        minLatitudeZ = None
        maxLatitudeZ = None
        for point in plot_points:
            # Offset to 0... so comparison doesn't have to worry about negative values
            x = point[1] + 180.0			# convert to range(0, 360)
            y = point[0] + 90.0				# convert to range(0, 180)
            if minLongitudeZ is None:
                minLatitudeZ = y
                maxLatitudeZ = y
                minLongitudeZ = x
                maxLongitudeZ = x
            else:
                if x < minLongitudeZ:
                    minLongitudeZ = x
                elif x > maxLongitudeZ:
                    maxLongitudeZ = x
                if y < minLatitudeZ:
                    minLatitudeZ = y
                elif y > maxLatitudeZ:
                    maxLatitudeZ = y
        extentWidth = maxLongitudeZ - minLongitudeZ
        if extentWidth <= 0.0:
            extentWidth = 0.0001
        extentHeight = maxLatitudeZ - minLatitudeZ
        if extentHeight <= 0.0:
            extentHeight = 0.0001
        #
        # restore to actual latitude and longitude - True values from Zero
        #
        minLongitudeT = minLongitudeZ - 180.0
        maxLongitudeT = maxLongitudeZ - 180.0
        minLatitudeT = minLatitudeZ - 90.0
        maxLatitudeT = maxLatitudeZ - 90.0
        #
        # Scale dimensions in meters so longest extent fits within margin.
        # Margin allows later feature beyond original extensts to be visible.
        # For original useage, this is to follow a robot which wanders a bit
        # beyond the original waypoints.
        #
        deltaMetersX = great_circle((minLatitudeT, minLongitudeT), (minLatitudeT, maxLongitudeT)).meters
        deltaMetersY = great_circle((minLatitudeT, minLongitudeT), (maxLatitudeT, minLongitudeT)).meters
        if deltaMetersX > deltaMetersY:
            self.mapScalePixelsPerMeter = (self.mapSizePixels - (2 * self.mapMarginPixels)) / deltaMetersX
        else:
            try:
                self.mapScalePixelsPerMeter = (self.mapSizePixels - (2 * self.mapMarginPixels)) / deltaMetersY
            except ZeroDivisionError:
                # this likely means we only have multiple identical waypoints
                self.mapScalePixelsPermeter = 0
                return
        self.mapMetersPerLongitudeX = deltaMetersX / extentWidth
        self.mapMetersPerLatitudeY = deltaMetersY / extentHeight
        print("EXTENT", extentWidth, deltaMetersX, extentHeight, deltaMetersY)
        # The following needs to consider crossing equator, poles, prime meridian, dateline.
        # Right now I don't want to think about it.
        marginMeters = self.mapMarginPixels / self.mapScalePixelsPerMeter
        try:
            marginAdjustmentX = marginMeters / self.mapMetersPerLongitudeX
        except ZeroDivisionError:
            marginAdjustmentX = 0
        self.mapOriginLongitudeX = minLongitudeT - marginAdjustmentX
        try:
            marginAdjustmentY = marginMeters / self.mapMetersPerLatitudeY
        except ZeroDivisionError:
            marginAdjustmentY = 0
        self.mapOriginLatitudeY = minLatitudeT - marginAdjustmentY
        print("SCALE", self.mapScalePixelsPerMeter, self.mapMetersPerLongitudeX, self.mapMetersPerLatitudeY)

    def PlotWaypoints(self):
        for w in self.waypoints:
            self.DrawPointLatLong(w, self.waypointColor)

    def PlotNavpoints(self):
        for w in self.navpoints:
            self.DrawPointLatLong(w, self.navpointColor)

    def InitMap(self):
        self.mapSizePixels = 200
        self.mapMaxPixelsX = self.mapSizePixels - 1
        self.mapMaxPixelsY = self.mapSizePixels - 1
        self.mapMarginPixels = 20
        self.mapScalePixelsPerMeter = 0.0
        self.originOffsetMetersX = 0.0
        self.originOffsetMetersY = 0.0
        self.map = np.zeros((self.mapSizePixels, self.mapSizePixels, 3), np.uint8)
        self.map[:] = (255, 255, 255)

    def SaveMap(self, fp):
        #self.map.save(im_fp)
        cv2.imwrite(fp, self.map)

    def DrawPointLatLong(self, point, color, size=1):
        # point is (latitude, longitude), (y, x) map coordinates
        # The following needs to consider crossing equator, poles, prime meridian, dateline.
        # Right now I don't want to think about it. This should work for North America.
        if (point[1] < self.mapOriginLongitudeX) or (point[0] < self.mapOriginLatitudeY):
            print("Invalid DrawPointLatLong()", point)
            return
        x = (point[1] - self.mapOriginLongitudeX) * self.mapMetersPerLongitudeX
        y =  (point[0] - self.mapOriginLatitudeY) * self.mapMetersPerLatitudeY
        print("DrawPointLatLong() %s -> (%s, %s)" %(point, x, y))
        self.DrawPointMeters((x, y), color, size)

    def DrawPointMeters(self, point, color, size=1):
        # point is (x, y) in meters from some origin.
        # Origin may be off visible map.
        # Origin (0,0) is lower right with increasing values up and right.
        x = int(round((point[0] - self.originOffsetMetersX) * self.mapScalePixelsPerMeter))
        y = self.mapMaxPixelsY - int(round((point[1] - self.originOffsetMetersY) * self.mapScalePixelsPerMeter))
        if (x < 0) or (x > self.mapMaxPixelsX) or (y < 0) or (y > self.mapMaxPixelsY):
            print("Invalid DrawPointMeters() (%d,%d) (%d,%d)." % (point[0], point[1], x, y))
            return
        print("DrawPointMeters() (%d,%d) (%d,%d)." % (point[0], point[1], x, y))
        #self.mapDraw.point((x, y), fill=color)
        #self.mapDraw.ellipse((x-size, y-size, x+size, y+size), fill=color)
        cv2.circle(self.map, (x, y), size, color, -1)

def TestMap():
    waypoints = [
			(37.6272, -122.4541),
			(38.6276, -123.4522)
		]
    m = MissionMap(waypoints)
    m.Save()
            
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
        h.NavigateTowardWaypoint(ix)
        h.latitude = h.waypoints[ix][0]
        h.longitude = h.waypoints[ix][1]

def TestNav2():
    h = navigator()
    h.ConnectWait()
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
        h.NavigateTowardWaypoint(ix)
        h.latitude = h.waypoints[ix][0]
        h.longitude = h.waypoints[ix][1]
        print(h.nav)
        print(h.navSteps)

def TestImuCancel():
    tests = [
        (350, -10, 359, 330, -3)
    ]
    h = navigator()
    for this in tests:
        print("***", this)
        h.nav.startingYaw = this[0]
        h.nav.deltaYawGoal = this[1]
        for yaw in range(this[2], this[3], this[4]):
            if yaw > 360:
                yaw = yaw - 360
            h.yaw = yaw
            if h.CheckYawForCompletedManuever():
                r = "STOP TURNING"
            else:
                r = "CONTINUE"
            print("IMU YAW {:+8.4f} Goal Delta: {:+8.4f} Progress: {}".format(h.yaw, h.nav.deltaYawGoal, r))

def RunMap():
    waypoints = []
    navpoints = []
    f = open('test.nav', 'r')
    for this in f.readlines():
        parts = this.split(',')
        if parts[0] == 'W':
            waypoints.append((float(parts[1]), float(parts[2])))
        elif parts[0] == 'N':
            navpoints.append((float(parts[1]), float(parts[2])))
    m = MissionMap()
    m.FindExtentsLatLong(waypoints=waypoints, navpoints=navpoints)
    m.PlotWaypoints()
    m.PlotNavpoints()
    m.SaveMap('/exports/missions/Runmap.jpeg')

def RunNode():
    h = navigator()
    h.Connect()
    h.Loop()
    h.Disconnect()

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        RunNode()
    elif sys.argv[1] == 'map':
        RunMap()
    elif sys.argv[1] == 'test':
        TestNav2()
    elif sys.argv[1] == 'testimucancel':
        TestImuCancel()
