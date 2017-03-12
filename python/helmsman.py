from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import base64
import json
import traceback
import io
import sys
import threading
import time
import cv2

from pyfirmata import Arduino, util

import picamera
import picamera.array

import OpticChiasm
import vnavs_mqtt
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
        self.st_straight = 90
        # speed in mm/second - depends on vehicle and battery condition
        # For now speed is just a number.
        # Zero is stopped, 1 is crawl, 2... incrementally faster (negative is reverse)
        self.mot_speed_goal = 0			# we may be ramping toward this
        self.mot_speed_ramp = 0			# current speed, on way to goal
        self.speed_max = 13411			# 30mph / 13.4112 meters/second
        self.steering_increment	= 10		# degrees of casual steering adjustment
        self.steering_max = 90			# 60 degrees left or right
        self.steering_last = 0
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

    def NewGoal(self, speed_goal):
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

    def Motor(self, speed_goal):
        # This sends commands to the hardware motor controller (ESC or H-Bridge).
        # This handles ramping if not handled by hardware motor controller.
        # This only considers forward motion right now.
        # This is fragile. Need to soften states to avoid race conditions.
        # This must be called frequently in order to maintain control of the
        # vehicle. Maybe it should be in its own thread.
        if speed_goal != self.mot_speed_goal:
            # the goal has changed, need to reset ramping variables
            self.NewGoal(speed_goal)
            self.mot_this_pulse, self.mot_this_tick = self.ConvertSpeedToPulseParameter(self.mot_speed_ramp)
        else:
            # No change in goal, keep ramping toward that
            if self.mot_ramp != 0:
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
            # we want to coast on this tick
            self.actualPulse = self.mot_offset
        self.motor.write(self.actualPulse)
        if (self.mot_last_pulse != self.mot_this_pulse) or (self.mot_last_tick != self.mot_this_tick):
            print("Motor:", self.actualPulse, "@", self.mot_tick_clock, "(", self.mot_speed_ramp, "->", self.mot_speed_goal,"Spec:", self.mot_this_pulse, ":", self.mot_this_tick)
        self.mot_tick_clock += 1
        if self.mot_tick_clock > self.tickMask:
            self.mot_tick_clock = 0
        self.mot_last_pulse = self.mot_this_pulse
        self.mot_last_tick = self.mot_this_tick

    def Steering(self, direction):
        if direction != self.steering_last:
            print("Steer:", direction)
        self.steering.write(90+direction)
        self.steering_last = direction

class helmsman(vnavs_mqtt.mqtt_node):
    def __init__(self):
        super().__init__(Subscriptions=('helmsman/set_speed', 'helmsman/steer', 'helmsman/take_pic'), Blocking=False)
        self.v = vehicle()
        self.camera_mode = 's'		# set by helmsman, s=single, r=run
        self.camera_snap = False	# set by helmsman, cleared by cameraman
        self.camera_last_fn = None	# set by camerman
        self.camera_iso = 800
        self.camera_shutter_speed = 10000
        self.camera_run = str(int(time.clock() * 1000))		# set by helmsman, id for series of pics
        self.speed_goal = 0		# (int) mm/sec
        self.steering_goal = 0		# (int) degrees (0 = straigh, neg is degrees left, pos is degrees right)
        self.camera = threading.Thread(target=cameraman, args=(self,))
        self.camera.start()

    def rmsg_helmsman_take_pic(self, msg):
        # should we verify mode and report if a problem?
        try:
            parms = json.loads(msg)
        except ValueError:
            parms = {}
            print("Invalid JSON", `msg`)
        if 'iso' in parms:
            iso = int(parms['iso'])
            self.camera_iso = iso
        if 'shutter_speed' in parms:
            shutter_speed = int(parms['shutter_speed'])
            self.camera_shutter_speed = shutter_speed
        self.camera_snap = True

class cameraman(object):
      def __init__(self, helmsman, Verbose=False):
          self.helmsman = helmsman
          self.verbose = Verbose
    # This will run in its own thread.
    # Touch helmsman as little as possible to avoid thread glitches.
    Verbose = True
    with picamera.PiCamera() as camera:
        camera_iso = 800
        camera_shutter_speed = helmsman.camera_shutter_speed		# microseconds, 1000 = 1ms
        camera.vflip = True
        camera.hflip = True
        # Camera warm-up time
        time.sleep(2)
        prev_mode = 'x'				# x is invalid, forces startup in single mode
        while True:
            if camera_iso != helmsman.camera_iso:
                new_iso = helmsman.camera_iso
                if (new_iso >= 0) and (new_iso <= 800):
                    camera_iso = new_iso
                    camera.iso = camera_iso
            if camera_shutter_speed != helmsman.camera_shutter_speed:
               camera_shutter_speed = helmsman.camera_shutter_speed
               camera.shutter_speed = camera_shutter_speed
            if helmsman.camera_mode != prev_mode:
                if prev_mode == 's':
                    # switching to run mode
                    prev_mode = 'r'
                    sleep_interval = 0.1
                    run_ct = 0
                else:
                    # switching to single mode
                    prev_mode = 's'
                    sleep_interval = 10
            if prev_mode == 's':
                picfn = 'temp/single.jpg'
            else: 
                run_ct += 1
                picfn = 'temp/R%s_%s_%s_S%s_T%s.jpg' % (helmsman.camera_run, run_ct, int(time.clock()*1000), helmsman.speed_goal, helmsman.steering_goal)
            if (prev_mode == 'r') or (helmsman.camera_snap == True):
              image_ct = 0
              start_time = time.clock()
              stream = io.BytesIO()
              for foo in camera.capture_continuous(stream, format='bgr', use_video_port=True):
                  image_ct += 1
                  payload = {}
                  payload['filename'] = picfn
                  #payload['imageBGR64'] = base64.b64encode(stream.getvalue())
                  res = 0
                  #(res, mid) = helmsman.mqttc.publish('helmsman/pic_ready', json.dumps(payload))
                  if res != mqtt.MQTT_ERR_SUCCESS:
                      print("MQTT Publish Error")
                  stream.truncate()
                  stream.seek(0)
                  if Verbose:
                      print("PIC", picfn)
                  if image_ct >= 10:
                      break
              stop_time = time.clock()
              print("%d images %f %5.2d fps" % (image_ct, stop_time - start_time, image_ct / (stop_time - start_time)))
              helmsman.camera_last_fn = picfn
              if prev_mode == 's':
                  # There is a potential race condition here where we miss the second of two
                  # closely timed requests. We will still have taken a photo very recently
                  # and published that. That shoud be good enough.
                  helmsman.camera_snap = False
            time.sleep(sleep_interval)

class helmsman(vnavs_mqtt.mqtt_node):
    def __init__(self):
        super().__init__(Subscriptions=('helmsman/set_speed', 'helmsman/steer', 'helmsman/take_pic'), Blocking=False)
        self.v = vehicle()
        self.camera_mode = 's'		# set by helmsman, s=single, r=run
        self.camera_snap = False	# set by helmsman, cleared by cameraman
        self.camera_last_fn = None	# set by camerman
        self.camera_iso = 800
        self.camera_shutter_speed = 10000
        self.camera_run = str(int(time.clock() * 1000))		# set by helmsman, id for series of pics
        self.speed_goal = 0		# (int) mm/sec
        self.steering_goal = 0		# (int) degrees (0 = straigh, neg is degrees left, pos is degrees right)
        self.camera = threading.Thread(target=cameraman, args=(self,))
        self.camera.start()

    def rmsg_helmsman_take_pic(self, msg):
        # should we verify mode and report if a problem?
        try:
            parms = json.loads(msg)
        except ValueError:
            parms = {}
            print("Invalid JSON", `msg`)
        if 'iso' in parms:
            iso = int(parms['iso'])
            self.camera_iso = iso
        if 'shutter_speed' in parms:
            shutter_speed = int(parms['shutter_speed'])
            self.camera_shutter_speed = shutter_speed
        self.camera_snap = True

    def rmsg_helmsman_set_speed(self, msg):
        self.GetGoalSpeed(msg)

    def rmsg_helmsman_steer(self, msg):
        self.GetGoalSteering(msg)

    def Loop(self):
        try:
            while True:
                self.Process()
                sleep_secs = 0.1			# This was my first try, slow speeds choppy
                sleep_secs = 2				# This is very slow, for testing
                sleep_secs = 0.01
                time.sleep(sleep_secs)
        except:
            traceback.print_exc()
        self.v.Estop()
        self.camera.stop()

    def Process(self):
        # Speed and Steering goals are set asynchronously via MQTT messages
        if self.speed_goal == 0:
            self.camera_mode = 's'
        else:
            self.camera_mode = 'r'
            self.camera_run = str(int(time.clock() * 1000))
        self.v.Motor(self.speed_goal)
        self.v.Steering(self.steering_goal)

    def ProcessImage(self):
        brain = OpticChiasm.ImageAnalyzer()
        brain.do_save_snaps = False
        #brain.FindLines(image(

    def GetGoalSpeed(self, speed_request):
        # from Loop(). It is possible that Loop() has not seen or acted upon
        # the previous goal. This means care must be exercised when processing
        # incremental requests. A subsequent +1 could be sent due to impatience
        # rather than an actual intent to increment speed in additiion to any
        # pending increments. There shouldn't be much latency, but for big
        # fast bots, some caution is in order.
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
        else:
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
    h.Connect()
    h.Loop()
    h.Disconnect()

if __name__ == '__main__':
    #Test_Mqtt_Node()
    Test_Helmsman_Node()
