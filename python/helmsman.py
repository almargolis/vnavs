import json
import math
import traceback
import io
import queue
import sys
import threading
import time

from pyfirmata import Arduino, util

import vnavs_mqtt as vmqtt
import vnavs_const as vconst
import paho.mqtt.client as mqtt

TICK_PATTERNS = [
	[],				# 0 tick bits
	[],				# 1 tick bits
	[				# 2 tick bits
		[True, True, True, True],
		[True, False, False, False],
		[True, False, True, False],
		[True, True, True, False]
	]
]

class SteeringPlanStep(object):
    def __init__(self, direction):
        self.direction = direction

class vehicle(object):
    """
        This class isolates low level hardware functions so that helmsman is vehicle
        agnostic. Right now it is hardwired for my initial robot. Later on it will
        either be subclassed or specilaized with a configuration file.

        For now, speed variables are actual Arduino Servo values. Eventually
        we want them to use actual speed mm/sec and map that to whatever
        control values are needed for the vehicle.
    """
    def __init__(self):
        self.board = Arduino('/dev/ttyUSB0')
        self.motor = self.board.get_pin('d:9:s')
        self.governor = 0
        self.tickBits = 2
        self.tickMax = (1 << self.tickBits)
        self.tickMask = (1 << self.tickBits) - 1
        # mot_offset does not include ticks
        self.mot_offset = 90
        self.mot_tick_clock = 0
        self.mot_pulse_dead_zone_f = 7		# Low pulse values that have no effect on motor
        self.mot_pulse_dead_zone_r = 4		# Low pulse values that have no effect on motor
        # mot_jump_f and mot_jump_r are SPEEDS, they are an increment above the pulse dead zone
        self.mot_jump_f = 3			# This is the minimum speed to start moving from stop
        self.mot_jump_r = -1			# This is the minimum speed to start moving from stop
        self.mot_ramp_increment = 0		# Current ramping increment
        self.mot_this_pulse = 0
        self.mot_this_tick = 0
        self.mot_last_pulse = 0
        self.mot_last_tick = 0
        # speed in mm/second - depends on vehicle and battery condition
        # For now speed is just a number.
        # Zero is stopped, 1 is crawl, 2... incrementally faster (negative is reverse)
        self.mot_speed_goal = SPEED_STOP	# we may be ramping toward this
        self.mot_speed_ramp = SPEED_STOP	# current speed, on way to goal
        self.speed_max = 13411			# 30mph / 13.4112 meters/second
        self.speed_max = 40			# servo speed request
        #
        self.steering = self.board.get_pin('d:10:s')
        self.steering_offset = 90
        self.steering_increment	= 10		# degrees of casual steering adjustment
        self.steering_max = 30			# 60 degrees left or right
        self.steering_max = 90			# 60 degrees left or right
        self.steering_last = 0			# last actual steering position
        self.steering_base = 0			# general goal, 0 for navigation, X for circles
        self.steering_plan = None		# steering variations from base
        self.steering_type = None		# R(elative) or A(bsolute)
        self.steering_goal = 0			# this is absolute steering direction
        self.steering_tick = 0			# time increment / step in plan
        self.steering_tock = 0			# counter toward tick_width
        self.steering_tick_width = 20 		# number off loops too maintain each plan step
        self.Estop()

    def ConvertSpeedToPulseParameter(self, speed):
        # Speed is just a number indicating relative speed
        if speed == SPEED_STOP:
            return (0, 0)
        if speed < 0:
            speed = -speed
            xsign = -1
        else:
            xsign = 1
        tick = speed & self.tickMask
        pulse = (speed >> self.tickBits) * xsign
        print("Convert:", speed, (speed >> self.tickBits), xsign)
        if xsign > 0:
            pulse += self.mot_pulse_dead_zone_f
        else:
            pulse -= self.mot_pulse_dead_zone_r
        print("Convert", pulse, tick)
        return (pulse, tick)

    def NewSpeedGoal(self, speed_goal):
        new_speed_goal = int(speed_goal)
        if self.governor > 0:
            if  (new_speed_goal > 0) and (new_speed_goal > self.governor):
                new_speed_goal = self.governor
            elif  (new_speed_goal < 0) and (new_speed_goal < (-self.governor)):
                new_speed_goal = -self.governor
        if new_speed_goal == self.mot_speed_goal:
            return
        # the goal has changed, need to reset ramping variables
        print("New Speed Goal ***", new_speed_goal)
        self.mot_speed_goal = new_speed_goal
        if self.mot_speed_goal == SPEED_STOP:
            # We want to stop.
            # This is all hardwired ZERO to avoid ambiguity about stopping.
            self.mot_speed_ramp = SPEED_STOP
            self.mot_ramp_increment = RAMP_NONE
            return
        if self.mot_speed_ramp == SPEED_STOP:
            # we are starting to move from a stop
            if self.mot_speed_goal >= self.mot_jump_f:
                # we are starting fast (forward), so just do it
                self.mot_speed_ramp = self.mot_speed_goal
                self.mot_ramp_increment = RAMP_NONE
                return
            elif self.mot_speed_goal <= self.mot_jump_r:
                # we are starting fast (reverse), so just do it
                self.mot_speed_ramp = self.mot_speed_goal
                self.mot_ramp_increment = RAMP_NONE
                return
            elif self.mot_speed_goal > SPEED_STOP:
                # we are want to go slow slow (forward), need to make an initial jump to overcome standing inertia
                self.mot_speed_ramp = self.mot_jump_f
                self.mot_ramp_increment = RAMP_DOWN
                return
            else:
                # we are want to go slow slow (reverse), need to make an initial jump to overcome standing inertia
                self.mot_speed_ramp = self.mot_jump_r
                self.mot_ramp_increment = RAMP_UP
                return
        # this is speed change while moving
        self.mot_speed_ramp = self.mot_speed_goal
        self.mot_ramp_increment = RAMP_NONE

    def RampSpeeed(self):
        self.mot_speed_ramp += self.mot_ramp_increment
        print("Ramp:", self.mot_speed_ramp, self.mot_ramp_increment, self.mot_speed_goal)
        if self.mot_speed_goal > SPEED_STOP:
            if self.mot_ramp_increment > RAMP_NONE:
                if self.mot_speed_ramp >= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp_increment = RAMP_NONE
            else:
                if self.mot_speed_ramp <= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp_increment = RAMP_NONE
        else:
            if self.mot_ramp_increment > RAMP_NONE:		# positive ramp, slowing down toward zero
                if self.mot_speed_ramp >= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp_increment = RAMP_NONE
            else:
                if self.mot_speed_ramp <= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp_increment = RAMP_NONE

    def Estop(self):
        self.motor.write(self.mot_offset)	# Stop motor if on
        self.mot_speed_goal = SPEED_STOP
        self.mot_speed_ramp = SPEED_STOP

    def Tick(self):
        # Called frequently. Hopefully at a precise fixed interval.
        # The required prcision is faily good but doesn't need to be perfect
        # because momemtum and chassis electronics provide some dampening
        # so some varition is smoothed out.
        # Checks if its time to change vehicle motor or steering setting.
        self.MotorTick()
        self.SteeringTick()

    def MotorTick(self):
        # This sends commands to the hardware motor controller (ESC or H-Bridge).
        # This handles ramping if not handled by hardware motor controller.
        # This only considers forward motion right now.
        # This is fragile. Need to soften states to avoid race conditions.
        # This must be called frequently in order to maintain control of the
        # vehicle. Maybe it should be in its own thread.
        #print("M-Tick", self.mot_ramp_increment, self.mot_speed_goal)
        #
        # self.mot_speed_goal is how fast we want to go
        # self.mot_speed_ramp is current speed setting, which ramps toward the goal
        #
        if self.mot_speed_goal == SPEED_STOP:
            self.motor.write(self.mot_offset)	# Stop motor if on
            return
        if self.mot_ramp_increment != RAMP_NONE:
            self.RampSpeeed()
        self.mot_this_pulse, self.mot_this_tick = self.ConvertSpeedToPulseParameter(self.mot_speed_ramp)
        # we know our pulse requirement, tell the hardware
        # self.mot_this_pulse and self.mot_this_tick is how fast we are driving now.
        # self.mot_goal_pulse and self.mot_goal_tick are the speed we are ramping towards.
        # In reality, they are the same most of the time.
        tick_pattern = TICK_PATTERNS[self.tickBits][self.mot_this_tick]
        #print("Pattern @", self.mot_tick_clock, self.tickBits, self.mot_this_tick, tick_pattern)
        tick_rule = tick_pattern[self.mot_tick_clock]
        if tick_rule:
            # we want to move on this tick
            if self.mot_this_tick == 0:
                self.actualPulse = self.mot_offset + self.mot_this_pulse
            elif self.mot_tick_clock <= self.mot_this_tick:
                # apply a pulse of the next fastest step
                if self.mot_this_pulse > 0:
                    self.actualPulse = self.mot_offset + self.mot_this_pulse + 1
                else:
                    self.actualPulse = self.mot_offset + self.mot_this_pulse - 1
        else:
            # we want to "coast" on this tick -- maintain speed
            self.actualPulse = self.mot_offset
        self.motor.write(self.actualPulse)
        print("Motor:", self.actualPulse, "@", self.mot_tick_clock, "(", self.mot_speed_ramp, "->", self.mot_speed_goal,"Spec:", self.mot_this_pulse, ":", self.mot_this_tick)
        self.mot_tick_clock += 1
        if self.mot_tick_clock > self.tickMask:
            self.mot_tick_clock = 0
        self.mot_last_pulse = self.mot_this_pulse
        self.mot_last_tick = self.mot_this_tick

    def NewSteeringGoal(self, steering_goal):
        step = SteeringPlanStep(steering_goal)
        self.steering_plan = [step]
        return
        if self.steering_plan is not None:
            print("OLD PLAN", self.steering_plan)
            # Don't start a new relative motion till previous complete
            return
        self.steering_tick = 0			# time increment / step in plan
        self.steering_tock = 0
        goal_type = steering_goal[1]
        goal_degree = (int(steering_goal[2:]) * self.steering_increment)
        if goal_type == 'V':
            # veer
            self.steering_plan = [goal_degree, goal_degree, 0, 0, -goal_degree, -goal_degree]
        else:
            # change heading
            self.steering_plan = [goal_degree, goal_degree, goal_degree]
        print("PLAN", self.steering_plan)

    def SteeringTick(self):
        # Direction is a number in the range minus/plus self.steering_max which the the degree of turning.
        # Negative degrees are turns left and positive are turns right.
        if self.steering_plan is None:
            direction = STEER_STRAIGHT
        else:
            direction = self.steering_plan[0].direction
        print("SteeringTick()", self.steering_offset, direction, self.steering_plan)
        try:
            self.steering.write(self.steering_offset + direction)
        except ValueError:
            pass				# attempt to write invalid value
        self.steering_last = direction
        return

        # The following is the old steering code which is a mess but may be useful when filling out the
        # above new code.

        if (steering_goal is None) or (not isinstance(steering_goal, str)) or (steering_goal == ''):
            pass
        elif steering_goal[0] == 'R':
            self.steering_type = 'R'
            self.NewSteeringGoal(steering_goal)
        elif steering_goal[0] == 'A':
            self.steering_type = 'A'
            self.steering_goal = int(steering_goal[1:])
        if self.steering_plan is None:
            if self.steering_type == 'A':
                direction = self.steering_goal
            else:
                direction = self.steering_base
        else:
            plan_step = self.steering_plan[self.steering_tick]
            direction = self.steering_base + plan_step
            self.steering_tock += 1
            if self.steering_tock >= self.steering_tick_width:
                # its time to increment to the next step
                self.steering_tick += 1
                self.steering_tock = 0
                if self.steering_tick >= len(self.steering_plan):
                    # steering plan has been completed
                    self.steering_plan = None
        if direction >= 0:
            if direction > self.steering_max:
                direction = self.steering_max
        else:
            if direction < (-self.steering_max):
                direction = (-self.steering_max)
        if direction != self.steering_last:
            print("Steer:", direction)

RAMP_NONE = 0
RAMP_UP = 1
RAMP_DOWN = -1

STATE_DEADMAN = 'd'			# d=deadman active
STATE_CONTINUOUS = 'c'			# c=continuous-no timer
STATE_TIMED_OUT = 't'			# t=time out
STATE_ESTOPPED = 'e'			# e=e-stop
STATES_MOVING = STATE_DEADMAN + STATE_CONTINUOUS

SPEED_DECREASE = 'd'			# decrease spead by one step
SPEED_STOP = 0

STEER_STRAIGHT = 0

HELMSMAN_GOVERNOR = 'governor'
HELMSMAN_SPEED_CONTROL = 'speed_control'
HELMSMAN_SPEED_CONTROL_DEFAULT = '*'
HELMSMAN_MAX_SPEED_CONTROL = 'max_speed_control'
HELMSMAN_STEERING_CONTROL = 'steering_control'
HELMSMAN_STEERING_CONTROL_DEFAULT = '*'

HELMSMAN_STATE = 'state'
HELMSMAN_SPEED = 'speed'
HELMSMAN_SPEED_SCALE_MIN = 'speed_scale_min'
HELMSMAN_SPEED_SCALE_MAX = 'speed_scale_max'
HELMSMAN_HEADING = 'heading'
HELMSMAN_HEADING_SCALE_MIN = 'heading_scale_min'
HELMSMAN_HEADING_SCALE_MAX = 'heading_scale_max'
HELMSMAN_TIMER = 'timer'
HELMSMAN_P_ERROR = 'p_error'
HELMSMAN_I_ACCUMULATOR = 'i_accumulator'
HELMSMAN_DERIVATIVE = 'derivative'

class helmsman(vmqtt.mqtt_node):
    def __init__(self):
        self.orders_q = queue.Queue(10)
        super().__init__(Subscriptions=[
						vmqtt.Subscription(vconst.helmsman_orders_topic, async_delivery=True, handler=self.OnHelmsmanOrders),
						vmqtt.Subscription(vconst.helmsman_controls_topic, async_delivery=True, handler=self.OnHelmsmanControls),
						vmqtt.Subscription(vconst.mission_log_start_topic, async_delivery=True, handler=self.OnMissionLogStart),
                                                vmqtt.Subscription(vconst.mission_log_stop_topic, async_delivery=True, handler=self.OnMissionLogStop)
				], SingleThreaded=False, BrokerType='F', Verbose=False)
        self.v = vehicle()
        self.steering_goal = 0		# (int) degrees (0 = straigh, neg is degrees left, pos is degrees right)
        self.mission_logging = False
        self.deadman_time = 0		# E-Stop if time.time() exceeds this
        self.speed_control = HELMSMAN_SPEED_CONTROL_DEFAULT
        self.steering_control = HELMSMAN_STEERING_CONTROL_DEFAULT
        self.state = STATE_DEADMAN

    def ClearOrdersQueue(self):
        # This could block if something is continuously filling queue.
        # Maybe should abort if max queue size loops exceeded.
        while True:
            try:
                self.orders_q.get_nowait()
            except queue.Empty:
                return

    def OnHelmsmanControls(self, payload):
        if HELMSMAN_GOVERNOR in payload:
            self.v.governor = int(payload[HELMSMAN_GOVERNOR])
        if HELMSMAN_MAX_SPEED_CONTROL in payload:
            self.v.speed_max = int(payload[HELMSMAN_MAX_SPEED_CONTROL])
        if HELMSMAN_STEERING_CONTROL in payload:
            self.steering_control = payload[HELMSMAN_STEERING_CONTROL].strip()
        if HELMSMAN_SPEED_CONTROL in payload:
            self.speed_control = payload[HELMSMAN_SPEED_CONTROL].strip()

    def OnHelmsmanOrders(self, payload):
        #print("ORDERS C:", time.time(), "D:", self.deadman_time, payload)
        if HELMSMAN_STATE in payload:
            print("--------------------")
            new_state = payload[HELMSMAN_STATE]
            if new_state == STATE_ESTOPPED:
                print("XXXXXXXXXXXXXXXXXXXXXX")
                self.v.Estop()
                self.state = STATE_ESTOPPED
                self.ClearOrdersQueue()
            if new_state in STATES_MOVING:
                self.state = new_state
        if self.state == STATE_ESTOPPED:
            return
        try:
            self.orders_q.put_nowait(payload)
        except queue.Full:
            pass			# should log this and do something
        return				# the rest is abandoned code

    def OnMissionLogStart(self, payload):
        self.mission_logging = True

    def OnMissionLogStop(self, payload):
        self.mission_logging = False

    def InterpretOrdersSpeed(self, payload):
        if self.speed_control == HELMSMAN_SPEED_CONTROL_DEFAULT:
            pass
        else:
          if self.speed_control == payload['_sender']:
              pass
          else:
              print("HELMSMAN - Unauthorized Speed Order from %s".format(payload['_sender']))
              return
        if HELMSMAN_SPEED_SCALE_MIN in payload:
            speed_raw = int(payload[HELMSMAN_SPEED])
            speed_scale_min = int(payload[HELMSMAN_SPEED_SCALE_MIN])
            speed_scale_max = int(payload[HELMSMAN_SPEED_SCALE_MAX])
            speed_request = self.ScaleRequest(speed_raw, -speed_scale_min, -speed_scale_max, -self.v.speed_max, self.v.speed_max)
        else:
            speed_request = payload[HELMSMAN_SPEED]	# Note: alphanumeric
        self.v.NewSpeedGoal(speed_request)
        print("SPEED", speed_request)

    def InterpretOrdersHeading(self, payload):
        if self.steering_control == HELMSMAN_STEERING_CONTROL_DEFAULT:
            pass
        else:
          if self.steering_control == payload['_sender']:
              pass
          else:
              print("HELMSMAN - Unauthorized Steering Order from %s".format(payload['_sender']))
              return
        if HELMSMAN_HEADING_SCALE_MIN in payload:
            heading_raw = int(payload[HELMSMAN_HEADING])
            heading_scale_min = int(payload[HELMSMAN_HEADING_SCALE_MIN])
            heading_scale_max = int(payload[HELMSMAN_HEADING_SCALE_MAX])
            heading_request = self.ScaleRequest(heading_raw, heading_scale_min, heading_scale_max, -self.v.steering_max, self.v.steering_max, sensitivity=None)
        else:
            try:
                heading_request = int(payload[HELMSMAN_HEADING])	# Note: alphanumeric
            except TypeError:
                heading_request = 0
        self.v.NewSteeringGoal(heading_request)

    def InterpretOrders(self, payload):
        if HELMSMAN_SPEED in payload:
            self.InterpretOrdersSpeed(payload)
        if HELMSMAN_HEADING in payload:
            self.InterpretOrdersHeading(payload)
        if HELMSMAN_TIMER in payload:
            print("TIMER", payload[HELMSMAN_TIMER])
            timer = int(payload[HELMSMAN_TIMER])
        else:
            timer = 3
        self.deadman_time = time.time() + timer
        if self.state == STATE_TIMED_OUT:
            # end timeout when new command arrives
            self.state = STATE_DEADMAN

    def ScaleRequest(self, raw_value, raw_min, raw_max, target_min, target_max, sensitivity=0.05):
        # return an integer value within target range proportional to raw value in raw range
        if raw_max >= raw_min:
            raw_range = raw_max - raw_min
            raw_inversion = 1.0
        else:
            raw_range = raw_min - raw_max
            raw_inversion = -1.0
        raw_range_pct = float(raw_value - raw_min) / float(raw_range)
        if sensitivity is None:
            # linear scaling
            target_range = float(target_max - target_min)
            request_value = ((target_range * raw_range_pct) + float(target_min)) * raw_inversion
        else:
            # parabolic scaling
            # This assumes target range is symetrial around zero.
            assert (target_min + target_max) == 0
            target_max_x = math.sqrt(float(target_max) / sensitivity)
            target_x_value = ((target_max_x * 2) * raw_range_pct) - target_max_x
            request_value = (sensitivity * math.pow(target_x_value, 2.0)) * raw_inversion
            if target_x_value < 0:
                request_value = 0 - request_value
            print("SCALE", raw_value, request_value, target_x_value)
        return int(request_value)

    def DoLoop(self):
        print("STATE", self.state, "Governor", self.v.governor)
        if not self.mqttc.connected:
            self.v.Estop()
            return
        if (self.state == STATE_DEADMAN) and (time.time() > self.deadman_time):
            self.v.Estop()
            self.state = STATE_TIMED_OUT
            self.stats.Count('timeouts')
            return
        if self.state == STATE_ESTOPPED:
            self.v.Estop()
            return
        # Process just the nost recent order if we have multiples.
        payload = None
        while True:
            try:
                payload = self.orders_q.get_nowait()
            except queue.Empty:
                break
        if payload is not None:
            self.InterpretOrders(payload)

        if self.state in STATES_MOVING:
            # Speed and Steering goals are set asynchronously via MQTT messages
            self.v.Tick()

    def CleanupLoop(self):
        self.v.Estop()
"""
    def SpeedRequestStr(self, speed_request):
        speed_goal = None
        if speed_request in '+=':
            speed_goal = self.speed_goal + 1
        elif speed_request == '-':
            speed_goal = self.speed_goal - 1
        elif speed_request in 'f':			# increase forward speed
            speed_goal = self.speed_goal + 1
        elif speed_request == 'r':			# increase reverse speed
            speed_goal = self.speed_goal - 1
        elif speed_request in SPEED_DECREASE:		# decrease speed (forward or reverse)
          if self.speed_goal <= 0:
              speed_goal = self.speed_goal + 1
              if speed_goal > 0:
                  speed_goal = 0
          else:
              speed_goal = self.speed_goal - 1
              if speed_goal < 0:
                  speed_goal = 0
        elif speed_request == 's':			# stop moving
          speed_goal = 0
        return speed_goal

    def GetGoalSpeed(self, speed_request):
        # from Loop(). It is possible that Loop() has not seen or acted upon
        # the previous goal. This means care must be exercised when processing
        # incremental requests. A subsequent +1 could be sent due to impatience
        # rather than an actual intent to increment speed in additiion to any
        # pending increments. There shouldn't be much latency, but for big
        # fast bots, some caution is in order.
        speed_goal = None
        if isinstance(speed_request, str):
            speed_goal = self.SpeedRequestStr(speed_request)
        if speed_goal is None:
          try:
            speed_goal = int(speed_request)
          except:
            print("Bad Input '%s'" %(speed_request))
            speed_goal = self.speed_goal
        if abs(speed_goal) > self.v.speed_max:
            if speed_goal > 0:
                self.speed_goal = +self.v.speed_max
            else:
                self.speed_goal = -self.v.speed_max
        else:
            self.speed_goal = speed_goal

    def GetGoalSteering(self, steering_request):
        self.steering_goal = steering_request
        return
        if steering_request == 's':
            steering_goal = 0
        elif steering_request == '+l':
            steering_goal = self.steering_goal - self.v.steering_increment
        elif steering_request == '+r':
            steering_goal = self.steering_goal + self.v.steering_increment
        else:
            try:
                steering_goal = int(steering_request)
            except:
                print("Bad Steering Input '%s'" % (steering_request))
                steering_goal = sself.steering_goal
        if abs(steering_goal) > self.v.steering_max:
            if steering_goal > 0:
                steering_goal = self.v.steering_max
            else:
                steering_goal = -self.v.steering_max
        else:
          self.steering_goal = steering_goal

"""

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        vmqtt.LaunchNode(helmsman)
