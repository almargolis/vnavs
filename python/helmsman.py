from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import json
import traceback
import io
import sys
import threading
import time

from pyfirmata import Arduino, util

import vnavs_mqtt
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
        self.mot_ramp = 0			# Current ramping increment
        self.mot_this_pulse = 0
        self.mot_this_tick = 0
        self.mot_last_pulse = 0
        self.mot_last_tick = 0
        self.steering = self.board.get_pin('d:10:s')
        # speed in mm/second - depends on vehicle and battery condition
        # For now speed is just a number.
        # Zero is stopped, 1 is crawl, 2... incrementally faster (negative is reverse)
        self.mot_speed_goal = 0			# we may be ramping toward this
        self.mot_speed_ramp = 0			# current speed, on way to goal
        self.speed_max = 13411			# 30mph / 13.4112 meters/second
        self.steering_offset = 90
        self.steering_increment	= 10		# degrees of casual steering adjustment
        self.steering_max = 60			# 60 degrees left or right
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
        if speed == 0:
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
        self.mot_speed_goal = int(speed_goal)
        if self.mot_speed_goal == 0:
            # We want to stop.
            # This is all hardwired ZERO to avoid ambiguity about stopping.
            self.mot_speed_ramp = 0
            self.mot_ramp = 0
            return
        if self.mot_speed_ramp == 0:
            # we are starting to move from a stop
            if self.mot_speed_goal >= self.mot_jump_f:
                # we are starting fast (forward), so just do it
                self.mot_speed_ramp = self.mot_speed_goal
                self.mot_ramp = 0
                return
            elif self.mot_speed_goal <= self.mot_jump_r:
                # we are starting fast (reverse), so just do it
                self.mot_speed_ramp = self.mot_speed_goal
                self.mot_ramp = 0
                return
            elif self.mot_speed_goal > 0:
                # we are want to go slow slow (forward), need to make an initial jump to overcome standing inertia
                self.mot_speed_ramp = self.mot_jump_f
                self.mot_ramp = -1
                return
            else:
                # we are want to go slow slow (reverse), need to make an initial jump to overcome standing inertia
                self.mot_speed_ramp = self.mot_jump_r
                self.mot_ramp = +1
                return
        # this is speed change while moving
        self.mot_speed_ramp = self.mot_speed_goal
        self.mot_ramp = 0

    def RampSpeeed(self):
        self.mot_speed_ramp += self.mot_ramp
        print("Ramp:", self.mot_speed_ramp, self.mot_ramp, self.mot_speed_goal)
        if self.mot_speed_goal > 0:
            if self.mot_ramp > 0:
                if self.mot_speed_ramp >= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp = 0
            else:
                if self.mot_speed_ramp <= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp = 0
        else:
            if self.mot_ramp > 0:		# positive ramp, slowing down toward zero
                if self.mot_speed_ramp >= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp = 0
            else:
                if self.mot_speed_ramp <= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp = 0

    def Estop(self):
        self.motor.write(self.mot_offset)	# Stop motor if on
        self.mot_speed_goal = 0
        self.mot_speed_ramp = 0

    def Motor(self, speed_goal):
        # This sends commands to the hardware motor controller (ESC or H-Bridge).
        # This handles ramping if not handled by hardware motor controller.
        # This only considers forward motion right now.
        # This is fragile. Need to soften states to avoid race conditions.
        # This must be called frequently in order to maintain control of the
        # vehicle. Maybe it should be in its own thread.
        if speed_goal != self.mot_speed_goal:
            # the goal has changed, need to reset ramping variables
            print("New Speed Goal", speed_goal)
            self.NewSpeedGoal(speed_goal)
            self.mot_this_pulse, self.mot_this_tick = self.ConvertSpeedToPulseParameter(self.mot_speed_ramp)
        else:
            # No change in goal, keep ramping toward that
            if self.mot_ramp != 0:
                self.RampSpeeed()
                self.mot_this_pulse, self.mot_this_tick = self.ConvertSpeedToPulseParameter(self.mot_speed_ramp)
        if self.mot_speed_goal == 0:
            self.motor.write(self.mot_offset)	# Stop motor if on
            return
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
        if (self.mot_last_pulse != self.mot_this_pulse) or (self.mot_last_tick != self.mot_this_tick):
            print("Motor:", self.actualPulse, "@", self.mot_tick_clock, "(", self.mot_speed_ramp, "->", self.mot_speed_goal,"Spec:", self.mot_this_pulse, ":", self.mot_this_tick)
        self.mot_tick_clock += 1
        if self.mot_tick_clock > self.tickMask:
            self.mot_tick_clock = 0
        self.mot_last_pulse = self.mot_this_pulse
        self.mot_last_tick = self.mot_this_tick

    def NewSteeringGoal(self, steering_goal):
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

    def Steering(self, steering_goal=None):
        if (steering_goal is None) or (not isinstance(steering_goal, basestring)) or (steering_goal == ''):
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
        self.steering.write(self.steering_offset + direction)
        self.steering_last = direction

class helmsman(vnavs_mqtt.mqtt_node):
    def __init__(self):
        super().__init__(Subscriptions=[vconst.helmsman_orders_topic], SingleThreaded=False, BrokerType='F')
        self.v = vehicle()
        self.speed_goal = 0		# (int) mm/sec
        self.steering_goal = 0		# (int) degrees (0 = straigh, neg is degrees left, pos is degrees right)
        self.deadman_time = 0		# E-Stop if time.time() exceeds this
        self.state = 'd'		# d=deadman active, c=continuous-no timer, t=time out, e=e-stop

    def rmsg_helmsman_orders(self, payload):
        print("ORDERS C:", time.time(), "D:", self.deadman_time, payload)
        if 'state' in payload:
            print("--------------------")
            new_state = payload['state']
            if new_state == 'e':
                print("XXXXXXXXXXXXXXXXXXXXXX")
                self.v.Estop()
                self.state = 'e'
            if new_state in 'dc':
                self.state = new_state
        if self.state == 'e':
            return
        if 'speed' in payload:
            print("SPEED", payload['speed'])
            self.GetGoalSpeed(payload['speed'])
        if 'heading' in payload:
            print ("STEER", payload['heading'])
            self.GetGoalSteering(payload['heading'])
        if 'timer' in payload:
            print("TIMER", payload['timer'])
            timer = int(payload['timer'])
        else:
            timer = 3
        self.deadman_time = time.time() + timer
        if self.state == 't':
            # end timeout when new command arrives
            self.state = 'd'

    def DoLoop(self):
        #print("STATE", self.state)
        if not self.mqttc.connected:
            self.v.Estop()
            return
        if (self.state == 'd') and (time.time() > self.deadman_time):
            self.v.Estop()
            self.state = 't'
            self.stats.Count('timeouts')
            return
        if self.state == 'e':
            self.v.Estop()
            return
        if self.state in 'cd':
            # Speed and Steering goals are set asynchronously via MQTT messages
            self.v.Motor(self.speed_goal)
            self.v.Steering(self.steering_goal)
            self.steering_goal = None		# only send steering goal once
        sleep_secs = 0.1			# This was my first try, slow speeds choppy
        sleep_secs = 2				# This is very slow, for testing
        sleep_secs = 0.001
        sleep_secs = 0.02
        time.sleep(sleep_secs)

    def CleanupLoop(self):
        self.v.Estop()

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
        elif speed_request in 'd':			# decrease speed (forward or reverse)
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
        if isinstance(speed_request, basestring):
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

def Test_Helmsman_Node():
    h = helmsman()
    h.Loop()
    h.Disconnect()

if __name__ == '__main__':
    #Test_Mqtt_Node()
    Test_Helmsman_Node()
