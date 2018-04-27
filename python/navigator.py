from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

try:
    import numpy as np
    import cv2
    import OpticChiasm
except ImportError:
    cv2 = None
    np = None
    OpticChiasm = None

import json
import math
import os
from geopy.distance import great_circle
import sys
import time

import vnavs_mqtt
import vnavs_const as vconst

WAYPOINT_WINDOW_METERS = 2.0
STEER_STRAIGHT_HEADING = 10.0
STEER_SHARP_HEADING = 90.0
FORWARD_VERY_SLOW = 6
FORWARD_SLOW = 6		# OK slow for court
FORWARD_SLOW = 16		# this is what it took to move well on grass at robogames
FORWARD_SLOW = 4		# too slow for court (maybe depends on battery)
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

def DistanceToWaypoint(position, waypoint):
    waypoint_latitude = waypoint[0]
    waypoint_longitude = waypoint[1]
    position_latitude = position[0]
    position_longitude = position[1]
    deltaY = great_circle((position_latitude, position_longitude), (waypoint_latitude, position_longitude)).meters
    deltaX = great_circle((position_latitude, position_longitude), (position_latitude, waypoint_longitude)).meters
    hypotenuse = great_circle(position, waypoint).meters
    if deltaY < 0.00001:		# about 1 meter
        heading_to_waypoint = 90
    else:
        tan = deltaX / deltaY
        atan = math.atan(tan)
        heading_to_waypoint = math.degrees(atan)
        ##print("tan=%f, WH=%f" % (tan, heading_to_waypoint))
    if position_latitude > waypoint_latitude:
        deltaY = -deltaY
    if position_longitude > waypoint_longitude:
        deltaX = -deltaX
        if deltaY >= 0:
            heading_to_waypoint = 360 - heading_to_waypoint		# quadrant IV
        else:
            heading_to_waypoint = 180 + heading_to_waypoint		# quadrant III
    else:
        if deltaY >= 0:
            pass							# quadrant I
        else:
            heading_to_waypoint = 180 - heading_to_waypoint		# quadrant II
    o = object()
    setattr(o, 'heading_to_waypoint', heading_to_waypoint)
    setattr(o, 'distance_to_waypoint',  hypotenuse)
    return o

class MissionStep(object):
    __slots__ = ('mission', 'nav', 'navigator', 'parms', 'section')
    def __init__(self, mission, section):
        self.mission = mission
        self.nav = NavStep()
        self.navigator = mission.navigator
        self.section = section
        self.parms = {}

    def PublishNavigation(self):
        payload = {}
        payload['heading'] = self.nav.steering
        payload['speed'] = self.nav.speed
        payload['timer'] = 6
        self.navigator.Publish(vconst.helmsman_orders_topic, payload)
        if self.nav.untrustedGpsUpdates < 0:
            # this could be dangerous, skipping navigation indefinately
            if self.nav.hardKeepSeconds <= 0:
                # we intend to end the manuever with IMU yaw, this keeps us safe
                self.nav.hardKeepSeconds = MAX_TIMED_MANUEVER_SECONDS
        if self.nav.softKeepSeconds > 0:
            self.nav.softTimeLimit = time.time() + self.nav.softKeepSeconds
        if self.nav.hardKeepSeconds > 0:
            self.nav.hardTimeLimit = time.time() + self.nav.hardKeepSeconds
        print("PublishNavigation", payload)

class StepGpsWaypoint(MissionStep):
    def __init__(self, mission, section, waypoint):
        super().__init__(mission, section)
        self.waypoint = waypoint		(latitude, longitude)

    def Load(self, parts):
        self.waypoint = (float(parts[1]), float(parts[2]))

    def DoMissionStep(self, nav):
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
                distance = self.NavigateTowardWaypoint(self.mission.mission_step_ix)
                if distance <= WAYPOINT_WINDOW_METERS:
                    self.mission.mission_step_ix += 1
                    if self.mission.mission_step_ix >= len(self.mission.waypoints):
                        self.mission.mission_step_ix = 0
                    distance = self.NavigateTowardWaypoint(self.mission.mission_step_ix)		# navigate toward new waypoint immediately
            self.gpsReadyForNavigation = False
        if check_yaw and self.CheckYawForCompletedManuever():
            print("IMU")
            self.nav.Init()
            self.nav.speed = FORWARD_SLOW
            self.PublishNavigation()

class StepMagic(MissionStep):
    __slots__ = ('last_imageFn', 'movement_started')

    def __init__(self, mission, section):
        super().__init__(mission, section)
        self.last_imageFn = None
        self.movement_started = False

    def DoMissionStep(self):
        if self.navigator.imageFn is None:
            # Don't do anything till navigator gets an image.
            # This is safe at start of mission but dangerous if moving
            return
        if self.last_imageFn is not None:
            if self.last_imageFn == self.navigator.imageFn:
                # No new image / information
                return
        self.last_imageFn = self.navigator.imageFn
        fp = os.path.join(self.navigator.imageDir, self.last_imageFn)
        print("image", fp)
        im = cv2.imread(fp)
        if im is None:
            print("IM RETRY")
            time.sleep(0.5)
            im = cv2.imread(fp)
            if im is None:
                return
        r = OpticChiasm.Robogames(im, [OpticChiasm.HSV_YELLOW])
        r.ProcessLines()
        r.FilterLines()
        r.SelectLines()
        outFn = 'X' + self.last_imageFn[1:]
        outFp = os.path.join(self.navigator.imageDir, outFn)
        cv2.imwrite(outFp, r.annotated)
        payload = {}
        payload['filename'] = outFn
        #self.Publish('pic_ready', payload, source='cameraman')
        if len(r.rectangles) > 0:
            print("move")
            self.nav.speed = FORWARD_VERY_SLOW
            self.PublishNavigation()
            self.movement_started = True
        else:
            if self.movement_started:
                print("BOX GONE")
                self.nav.speed = STOP_SPEED
                self.PublishNavigation()
                return True			# end mission steo
            else:
                print("WAIT")
        return


class StepAccMotion(MissionStep):
    def __init__(self, mission):
        super().__init__(mission)

    def Load(self, parts):
        self.direction = parts[1]
        self.distance = float(parts[2])

    def DoMissionStep(self, nav):
        step = NavStep()
        step.steering = 'A0'
        if self.direction == 'F':
            step.speed = FORWARD_SLOW
            step.dist_max = nav.acc_dist_f + self.distance
        else:
            step.speed = REVERSE_SLOW
            step.dist_min = nav.acc_dist_f - self.distance
        nav.nav = step
        nav.PublishNavigation()
        return True

class StepMessage(MissionStep):
    def __init__(self, mission, section, topic):
        super().__init__(mission, section)
        self.topic = topic

    def DoMissionStep(self):
        print("StepMessage", self.topic, self.parms)
        self.mission.navigator.Publish(self.topic, self.parms)
        return True

class StepSleep(MissionStep):
    def __init__(self, mission, section, interval):
        super().__init__(mission, section)
        self.interval = interval

    def DoMissionStep(self):
        time.sleep(float(self.interval))
        return True


class Mission(object):
    def __init__(self, navigator, payload):
        self.navigator = navigator
        self.missionDir = self.navigator.missionDir
        self.mission_name = payload['mission_name']
        self.mission_script = payload['mission_script'].split('\n')
        self.mission_steps = []
        self.mission_step_ix = 0
        self.running = True
        self.LoadMission()

    def LoadMission(self):
        print("LOAD", self.mission_name)
        section = 'run'
        for this in self.mission_script:
            line = this.strip()
            if line == '':
                continue
            if line[0] == '#':
                continue
            print(line)
            if line[0] == '/':
                step = None
                # This is a new mission command
                parts = line[1:].split(':')
                step_type = parts[0].strip()
                if step_type == 'begin':
                    section = 'begin'
                elif step_type == 'run':
                    section = 'run'
                elif step_type == 'end':
                    section = 'end'
                elif step_type == 'magic':
                    step = StepMagic(self, section)
                elif step_type == 'msg':
                    step = StepMessage(self, section, parts[1].strip())
                elif step_type == 'sleep':
                    step = StepSleep(self, section, parts[1].strip())
                if step is not None:
                    self.mission_steps.append(step)
            else:
                # This is a parameter of the step being loaded
                pos = line.find('=')
                key = line[:pos].strip()
                value = line[pos+1:].strip()
                step.parms[key] = value

    def DoMission(self):
        if not self.running:
            return False
        if self.mission_step_ix >= len(self.mission_steps):
            self.EndMission()
            return False
        step = self.mission_steps[self.mission_step_ix]
        if step.DoMissionStep():
            # The step returns true to indicate that it is done.
            # Otherwise it repeats on the next DoMission().
            self.mission_step_ix += 1
        return True

    def StartWrapup(self):
        # This should insert some steps to (optionally?) halt the vehicle
        # and wait for physical operations to wind down. For now its a
        # hard stop.
        self.EndMission()

    def Waypoints(self):
        waypoints = []
        for s in self.mission_steps:
            if isinstance(s, StepGpsWaypoint):
                waypoints.append(s.waypoint)
        return waypoints

    def EndMission(self):
        # This is a hard stop, closing all operations and data collection.
        self.running = False
        # Putting the camera in idle mode may be redundant but doesn't do any harm.
        # Making sure we are in idle mode helps avoid crashes due to running out of
        # storage.
        # The mission end topic stops logging of data. This should only happen 
        # once per mission from here, but redundant messages should not be harmful.
        payload = {}
        payload['loop_mode'] = 'idle'
        self.navigator.Publish(vconst.cameraman_orders_topic, payload)
        payload = {}
        self.navigator.Publish(vconst.mission_end_topic, payload)

    def SaveWaypoints(self, MissionName=None):
        return
        mission_name = self.missionName
        if MissionName is not None:
            mission_name = MissionName
        fp = os.path.join(self.missionDir, mission_name) + '.mis'
        f = open(fp, "w")
        for p in self.waypoints:
            f.write(u'W,%f,%f\n' % (p[1][0], p[1][1]))
        f.close

    def SaveNavigation(self, MissionName=None):
        return
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
        self.steering = '0'
        self.speed = 0
        self.startingYaw = None
        self.deltaYawGoal = None
        self.dist_max = None
        self.dist_min = None
        self.untrustedGpsUpdates = 0
        self.hardKeepSeconds = 0
        self.softKeepSeconds = 0
        self.hardTimeLimit = 0
        self.softTimeLimit = 0

class navigator(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=[
						'navigator/mode',
						vconst.engineer_1_gps_topic,
						vconst.engineer_1_imu_topic,
						vconst.mission_begin_topic,
						vconst.mission_cancel_topic,
						vconst.mission_end_topic,
						vconst.navigator_service_topic,
						vconst.cameraman_pic_ready_topic
					],
					Readers=[],
					SingleThreaded=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.missionDir = self.config.get("Pilot", "MissionDir")
        self.longitude = 0
        self.gps_speed = None
        self.heading = None
        self.imageFn = None
        self.imageRequested = None
        self.latitude = 0
        self.pausedMode = None
        self.mission = None
        self.new_gps_payload = None
        self.new_imu_payload = None
        self.new_mission_begin_payload = None
        self.new_mission_cancel_payload = None
        self.new_mode_payload = None
        self.serviceNames = ['ClearWaypoints', 'MarkWaypoint', 'SaveWaypoints', 'MakeWaypointMap']
        self.serviceRequests = []
        self.gpsReadyForNavigation = False
        self.persistent_data = None

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
        d = DistanceToWaypoint((self.latitude, self.longitude), w)

        deltaHeading = d.heading_to_waypoint - self.heading
        if deltaHeading < -180:
            deltaHeading = deltaHeading + 360
        elif deltaHeading > 180:
            deltaHeading = deltaHeading - 360
        if abs(deltaHeading) < STEER_STRAIGHT_HEADING:
            self.nav.Init()
            self.nav.steering = "A0"
            if d.distance_to_waypoint > 10:
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
                if (d.distance_to_waypoint > 10) and (abs(deltaHeading) < 20):
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
                step.gps_speed = REVERSE_SLOW
                step.startingYaw = self.yaw
                step.deltaYawGoal = deltaHeading * OVERSTEER_ADJUSTMENT
                step.untrustedGpsUpdates = -1
                self.navSteps = [step]
                #
                step = NavStep()
                step.steering = 'A0'
                step.gps_speed = STOP_SPEED
                step.hardKeepSeconds = STOP_SECONDS
                step.untrustedGpsUpdates = -1
                self.navSteps.append(step)
                #
                step = NavStep()
                step.steering = 'A' + str(int(deltaHeading / 3))
                step.gps_speed = FORWARD_SLOW
                step.startingYaw = self.yaw
                step.deltaYawGoal = deltaHeading * OVERSTEER_ADJUSTMENT
                step.untrustedGpsUpdates = 1
                self.navSteps.append(step)

        self.PublishNavigation()
        self.mission.navpoints.append(((self.latitude, self.longitude), self.nav.steering))
        print("Path (%s, %s) -> %s" % (self.latitude, self.longitude, self.mission.waypoints[self.mission.mission_step_ix]))
        print("Path %4s dX %+03.4f dY %+03.4f Hyp %+03.2f difHdg %+03.4f GpsHdg %+03.4f HdgToW %03.4f %2d" % (self.nav.steering, deltaX, deltaY, d.distance_to_waypoint,
					deltaHeading, self.heading, waypointHeading, self.mission.mission_step_ix))
        return d.distance_to_waypoint

    def DumpPersistentData(self):
        if self.persistent_data is None:
            return					# its was never loaded
        path = os.path.expanduser('~/vnavs.data')
        d = json.dumps(self.persistent_data)
        f = open(path, 'w')
        f.write(d)
        f.close()

    def LoadPersistentData(self):
        if self.persistent_data is not None:
            return					# its already loaded
        path = os.path.expanduser('~/vnavs.data')
        f = open(path, 'r')
        d = f.read()
        f.close()
        self.persistent_data = json.loads(d)


    def rmsg_cameraman_pic_ready(self, payload):
        self.imageFn = payload['filename']
        #print("LAST", payload)

    def rmsg_engineer_1_imu(self, payload):
        self.new_imu_payload = payload

    def rmsg_engineer_1_gps(self, payload):
        self.new_gps_payload = payload

    def rmsg_mission_begin(self, payload):
        self.new_mission_begin_payload = payload

    def rmsg_mission_cancel(self, payload):
        self.new_mission_cancel_payload = payload

    def rmsg_mission_end(self, payload):
        # This message is sent by the mission to let other nodes know that
        # the mission has ended.
        # This should function should verify that we have sent this normally.
        # If we think the mission is still running, we need to do something.
        pass

    def rmsg_data_save(self, payload):
        key = payload['key']
        value = payload['value']
        self.LoadPersistentData()
        self.persistent_data[key] = value
        self.DumpPersistentData()

    def rmsg_navigator_mode(self, payload):
        print("MODE_MSG", payload)
        new_mode = payload['mode']
        if new_mode not in "GMPR":
            return 'invalid mode'
        self.new_mode_payload = payload

    def rmsg_navigator_service(self, payload):
        request = payload['request']
        if request not in self.serviceNames:
            return 'unknown service'
        self.serviceRequests.append(payload)

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
                print("START MISSION")
                mission_name = payload['missionName']
                self.Init(MissionName=mission_name)
                self.mission.StartMission()
                """
                THIS NEEDS to be activated for GPS
                self.nav.steering = 'A0'
                self.nav.speed = FORWARD_SLOW
                if self.mission.waypoints[self.mission.mission_step_ix][0] == "W":
                    self.nav.untrustedGpsUpdates = INITIAL_GPS_WAIT		# allow gps to settle
                    self.PublishNavigation()
                """
            print("MISSION", self.mission.missionName, len(self.mission.mission_steps))
            if (mode == "M") and (self.mode == "G"):
                # end of mission
                print("END MISSION")
                self.nav.Init()
                self.PublishNavigation()
                self.mission.SaveNavigation()
                self.mission.EndMission()
            self.mode = mode
            self.pausedMode = None

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
            self.mission.SaveWaypoints(MissionName=mission_name)
        elif request == 'MakeWaypointMap':
            mission_map = MissionMap(waypoints=self.mission.Waypoints())
            map_fn = 'Map_%s_%s_%s.jpeg' % (payload['_sender'], payload['_sendPid'], payload['_sendSeq'])
            map_fp = os.path.join(self.imageDir, map_fn)
            mission_map.SaveMap(map_fp)
            payload['filename'] = map_fn
            payload['captureFormat'] = 'jpeg'

        self.Publish(vconst.navigator_service_ack_topic, payload)

    def LoadGpsPayload(self):
        payload = self.new_gps_payload
        if payload is None:
            return False
        self.new_gps_payload = None
        self.longitude = payload['longitude']
        self.latitude = payload['latitude']
        self.gps_speed = payload['gps_speed']
        self.heading = payload['heading']
        self.yaw = payload['yaw']
        self.acc_dist_f = payload['acc_dist_f']
        #self.gpsRequested = False
        self.gpsReadyForNavigation = True
        self.stats.Count('GpsRcv')
        return True

    def LoadImuPayload(self):
        payload = self.new_imu_payload
        if payload is None:
            return False
        self.new_imu_payload = None
        self.yaw = payload['yaw']
        self.acc_dist_f = payload['acc_dist_f']
        self.stats.Count('ImuRcv')

    def DoLoop(self):
        if self.mission is None:
            if self.new_mission_begin_payload is None:
                # No navigation. No active mission. None to load.
                return
            mission_payload = self.new_mission_begin_payload
            self.new_mission_begin_payload = None
            self.new_mission_cancel_payload = None
            self.mission = Mission(self, mission_payload)
        if self.mission is not None:
            if self.new_mission_begin_payload is not None:
                # A new mission has been received, cancel the existing mission
                self.mission.StartWrapup()
            elif self.new_mission_cancel_payload is not None:
                # The current mission is being cancelled
                self.new_mission_cancel_payload = None
                self.mission.StartWrapup()
            self.mission.DoMission()			# do mission work
            if not self.mission.running:
                self.mission = None
            return
        return		# the following code needs to be moved to mission
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
        if not self.mqttc.connected:
            return
        if self.mode != 'G':
            return				# not in navigator control mode
        #
        # Navigation are scheduled movements of the robot. They can take a relatively long period of time
        # compared to how often this DoLoop() is executed. Once started, they generally continue till
        # completed. Completion can be determined by running to a fixed time, fixed sensor output or
        # a mission step decision.
        #
        # Several navigation steps may be queued up in self.navSteps. These are often components of a
        # manuever like a back-up Y turn.
        #
        # If we have an active navigation steps, check if should be terminated.
        #
        if self.nav is not None:
            #if (self.nav.hardTimeLimit > 0) or self.gpsReadyForNavigation:
            #    print("TL {} GPS Rdy: {}".format(self.nav.hardTimeLimit, self.gpsReadyForNavigation))
            if self.nav.hardTimeLimit > 0:
                # if there is a time limit, just follow those orders until they expire.
                # if there is an unexpired time limit, untrustedGpsUpdates is ignored, we don't get that far.
                if  self.nav.hardTimeLimit > time.time():
                    # we want to maintain the the current navigation orders until completed by yaw or time
                    if not self.CheckYawForCompletedManuever():
                        return				# not ended, continue timed order
            if self.nav.dist_max is not None:
                if self.acc_dist_f > self.nav.dist_max:
                    self.EStop()
                    self.nav = None
                else:
                    #print("FWD", self.acc_dist_f,  self.nav.dist_max, (self.nav.dist_max - self.acc_dist_f))
                    return
            if self.nav.dist_min is not None:
                if self.acc_dist_f < self.nav.dist_max:
                    self.EStop()
                    self.nav = None
                else:
                    return
        #
        # The previous navigation step has expired or ended by IMU yaw, check if there are any other
        # scheduled naviagation steps.
        #
        if len(self.navSteps) > 0:
            self.nav = self.navSteps.pop(0)
            self.PublishNavigation()
            return				# new orders came from stack
        #
        # See what the mission step wants to do
        #
        if self.mission.mission_step_ix < len(self.mission.mission_steps):
            print("DoLoop/DoMissionStep", self.mission.mission_step_ix)
            step = self.mission.mission_steps[self.mission.mission_step_ix]
            mission_step_finis = step.DoMissionStep(self)
            if mission_step_finis:
                self.mission.mission_step_ix += 1
        else:
            if self.nav is None:
                # If we are out of mission steps and the last navigation step has terminated
                # come to a stop.
                self.EStop()
        self.stats.Print("MSGS")

    def EStop(self):
        payload = {}
        payload['heading'] = "A0"
        payload['speed'] = 0
        payload['timer'] = 6
        self.Publish(vconst.helmsman_orders_topic, payload)

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

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        vnavs_mqtt.LaunchNode(navigator)
    elif sys.argv[1] == 'map':
        RunMap()
    elif sys.argv[1] == 'test':
        TestNav2()
    elif sys.argv[1] == 'testimucancel':
        TestImuCancel()
