try:
    import numpy as np
    import cv2
    from vnavslib import opticchiasm as oc
except ImportError:
    cv2 = None
    np = None
    oc = None

import math
import os
from geopy.distance import great_circle
import string
import sys
import time

from ezcomms import vnavs_comms as vcomms
from ezcomms import vnavs_node as vmqtt
from ezcomms import vnavs_const as vconst
from ezcomms import vnavs_data as vdata
from vnavsrun import engineer_1
from vnavsrun import helmsman

WAYPOINT_WINDOW_METERS = 4.0
STEER_STRAIGHT_HEADING = 10.0
STEER_SHARP_HEADING = 90.0
FORWARD_VERY_SLOW = 2
FORWARD_SLOW = 6  # OK slow for court
FORWARD_SLOW = 16  # this is what it took to move well on grass at robogames
FORWARD_SLOW = 4  # too slow for court (maybe depends on battery)
FORWARD_FAST = 10
FORWARD_FAST = 14
FORWARD_FAST = 8
FORWARD_FAST = 20  # robgames on grass
FORWARD_FAST_METERS = 10
REVERSE_SLOW = -4
STOP_SPEED = 0
STOP_SECONDS = 2
MAX_TIMED_MANUEVER_SECONDS = 10
Y_TURN_LIMIT = 160
INITIAL_GPS_WAIT = 3
OVERSTEER_ADJUSTMENT = 0.5

NAVIGATOR_WAYPOINT_LATITUDE = "waypoint_latitude"
NAVIGATOR_WAYPOINT_LONGITUDE = "waypoint_longitude"
NAVIGATOR_WAYPOINT_HEADING = "waypoint_heading"
NAVIGATOR_WAYPOINT_DISTANCE = "waypoint_distance"


class PID:
    __slots__ = (
        "d_gain",
        "d_out",
        "derivative",
        "error",
        "i_out",
        "i_accumulator",
        "i_gain",
        "i_time_last",
        "output_scale",
        "p_gain",
        "p_out",
        "pid_out",
        "prev_error",
        "target_value",
    )

    def __init__(self, SetPoint=0, KP=1.0, KI=0.5, KD=0.25, OutputScale=1.0):
        # Parameter names are common engineering terms.
        # Code variables are more like programming terms.
        self.target_value = SetPoint
        self.p_gain = KP
        self.i_gain = KI
        self.d_gain = KD
        self.output_scale = OutputScale
        self.Reset()

    def Reset(self):
        self.error = 0
        self.prev_error = 0
        self.p_out = 0
        self.i_accumulator = 0
        self.i_out = 0
        self.d_out = 0
        self.derivative = 0
        self.pid_out = 0
        self.i_time_last = time.time()  # time in seconds

    def GetOutput(self, current_state):
        if current_state is None:
            return None
        time_now = time.time()
        dt = time_now - self.i_time_last
        self.error = current_state - self.target_value

        self.p_out = self.error * self.p_gain

        self.i_accumulator += self.error * dt
        self.i_out = self.i_accumulator * self.i_gain

        self.derivative = (self.error - self.prev_error) / dt
        self.d_out = self.derivative * self.d_gain
        #
        self.i_time_last = time_now
        self.prev_error = self.error
        self.pid_out = self.p_out + self.i_out + self.d_out
        scaled_output = self.pid_out * self.output_scale
        print(
            "PID.GetOutput()",
            self.target_value,
            current_state,
            scaled_output,
            "--",
            self.p_out,
            self.i_out,
            self.d_out,
        )
        return scaled_output

    def GetOutputInt(self, current_state):
        if current_state is None:
            return None
        return int(self.GetOutput(current_state))


def CheckYawForCompletedManuever(current_yaw, nav):
    ## ************** ##
    # Need to track how far we have been moving in same direction. If we overshoot
    # past folding point we get stuck in circle.
    #
    if nav.startingYaw is None:
        return False  # there is nothing to complete
    if self.yaw is None:
        return False  # probably an error, no IMU data arriving
    yawDeltaSoFar = current_yaw - nav.startingYaw
    print(
        "IMU YAW {:+8.4f} Goal Delta: {:+8.4f} Progress: {:+8.4f}".format(
            current_yaw, nav.deltaYawGoal, yawDeltaSoFar
        )
    )
    if nav.deltaYawGoal < 0:
        # we are turning left. Heading going down in value.
        # Possibly wrapping from 0 to 359
        if current_yaw > nav.startingYaw:
            # we have probably wrapped 0/360, but it could be noise or wind
            try:
                if (current_yaw - nav.startingYaw) > 30:
                    # it's a significant difference, not noise
                    yawDeltaSoFar -= 360
            except TypeError:
                # not sure how this happened!
                print("TYPE ERROR")
                pass
        if yawDeltaSoFar <= nav.deltaYawGoal:
            # we have gone more negative, further left
            return True  # manuever completed
        else:
            return False  # manuever continuing
    else:
        # we are turning right, Heading going up in value.
        # Possibly wrapping from 359 to 0
        if current_yaw < nav.startingYaw:
            if (current_yaw - nav.startingYaw) < -30:
                yawDeltaSoFar += 360
        if yawDeltaSoFar >= nav.deltaYawGoal:
            return True  # manuever completed
        else:
            return False  # manuever continuing


def NavigateTowardWaypoint(
    current_yaw, current_position, waypoint, nav, navigator=None
):
    # should be reworked using GeographicLib ??
    # Longitude are lines drawn between poles. +/- 180 degrees from Prime Meridian (Greenwich England)
    # delta Longitude is deltaX.
    # Latitude are lines drawn ~ perpendicular to longitude. Equator is 0 degrees, poles are +/- 90 degrees.
    # delta Latitude is deltaY.
    # geopy coordinates are (latitude, longitude) or (y, x)
    if current_yaw is None:
        # we don't know our current direction. Can't navigate.
        print("NO HEADING - can't navigate.")
        return None
    delta = current_position.DistanceToWaypoint(waypoint)

    diffHeading = current_yaw - delta.heading_to_waypoint
    deltaHeading = (
        diffHeading + 180
    ) % 360 - 180  # heading change needed from current heading to waypoint

    if abs(deltaHeading) < STEER_STRAIGHT_HEADING:
        nav.Init()
        nav.steering = 0
        if delta.distance_to_waypoint > 10:
            nav.speed = FORWARD_FAST
        else:
            nav.speed = FORWARD_SLOW
    else:
        # deltaHeading is +/- 180 degrees, map to +/- 60 steering order.
        # this should query the helmsman for this bots range instead of assuming 60.
        # The signs of headings and steering command are the same. Negative means
        # the waypoint is to the left, positive is to the right.
        if True:  # For now, just stear for all turns
            # if abs(deltaHeading) <= Y_TURN_LIMIT:
            # make the direct turn
            nav.Init()
            nav.steering = -int(deltaHeading / 3)
            if (delta.distance_to_waypoint > 10) and (abs(deltaHeading) < 20):
                nav.speed = FORWARD_FAST
            else:
                nav.speed = FORWARD_SLOW
            """
            if abs(deltaHeading) > 45:
                pass
                #self.nav.untrustedGpsUpdates = 1		# give GPS time to settle after tight turn
                nav.softKeepSeconds = 2
                nav.speed = FORWARD_SLOW
                nav.startingYaw = current_yaw
                nav.deltaYawGoal = deltaHeading
            """
        """
        *** This is a Y U-Turn which needs to be reimplimented ***
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
        """
    # self.PublishNavigation()
    # self.mission.navpoints.append(((self.latitude, self.longitude), self.nav.steering))
    # print("Path (%s, %s) -> %s" % (self.latitude, self.longitude, self.mission.waypoints[self.mission.stage_step_ix]))
    # print("Path %4s dX %+03.4f dY %+03.4f Hyp %+03.2f difHdg %+03.4f GpsHdg %+03.4f HdgToW %03.4f %2d" % (self.nav.steering, deltaX, deltaY, d.distance_to_waypoint,
    # 					deltaHeading, self.heading, waypointHeading, self.mission.stage_step_ix))
    payload = {}
    payload[NAVIGATOR_WAYPOINT_LATITUDE] = waypoint.latitude
    payload[NAVIGATOR_WAYPOINT_LONGITUDE] = waypoint.longitude
    payload[NAVIGATOR_WAYPOINT_HEADING] = delta.heading_to_waypoint
    payload[NAVIGATOR_WAYPOINT_DISTANCE] = delta.distance_to_waypoint
    navigator.publish(vconst.navigator_plot_topic, payload)

    # print("NavigateTowardWaypoint()", current_yaw, delta.heading_to_waypoint, deltaHeading, nav.steering, nav.speed)
    return delta.distance_to_waypoint


class MissionStep:
    __slots__ = (
        "mission",
        "mission_vars",
        "name",
        "nav",
        "navigator",
        "parm_pos",
        "parm_kword",
        "parm_mission",
        "stage",
    )

    def __init__(self, stage):
        self.mission = stage.mission
        self.mission_vars = []
        self.name = None  # not required. used for StepWait
        self.nav = NavStep()
        self.navigator = self.mission.navigator
        self.stage = stage
        self.parm_pos = None
        self.parm_kword = None
        self.parm_mission = None

    def Load(self, parm_pos, parm_kword, parm_mission):
        self.parm_pos = parm_pos
        self.parm_kword = parm_kword
        self.parm_mission = parm_mission

    def PublishNavigation(self, timer=6):
        # mission_specs = self.navigator.persistent_data.Get('mission_specs', key_group='/')
        # speed_method = mission_specs.get('speed_method', 'automatic')
        speed_method = "manual"

        payload = {}
        payload[helmsman.HELMSMAN_HEADING] = self.nav.steering
        if speed_method != "manual":
            payload[helmsman.HELMSMAN_SPEED] = self.nav.speed
        payload[helmsman.HELMSMAN_P_ERROR] = self.nav.p_error
        payload[helmsman.HELMSMAN_I_ACCUMULATOR] = self.nav.i_accumulator
        payload[helmsman.HELMSMAN_DERIVATIVE] = self.nav.derivative
        payload[helmsman.HELMSMAN_TIMER] = timer
        self.navigator.publish(vconst.helmsman_orders_topic, payload)
        if self.nav.untrustedGpsUpdates < 0:
            # this could be dangerous, skipping navigation indefinately
            if self.nav.hardKeepSeconds <= 0:
                # we intend to end the manuever with IMU yaw, this keeps us safe
                self.nav.hardKeepSeconds = MAX_TIMED_MANUEVER_SECONDS
        if self.nav.softKeepSeconds > 0:
            self.nav.softTimeLimit = time.time() + self.nav.softKeepSeconds
        if self.nav.hardKeepSeconds > 0:
            self.nav.hardTimeLimit = time.time() + self.nav.hardKeepSeconds
        # print("PublishNavigation", payload)


class StepData(MissionStep):
    __slots__ = ("dname", "dtype", "dkeygroup")

    def __init__(self, stage):
        super().__init__(stage)
        self.dname = None
        self.dtype = None
        self.dkeygroup = None

    def DoStageStepInit(self):
        self.dname = self.parm_pos[0]
        self.dtype = self.parm_pos[1]
        if len(self.parm_pos) > 2:
            self.dkeygroup = self.parm_pos[2]

    def DoStageStepRun(self, loop_ct):
        self.navigator.persistent_data.PutPayload(
            self.dname, self.dtype, self.parm_kword, key_group=dkeygroup
        )
        return True


class StepKeyGroup(MissionStep):
    __slots__ = ("dkeygroup",)

    def __init__(self, stage):
        super().__init__(stage)
        self.dkeygroup = None

    def DoStageStepInit(self):
        self.dkeygroup = self.parm_pos[0]

    def DoStageStepRun(self, loop_ct):
        self.navigator.persistent_data.SetDefaultKeyGroup(self.dkeygroup)
        return True


class StepFollowLinePid(MissionStep):
    __slots__ = ("next_time", "speed", "pid")

    def __init__(self, stage):
        super().__init__(stage)
        self.next_time = None
        self.pid = PID(SetPoint=285, OutputScale=1.0, KI=0, KD=1)
        self.speed = 4

    def DoStageStepInit(self):
        if "speed" in self.parm_kword:
            self.speed = int(self.parm_kword["speed"])
        if "Kp" in self.parm_kword:
            self.pid.p_gain = float(self.parm_kword["Kp"])
        if "Ki" in self.parm_kword:
            self.pid.i_gain = float(self.parm_kword["Ki"])
        if "Kd" in self.parm_kword:
            self.pid.d_gain = float(self.parm_kword["Kd"])
        rect = oc.RectFromPayload(self.parm_kword)
        self.pid.target_value = rect.center_x
        self.next_time = 0
        self.pid.Reset()

    def DoStageStepRun(self, loop_ct):
        if time.time() > self.next_time:
            self.nav.steering = self.pid.GetOutputInt(self.navigator.line_x)
            self.nav.speed = self.speed
            self.nav.p_error = self.pid.error
            self.nav.i_accumulator = self.pid.i_accumulator
            self.nav.derivative = self.pid.derivative
            print(
                "StepFollowLinePid.DoStageStepRun() LINEpid",
                self.navigator.line_x,
                self.nav.speed,
                self.nav.steering,
            )
            self.PublishNavigation()
            self.next_time = time.time() + 1.0
            self.next_time = time.time() + 0.5
        return False


class StepFollowLineTrace(MissionStep):
    __slots__ = (
        "base_angle",
        "next_time",
        "sensitvity_x",
        "sensitivity_general",
        "speed",
        "target_x",
    )

    def __init__(self, stage):
        super().__init__(stage)
        self.next_time = None
        self.base_angle = 135
        self.sensitivity_general = 1.5
        self.sensitivity_x = 1.0
        self.speed = 4

    def DoStageStepInit(self):
        if "speed" in self.parm_kword:
            self.speed = int(self.parm_kword["speed"])
        if "base_angle" in self.parm_kword:
            self.base_angle = float(self.parm_kword["base_angle"])
        rect = oc.RectFromPayload(self.parm_kword)
        self.target_x = rect.center_x
        self.next_time = 0

    def DoStageStepRun(self, loop_ct):
        if time.time() > self.next_time:
            x_error = self.navigator.line_x - self.target_x
            x_steering = float(x_error) * self.sensitivity_x
            path_steering = self.navigator.line_angle - self.base_angle
            self.nav.steering = int(
                ((x_steering + path_steering) * self.sensitivity_general)
            )
            self.nav.speed = self.speed
            print(
                "StepFollowLinePid.DoStageStepRun() LINEtrace",
                self.navigator.line_x,
                self.nav.speed,
                self.nav.steering,
            )
            self.PublishNavigation()
            self.next_time = time.time() + 1.0
            self.next_time = time.time() + 0.1
        return False


class StepGpsWaypoint(MissionStep):
    __slots__ = ("next_time", "speed", "waypoint", "differential_base_position")

    def __init__(self, stage):
        super().__init__(stage)
        self.waypoint = None
        self.differential_base_position = vconst.DifferentialGpsClear
        self.speed = 0
        self.next_time = None

    def DoStageStepInit(self):
        key = self.parm_pos[0]
        print("StepGpsWaypoint()", key, self.navigator.persistent_data.key_group)
        self.waypoint = self.navigator.persistent_data.Get(key)
        print("StepGpsWaypoint", self.waypoint)
        if "differential_base_position" in self.parm_kword:
            differential_gps_key = self.parm_kword["differential_base_position"]
            start_position = self.navigator.persistent_data.Get(differential_gps_key)
            self.differential_base_position = start_position.PositionString()
        # Always publish differntial_base_position, either to set or clear
        payload = {}
        payload["differential_base_position"] = self.differential_base_position
        self.navigator.publish(vconst.engineer_1_settings_topic, payload)
        if len(self.parm_pos) > 1:
            self.speed = int(self.parm_pos[1])
        self.next_time = time.time()
        print("StepGpsWaypoint.DoStageStepInit()")

    def DoStageStepRun(self, loop_ct):
        # should check freshness of GPS and IMU data
        current_position = self.navigator.gps_data.Position()
        # print("StepGpsWaypoint.DoStageStepRun()", current_position, self.waypoint)
        delta = current_position.DistanceToWaypoint(self.waypoint)
        if delta.distance_to_waypoint <= WAYPOINT_WINDOW_METERS:
            print(
                "StepGpsWaypoint.DoStageStepRun() reached waypoint",
                delta.distance_to_waypoint,
            )
            self.nav.Init()
            self.PublishNavigation()
            payload = {}
            payload["differential_base_position"] = vconst.DifferentialGpsClear
            self.navigator.publish(vconst.engineer_1_settings_topic, payload)
            return True
        if time.time() > self.next_time:
            # print("StepGpsWaypoint.DoStageStepRun() navigate", delta.distance_to_waypoint)
            NavigateTowardWaypoint(
                self.navigator.imu_data.imu_yaw,
                current_position,
                self.waypoint,
                self.nav,
                navigator=self.navigator,
            )
            self.PublishNavigation()
            self.next_time = time.time() + 1.0
            self.next_time = time.time() + 0.5
        return False

        # if check_yaw and CheckYawForCompletedManuever(self.navigator.yaw, self.nav):

        return  # old code follows
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
            if (self.mode == "G") and (len(self.mission.waypoints) > 0):
                print("GPS")
                check_yaw = False
                self.stats.Count("GpsPrc")
                distance = self.NavigateTowardWaypoint(self.mission.stage_step_ix)
                if distance <= WAYPOINT_WINDOW_METERS:
                    self.mission.stage_step_ix += 1
                    if self.mission.stage_step_ix >= len(self.mission.waypoints):
                        self.mission.stage_step_ix = 0
                    distance = self.NavigateTowardWaypoint(
                        self.mission.stage_step_ix
                    )  # navigate toward new waypoint immediately
            self.gpsReadyForNavigation = False
        if check_yaw and self.CheckYawForCompletedManuever():
            print("IMU")
            self.nav.Init()
            self.nav.speed = FORWARD_SLOW
            self.PublishNavigation()


class StepMove(MissionStep):
    __slots__ = ("speed", "steering", "timer", "end_time")

    def __init__(self, stage):
        super().__init__(stage)
        self.speed = 0
        self.steering = 0
        self.timer = 1
        self.end_time = None

    def DoStageStepInit(self):
        self.speed = int(self.parm_kword["speed"])
        self.steering = int(self.parm_kword["steering"])
        self.timer = float(self.parm_kword["timer"])

    def DoStageStepRun(self, loop_ct):
        print("StepMove.DoStageStepRun()", loop_ct, self.end_time, time.time())
        if loop_ct == 1:
            self.nav.speed = self.speed
            self.nav.steering = self.steering
            self.PublishNavigation(timer=self.timer)
            self.end_time = time.time() + self.timer
            return False
        if time.time() >= self.end_time:
            return True


class StepMagic(MissionStep):
    __slots__ = ("last_imageFn", "movement_started")

    def __init__(self, stage):
        super().__init__(stage)
        self.last_imageFn = None
        self.movement_started = False

    def DoStageStepInit(self):
        pass

    def DoStageStepRun(self, loop_ct):
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
        r = oc.Robogames(im, [25])
        r.ProcessLines()
        r.FilterLines()
        r.SelectLines()
        outFn = "X" + self.last_imageFn[1:]
        outFp = os.path.join(self.navigator.imageDir, outFn)
        cv2.imwrite(outFp, r.annotated)
        payload = {}
        payload["filename"] = outFn
        # self.publish('pic_ready', payload, source='cameraman')
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
                return True  # end mission steo
            else:
                print("WAIT")
        return


class StepWait(MissionStep):
    __slots__ = "wait_target"

    def __init__(self, stage):
        super().__init__(stage)
        self.wait_target = None

    def DoStageStepInit(self):
        self.wait_target = self.parm_pos[0]

    def DoStageStepRun(self, loop_ct):
        conf_id = self.mission.confirmation_ids[self.wait_target]
        print("StepWait() checking", self.wait_target, conf_id)
        payload = self.navigator.CheckConfirmation(conf_id)
        if payload is None:
            return False
        else:
            return True


class StepAccMotion(MissionStep):
    def __init__(self, stage):
        super().__init__(stage)

    def DoStageStepInit(self):
        self.direction = self.parm_pos[0]
        self.distance = float(self.parm_pos[1])

    def DoStageStepRun(self, loop_ct):
        # def DoStageStepRun(self, nav):
        step = NavStep()
        step.steering = "A0"
        if self.direction == "F":
            step.speed = FORWARD_SLOW
            step.dist_max = nav.acc_dist_f + self.distance
        else:
            step.speed = REVERSE_SLOW
            step.dist_min = nav.acc_dist_f - self.distance
        nav.nav = step
        nav.PublishNavigation()
        return True


#
# Message Step
#
class StepMessage(MissionStep):
    __slots__ = ("payload", "topic")

    def __init__(self, stage):
        super().__init__(stage)
        self.topic = ""
        self.payload = {}

    def DoStageStepInit(self):
        self.topic = self.parm_pos[0]
        self.payload.update(self.parm_kword)

    def DoStageStepRun(self, loop_ct):
        print("StepMessage", self.topic, self.payload)
        conf = None
        if self.name is not None:
            conf = self.name + vmqtt.NowStr()
            self.mission.confirmation_ids[self.name] = conf
        self.mission.navigator.publish(self.topic, self.payload, conf_request=conf)
        return True


class StepSleep(MissionStep):
    def __init__(self, stage):
        super().__init__(stage)
        self.interval = interval

    def DoStageStepRun(self, loop_ct):
        time.sleep(float(self.interval))
        return True


MISSION_NAME = "mission_name"
MISSION_SCRIPT = "mission_script"
MISSION_DEBUG = "mission_debug"


class MissionStage:
    __slots__ = ("mission", "name", "steps")

    def __init__(self, mission, name):
        self.mission = mission
        self.name = name
        self.steps = []


class MissionStepDef:
    def __init__(self, kword, sclass=None, func=None, defs=None):
        self.name = kword
        self.sclass = sclass
        self.func = func
        if defs is not None:
            defs[self.name] = self


MISSION_STATE_NONE = 0
MISSION_STATE_LOADED = 10
MISSION_STATE_STARTED = 20  # vconst_stage_init has started
MISSION_STATE_INITED = 30  # vconst.stage_init stage has completed
MISSION_STATE_WRAPUP = 35  # mission is ending, only vconst.stage_finis should run
MISSION_STATE_FINISED = 40  # vconst.stage_finis has been completed
MISSION_STATE_ENDED = 50  # EndMission() termination process completed


class Mission:
    __slots__ = (
        "active_stage",
        "confirmation_ids",
        "mission_id",
        "mission_state",
        "mission_name",
        "mission_script",
        "named_steps",
        "navigator",
        "stage_step_ix",
        "stage_step_loop_ct",
        "stages_dict",
        "stages_list",
    )

    def __init__(self, navigator=None, name="", script=None, InitiatorPayload=None):
        self.active_stage = None
        self.confirmation_ids = {}
        self.navigator = navigator
        self.mission_id = None
        self.mission_name = name
        self.mission_script = script
        self.named_steps = {}
        self.stages_dict = {}
        self.stages_list = []
        self.stage_step_ix = 0
        self.stage_step_loop_ct = 0
        self.mission_state = MISSION_STATE_NONE
        if self.mission_script is not None:
            self.LoadMission(self.mission_script, InitiatorPayload=InitiatorPayload)

    def LoadMission(self, script, InitiatorPayload=None):
        def StartLog(stage, parm_pos):
            while len(parm_pos) < 1:
                parm_pos.append("")
            parm_pos[0] = vconst.mission_log_start_topic
            return StepMessage(stage)

        def StopLog(stage, parm_pos):
            while len(parm_pos) < 1:
                parm_pos.append("")
            parm_pos[0] = vconst.mission_log_stop_topic
            return StepMessage(stage)

        step_defs = {}
        MissionStepDef("data", sclass=StepData, defs=step_defs)
        MissionStepDef("key_group", sclass=StepKeyGroup, defs=step_defs)
        MissionStepDef("gps", sclass=StepGpsWaypoint, defs=step_defs)
        MissionStepDef("follow_line_pid", sclass=StepFollowLinePid, defs=step_defs)
        MissionStepDef("follow_line_trace", sclass=StepFollowLineTrace, defs=step_defs)
        MissionStepDef("log_start", func=StartLog, defs=step_defs)
        MissionStepDef("log_stop", func=StopLog, defs=step_defs)
        MissionStepDef("magic", sclass=StepMagic, defs=step_defs)
        MissionStepDef("move", sclass=StepMove, defs=step_defs)
        MissionStepDef("message", sclass=StepMessage, defs=step_defs)
        MissionStepDef("sleep", sclass=StepSleep, defs=step_defs)
        MissionStepDef("wait", sclass=StepWait, defs=step_defs)

        self.mission_script = script
        print("LOAD", self.mission_name)
        this_stage = None
        line_no = 0
        err_ct = 0
        for this in self.mission_script:
            line_no += 1
            line = this.strip()
            hash = line.find("#")
            if hash >= 0:
                line = line[:hash].strip()
                # print("LoadMission()", line, line.__class__.__name__)
            if line == "":
                continue
            print(line)
            if line[0] == "/":
                pass  # continuation?
            else:
                step = None
                # This is a new mission command
                parts = line.split(":")
                # parse command
                cparts = [p.strip() for p in parts[0].split(" ")]
                step_type = cparts[0]
                step_name = None
                if len(cparts) > 1:
                    if cparts[1] == "name":
                        step_name = cparts[2]
                # parse parameters
                parm_kword = {}
                parm_pos = []
                parm_mission = []
                for this in parts[1:]:
                    eq = this.find("=")
                    if eq > 0:
                        key = this[:eq].strip()
                        value = this[eq + 1 :].strip()
                    else:
                        key = ""
                        value = this.strip()
                    if key == "":
                        parm_pos.append(value)
                        if value[0] == "$":
                            # also in parm_pos so positions don't shift
                            parm_mission.append(value[1:])
                    else:
                        parm_kword[key] = value
                if step_type == "stage":
                    stage_name = parm_pos[0]
                    print("LoadMission() Add Stage", stage_name)
                    stage = MissionStage(self, stage_name)
                    self.stages_list.append(stage_name)
                    self.stages_dict[stage_name] = stage
                    this_stage = stage
                elif step_type in step_defs:
                    if this_stage is None:
                        print("LoadMission() Stage must be defined before work step")
                        err_ct += 1
                    else:
                        sdef = step_defs[step_type]
                        if sdef.func is None:
                            # The step is created by simply creating a StepXXX class member
                            step = sdef.sclass(this_stage)
                        else:
                            # The step needs some fixups, so we have a function to do that
                            step = sdef.func(this_stage, parm_pos)
                        if step_name is not None:
                            step.name = step_name
                            self.named_steps[step_name] = step
                        step.Load(parm_pos, parm_kword, parm_mission)
                        this_stage.steps.append(step)
                else:
                    print("LoadMission() Unknown step type", step_type)
                    err_ct += 1
        self.mission_state = MISSION_STATE_LOADED
        if InitiatorPayload is not None:
            # Only announce if part of runnng mission -- not mission control
            payload = vcomms.prepare_response(InitiatorPayload)
            self.navigator.publish(vconst.mission_loaded_topic, payload)
        print("Mission Loaded", self.stages_list, InitiatorPayload)

    def DoMission(self):
        if (self.mission_state < MISSION_STATE_LOADED) or (
            self.mission_state >= MISSION_STATE_FINISED
        ):
            # Missions cannot run before they are loaded and are over after vconst.stage_finis has completed.
            return
        # At this time, we trust mission control to send rational stage requests.
        # We probably need a production/testing mode flag.
        # In testing, anything goes. In production, init must be first and other sequence
        # controls may be prudent.
        if (self.active_stage is None) and (self.mission_state < MISSION_STATE_WRAPUP):
            # We get here if prior stage has been completed or if a newly loaded mission.
            # Once we start wrapping up mission, synchronous events are ignored.
            if self.navigator.mission_sync_event_payload is not None:
                if "mission_stage" in self.navigator.mission_sync_event_payload:
                    stage_name = self.navigator.mission_sync_event_payload[
                        "mission_stage"
                    ]
                    self.StartStage(
                        stage_name, self.navigator.mission_sync_event_payload
                    )
                self.navigator.mission_sync_event_payload = None
        if self.active_stage is None:
            return  # waiting for external event (from mission control)
        if self.stage_step_ix >= len(self.active_stage.steps):
            # we just finised the current stage
            payload = {}
            payload["mission_id"] = self.mission_id
            payload["mission_name"] = self.mission_name
            payload["mission_stage"] = self.active_stage.name
            self.navigator.publish(vconst.mission_stage_completed_topic, payload)
            if self.active_stage.name == vconst.stage_init:
                self.mission_state = MISSION_STATE_INITED
            elif self.active_stage.name == vconst.stage_finis:
                self.mission_state = MISSION_STATE_FINISED
                self.EndMission(None)
            self.active_stage = None
            print("DoMission() End Stage", self.mission_state)
            return
        self.stage_step_loop_ct += 1
        step = self.active_stage.steps[self.stage_step_ix]
        # print("Mission.DoMission() loop_ct", self.stage_step_loop_ct)
        if self.stage_step_loop_ct == 1:
            print(
                "DoMission() Start Stage Step",
                self.active_stage.name,
                len(self.active_stage.steps),
                step.__class__.__name__,
                self.mission_state,
            )
            print("DoMission() Step", step.parm_pos, step.parm_kword, step.parm_mission)
            for this in step.parm_mission:
                d = self.navigator.persistent_data.Get(this)
                print("DoMission() Init Step Mission Data", this, d)
                step.parm_kword.update(d)
            step.DoStageStepInit()
        if step.DoStageStepRun(self.stage_step_loop_ct):
            # The step returns true to indicate that it is done.
            # Otherwise it repeats on the next DoMission().
            self.stage_step_ix += 1  # increment to next step in this stage
            self.stage_step_loop_ct = 0  # set counter for executions of new step

    def StartStage(self, stage_name, initiator_payload):
        if not (stage_name in self.stages_list):
            return False
        # initiator_payload could be none if navigator decided to start a stage
        # without an external event. Maybe from an abend or timeout. That is not
        # implemented at this point.
        if stage_name == vconst.stage_init:
            # This is the start of a mission
            self.mission_id = f"{self.mission_name}_{vmqtt.NowStr()}"
            if initiator_payload is None:
                stage_payload = {}
            else:
                init_payload = vcomms.prepare_response(initiator_payload)
            init_payload["mission_id"] = self.mission_id
            init_payload["mission_name"] = self.mission_name
            init_payload["mission_stage"] = stage_name
            self.navigator.publish(vconst.mission_init_topic, init_payload)
            self.mission_state = MISSION_STATE_STARTED
        elif stage_name == vconst.stage_init:
            self.mission_state = MISSION_STATE_WRAPUP
        # Start this stage
        if initiator_payload is None:
            stage_payload = {}
        else:
            stage_payload = vcomms.prepare_response(initiator_payload)
        stage_payload["mission_id"] = self.mission_id
        stage_payload["mission_name"] = self.mission_name
        stage_payload["mission_stage"] = stage_name
        self.navigator.publish(vconst.mission_stage_started_topic, stage_payload)
        self.active_stage = self.stages_dict[stage_name]
        self.stage_step_ix = 0
        self.stage_step_loop_ct = 0
        return True

    def EndMission(self, initiator_payload):
        # We can get here naturally because vconst.stage_finish has ended routinely
        # or because of an exceptioon event.
        if (self.mission_state >= MISSION_STATE_STARTED) and (
            self.mission_state < MISSION_STATE_WRAPUP
        ):
            if vconst.stage_finis in self.stages_list:
                # it's  conceivable to get in a loop where vconst.stage_finis
                # never completes because we keep restarting it.
                # Maybe check if vconst.stage_finis is running and do
                # something a bit different. MISSION_STATE_WRAPUP has
                # been added to identify and prevent potential issues.
                self.mission_state = MISSION_STATE_WRAPUP
                self.StartStage(vconst.stage_finis, initiator_payload)
                # The mission has not ended, but we are working on it.
                print("EndMission() Wrapup Started")
                return False
            else:
                self.mission_state = MISSION_STATE_FINISED
        # We get here if the mission was never started or vconst.stage_finis
        # has either completed or doesn't exist. We can get here multiple times
        # if the operator clicks repeatedly. That isn't harmful, but nodes
        # need to be able to handle multiple vconst.mission_end_topic messages.
        payload = {}
        payload["mission_id"] = self.mission_id
        payload["mission_name"] = self.mission_name
        self.navigator.publish(vconst.mission_end_topic, payload)
        self.mission_state = MISSION_STATE_ENDED
        print("EndMission() Mission Ended")
        return True

    def CancelMission(self, initiator_payload):
        # This is a hard stop, closing all dangeous operations.
        # This starts vconst.stage_finis, to clean up the mission.
        self.navigator.EStop()
        self.EndMission(initiator_payload)

    def Waypoints(self):
        waypoints = []
        for s in self.mission_steps:
            if isinstance(s, StepGpsWaypoint):
                waypoints.append(s.waypoint)
        return waypoints

    def SaveWaypoints(self, MissionName=None):
        return
        mission_name = self.missionName
        if MissionName is not None:
            mission_name = MissionName
        fp = os.path.join(self.navigator.missionDir, mission_name) + ".mis"
        f = open(fp, "w")
        for p in self.waypoints:
            f.write("W,%f,%f\n" % (p[1][0], p[1][1]))
        f.close

    def SaveNavigation(self, MissionName=None):
        return
        mission_name = self.missionName
        if MissionName is not None:
            mission_name = MissionName
        fp = os.path.join(self.navigator.missionDir, mission_name) + ".nav"
        f = open(fp, "w")
        for p in self.waypoints:
            if p[0] == "W":
                f.write("W,%s,%s\n" % (p[1][0], p[1][1]))
            elif p[0] == "M":
                f.write("M,%s\n" % (p[1]))
        for p in self.navpoints:
            f.write("N,%f,%f,%s\n" % (p[0][0], p[0][1], p[1]))
        f.close()


class NavStep:
    def __init__(self):
        self.Init()

    def Init(self):
        # When we have multiple steps, all the intermediate steps must either have
        # hardKeepSeconds > 0 or untrustedGpsUpdates < 0 with yaw settings to cancel
        # the operation.
        self.steering = "0"
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
        self.p_error = 0
        self.i_accumulator = 0
        self.derivative = 0


class navigator(vmqtt.VnavsNode):
    def __init__(self, verbose=False):
        super().__init__(
            subscriptions=[
                vmqtt.Subscription(
                    vconst.cameraman_pic_ready_topic, handler=self.DoCameramanPicReady
                ),
                vmqtt.Subscription(
                    vconst.engineer_1_gps_topic, handler=self.DoEngineer1Gps
                ),
                vmqtt.Subscription(
                    vconst.engineer_1_imu_topic, handler=self.DoEngineer1Imu
                ),
                vmqtt.Subscription(
                    vconst.mission_load_topic, handler=self.DoMissionLoad
                ),
                vmqtt.Subscription(
                    vconst.mission_cancel_topic, handler=self.DoMissionCancel
                ),
                vmqtt.Subscription(
                    vconst.mission_sync_event_topic, handler=self.DoMissionSyncEvent
                ),
                # vmqtt.Subscription(vconst.navigator_service_topic, handler=self.DoNavigatorService),
                vmqtt.Subscription(
                    vconst.data_save_topic, async_delivery=True, handler=self.OnDataSave
                ),
                vmqtt.Subscription(
                    vconst.data_get_topic, async_delivery=True, handler=self.OnDataGet
                ),
            ],
            single_threaded=False,
            broker_type="F",
            streamer=False,
            verbose=verbose,
        )
        self.missionDir = self.get_ini_directory(
            "Navigator", "MissionDir", IsWriteable=True
        )
        self.gps_data = engineer_1.GpsDataRecord()
        self.imu_data = engineer_1.ImuDataRecord()
        self.imageFn = None
        self.imageRequested = None
        self.line_angle = None
        self.line_centers = []
        self.line_x = None
        self.mission = None
        self.mission_load_payload = None
        self.mission_sync_event_payload = None
        self.mission_cancel_payload = None
        self.serviceNames = [
            "ClearWaypoints",
            "MarkWaypoint",
            "SaveWaypoints",
            "MakeWaypointMap",
        ]
        self.serviceRequests = []
        self.gpsReadyForNavigation = False
        self.persistent_data = vdata.PersistentData()

    def OnDataSave(self, payload):
        # The payload is in the format of a PersistentData entry
        print("OnDataSave()", payload)
        pdata = payload["pdata"]
        self.persistent_data.PutPdata(pdata)

    def OnDataGet(self, payload):
        print("OnDataGet()", payload)
        key = payload[vdata.dkey_field_name]
        key_group = payload[vdata.dgroup_field_name]
        pdata = self.persistent_data.GetPdata(key, key_group=key_group)
        response_payload = vcomms.prepare_response(payload, conf_request=True)
        response_payload["pdata"] = pdata
        self.publish(vconst.data_put_topic, response_payload)

    def rmsg_navigator_service(self, payload):
        request = payload["request"]
        if request not in self.serviceNames:
            return "unknown service"
        self.serviceRequests.append(payload)

    def ProcessServiceRequest(self):
        if len(self.serviceRequests) < 1:
            return
        payload = self.serviceRequests.pop(0)
        print("PROCESS", payload)
        request = payload["request"]
        payload = vcomms.prepare_response(payload)
        payload["MissionName"] = self.mission.missionName
        payload["WaypointCt"] = len(self.mission.waypoints)
        if request == "ClearWaypoints":
            self.mission.Init()
        elif request == "MarkWaypoint":
            self.mission.waypoints.append(("W", (self.latitude, self.longitude)))
        elif request == "SaveWaypoints":
            if "MissionName" in payload:
                mission_name = payload["MissionName"]
            else:
                mission_name = None
            self.mission.SaveWaypoints(MissionName=mission_name)
        elif request == "MakeWaypointMap":
            mission_map = MissionMap(waypoints=self.mission.Waypoints())
            map_fn = "Map_%s_%s_%s.jpeg" % (
                payload["_sender"],
                payload["_sendPid"],
                payload["_sendSeq"],
            )
            map_fp = os.path.join(self.imageDir, map_fn)
            mission_map.SaveMap(map_fp)
            payload["filename"] = map_fn
            payload["captureFormat"] = "jpeg"

        self.publish(vconst.navigator_service_ack_topic, payload)

    def DoEngineer1Gps(self, payload):
        self.gps_data.LoadPayload(payload)
        self.stats.Count("GpsRcv")
        self.gpsReadyForNavigation = True

    def DoEngineer1Imu(self, payload):
        self.imu_data.LoadPayload(payload)
        self.stats.Count("ImuRcv")

    def DoCameramanPicReady(self, payload):
        if "center_line" in payload:
            line_at = payload["center_line"]
            list_of_OpenCvRect = oc.ListOfOpenCvRectFromListofDicts(line_at)
            self.line_centers = []
            if len(list_of_OpenCvRect) > 0:
                self.line_x = list_of_OpenCvRect[0].center_x
                start_y = list_of_OpenCvRect[0].center_y
                for this_rect in list_of_OpenCvRect:
                    self.line_centers.append(this_rect.center)
                    end_x = this_rect.center_x
                    end_y = this_rect.center_y
                if end_y < start_y:
                    adjacent_len = float(start_y - end_y)
                    opposite_len = float(self.line_x - end_x)
                    self.line_angle = math.degrees(
                        math.atan2(adjacent_len, opposite_len)
                    )
                    # print("DoCameramanPicReady()", self.line_x, start_y, end_x, end_y, self.line_angle, "<<<")

    def DoMissionLoad(self, payload):
        self.mission_load_payload = payload
        self.mission_cancel_payload = None
        self.mission_sync_event_payload = None

    def DoMissionSyncEvent(self, payload):
        self.mission_sync_event_payload = payload

    def DoMissionCancel(self, payload):
        self.mission_cancel_payload = payload
        self.mission_load_payload = None
        self.mission_sync_event_payload = None

    def client_loop_code(self):
        if self.mission is None:
            if self.mission_load_payload is not None:
                mission_payload = self.mission_load_payload
                self.mission_load_payload = None
                self.mission_cancel_payload = None
                name = mission_payload[MISSION_NAME]
                script = mission_payload[MISSION_SCRIPT].split("\n")
                self.mission = Mission(
                    self, name=name, script=script, InitiatorPayload=mission_payload
                )

        if self.mission is not None:
            if self.mission_load_payload is not None:
                # A new mission has been received, cancel the existing mission
                self.mission.CancelMission(self.mission_load_payload)
            elif self.mission_cancel_payload is not None:
                # The current mission is being cancelled
                self.mission.CancelMission(self.mission_cancel_payload)
                self.mission_cancel_payload = None
            self.mission.DoMission()  # do mission work
            if self.mission.mission_state >= MISSION_STATE_FINISED:
                self.mission = None
            return

    def EStop(self):
        payload = {}
        payload[helmsman.HELMSMAN_HEADING] = "0"
        payload[helmsman.HELMSMAN_SPEED] = 0
        payload[helmsman.HELMSMAN_TIMER] = 6
        self.publish(vconst.helmsman_orders_topic, payload)


class MissionMap:
    def __init__(self, waypoints=None, navpoints=None):
        self.waypoints = waypoints
        self.navpoints = navpoints
        self.InitMap()
        self.FindExtentsLatLong()
        self.mapOriginLongitudeX = 0
        self.mapOriginLatitudeY = 0
        self.waypointColor = "red"
        self.waypointColor = (0, 0, 255)  # red BGR
        self.navpointColor = "green"
        self.navpointColor = (0, 255, 0)
        self.survey_ul = engineer_1.Position(0.0, 0.0)
        self.survey_lr = engineer_1.Position(0.0, 0.0)

    def InitSurvey(self):
        # A survey is a plot of positions with some calculations made continuously.
        self.navpoints = []
        self.survey_min_latitudeZ = None
        self.survey_max_latitudeZ = None
        self.survey_min_longitudeZ = None
        self.survey_max_longitudeZ = None

    def SurveyCount(self):
        if self.navpoints is None:
            return 0
        return len(self.navpoints)

    def AppendSurveyPosition(self, position):
        if self.navpoints is None:
            self.InitSurvey()
        self.navpoints.append(position)
        latitudeZ = (
            position.latitude + 90.0
        )  # convert latitude (y-axis) to zero base 0 to 180
        longitudeZ = (
            position.longitude + 180.0
        )  # convert longitude (x-axis) to zero base 0 to 360
        if self.survey_min_latitudeZ is None:
            self.survey_min_latitudeZ = latitudeZ
            self.survey_max_latitudeZ = latitudeZ
            self.survey_min_longitudeZ = longitudeZ
            self.survey_max_longitudeZ = longitudeZ
        if latitudeZ < self.survey_min_latitudeZ:
            self.survey_min_latitudeZ = latitudeZ
        if latitudeZ > self.survey_max_latitudeZ:
            self.survey_max_latitudeZ = latitudeZ
        if longitudeZ < self.survey_min_longitudeZ:
            self.survey_min_longitudeZ = longitudeZ
        if longitudeZ > self.survey_min_longitudeZ:
            self.survey_max_longitudeZ = longitudeZ
        self.survey_ul.latitude = self.survey_max_latitudeZ - 90.0
        self.survey_lr.latitude = self.survey_min_latitudeZ - 90.0
        self.survey_ul.longitude = self.survey_min_longitudeZ - 180.0
        self.survey_lr.longitude = self.survey_max_longitudeZ - 180.0
        d = self.survey_ul.DistanceToWaypoint(self.survey_lr)
        self.survey_hypotenuse = d.distance_to_waypoint

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
            x = point[1] + 180.0  # convert to range(0, 360)
            y = point[0] + 90.0  # convert to range(0, 180)
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
        deltaMetersX = great_circle(
            (minLatitudeT, minLongitudeT), (minLatitudeT, maxLongitudeT)
        ).meters
        deltaMetersY = great_circle(
            (minLatitudeT, minLongitudeT), (maxLatitudeT, minLongitudeT)
        ).meters
        if deltaMetersX > deltaMetersY:
            self.mapScalePixelsPerMeter = (
                self.mapSizePixels - (2 * self.mapMarginPixels)
            ) / deltaMetersX
        else:
            try:
                self.mapScalePixelsPerMeter = (
                    self.mapSizePixels - (2 * self.mapMarginPixels)
                ) / deltaMetersY
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
        print(
            "SCALE",
            self.mapScalePixelsPerMeter,
            self.mapMetersPerLongitudeX,
            self.mapMetersPerLatitudeY,
        )

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
        # self.map.save(im_fp)
        cv2.imwrite(fp, self.map)

    def DrawPointLatLong(self, point, color, size=1):
        # point is (latitude, longitude), (y, x) map coordinates
        # The following needs to consider crossing equator, poles, prime meridian, dateline.
        # Right now I don't want to think about it. This should work for North America.
        if (point[1] < self.mapOriginLongitudeX) or (
            point[0] < self.mapOriginLatitudeY
        ):
            print("Invalid DrawPointLatLong()", point)
            return
        x = (point[1] - self.mapOriginLongitudeX) * self.mapMetersPerLongitudeX
        y = (point[0] - self.mapOriginLatitudeY) * self.mapMetersPerLatitudeY
        print("DrawPointLatLong() %s -> (%s, %s)" % (point, x, y))
        self.DrawPointMeters((x, y), color, size)

    def DrawPointMeters(self, point, color, size=1):
        # point is (x, y) in meters from some origin.
        # Origin may be off visible map.
        # Origin (0,0) is lower right with increasing values up and right.
        x = int(
            round((point[0] - self.originOffsetMetersX) * self.mapScalePixelsPerMeter)
        )
        y = self.mapMaxPixelsY - int(
            round((point[1] - self.originOffsetMetersY) * self.mapScalePixelsPerMeter)
        )
        if (x < 0) or (x > self.mapMaxPixelsX) or (y < 0) or (y > self.mapMaxPixelsY):
            print(
                "Invalid DrawPointMeters() (%d,%d) (%d,%d)."
                % (point[0], point[1], x, y)
            )
            return
        print("DrawPointMeters() (%d,%d) (%d,%d)." % (point[0], point[1], x, y))
        # self.mapDraw.point((x, y), fill=color)
        # self.mapDraw.ellipse((x-size, y-size, x+size, y+size), fill=color)
        cv2.circle(self.map, (x, y), size, color, -1)


def TestMap():
    waypoints = [(37.6272, -122.4541), (38.6276, -123.4522)]
    m = MissionMap(waypoints)
    m.Save()


def TestNav():
    h = navigator()
    h.latitude = 37.6272
    h.longitude = -122.4540
    h.waypoints = [
        (37.6272, -122.4541),  # about 10 meters west (270 deg)
        (37.6276, -122.4522),  # about 30 meters north (0 deg)
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
    h.longitude = 0  # start at Prime Meridian @ Equator
    h.waypoints = [
        (1, 0),  # north one latitude, heading 0
        (1, 1),  # east 1 longitude, heading 90
        (0, 1),  # south one latitude, heading 180
        (0, 0),  # west one longitude, heading 270
        (3, 1),  # north three, east one, heading 18.4349, qudrant I
        (4, 4),  # north one, east three, heading 71.5650, quadrant I
        (3, 7),  # south one, east three, heading 108.4349, quadrant II
        (0, 8),  # south three, east one, heading 161,5650, quadrant II
        (-3, 7),  # south three, west one, heading 198.4349, quadrant III
        (-4, 4),  # south one, west three, heading 251.5650, quadrant III
        (-3, 1),  # north one, west three, heading 288.4349, quadrant IV
        (0, 0),  # north three, west one, heading 341.5650, quadrant IV
    ]
    headings = [
        0,
        90,
        180,
        270,
        18.4349,
        71.5650,
        108.4349,
        161.5650,
        198.4349,
        251.5650,
        288.4349,
        341.5650,
    ]
    for ix in range(0, len(h.waypoints)):
        h.heading = headings[ix]
        h.NavigateTowardWaypoint(ix)
        h.latitude = h.waypoints[ix][0]
        h.longitude = h.waypoints[ix][1]
        print(h.nav)
        print(h.navSteps)


def TestImuCancel():
    tests = [(350, -10, 359, 330, -3)]
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
            print(
                "IMU YAW {:+8.4f} Goal Delta: {:+8.4f} Progress: {}".format(
                    h.yaw, h.nav.deltaYawGoal, r
                )
            )


def RunMap():
    waypoints = []
    navpoints = []
    f = open("test.nav", "r")
    for this in f.readlines():
        parts = this.split(",")
        if parts[0] == "W":
            waypoints.append((float(parts[1]), float(parts[2])))
        elif parts[0] == "N":
            navpoints.append((float(parts[1]), float(parts[2])))
    m = MissionMap()
    m.FindExtentsLatLong(waypoints=waypoints, navpoints=navpoints)
    m.PlotWaypoints()
    m.PlotNavpoints()
    m.SaveMap("/exports/missions/Runmap.jpeg")


if __name__ == "__main__":
    if sys.argv[1] == "node":
        m = navigator()
        m.main_loop()
    elif sys.argv[1] == "map":
        RunMap()
    elif sys.argv[1] == "test":
        TestNav2()
    elif sys.argv[1] == "testimucancel":
        TestImuCancel()
