from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)
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
        self.mot_offset = 90
        self.mot_goal = 0		# This is the pulse we are ramping towards
        self.mot_jump_f = 5			# This is the minimum speed to start moving from stop
        self.mot_jump_f = 10			# This is the minimum speed to start moving from stop
        self.mot_jump_r = -5			# This is the minimum speed to start moving from stop
        self.mot_ramp = 0			# Current ramping increment
        self.mot_this_pulse = 0
        self.mot_last_pulse = 0
        self.motor.write(self.mot_offset)	# Stop motor if on
        self.steering = self.board.get_pin('d:10:s')
        self.st_straight = 90
        # speed in mm/second - depends on vehicle and battery condition
        self.speed_crawl_forward = 5		# minimum start moving speed
        self.speed_crawl_forward = 8		# minimum start moving speed
        self.speed_crawl_reverse = -5		# minimum start moving speed
        self.speed_increment = 1		# a reasonable quantity for "go a bit faster"
        self.speed_max = 13411			# 30mph / 13.4112 meters/second
        self.steering_increment	= 10		# degrees of casual steering adjustment
        self.steering_max = 60			# 60 degrees left or right

    def ConvertSpeedToPulseParameter(self, speed):
        # for now, speed is just arduino servo increment value.
        # Degree of servo turn, but cetnered at 0 instead of 90.
        return speed

    def self.NewGoal(speed_goal)
        if pulse_goal == 0:
            # we want to stop
            self.mot_this_pulse = pulse_goal
            self.mot_goal = pulse_goal
            self.mot_ramp = 0
            return
        if (pulse_goal != 0) and (self.mot_this_pulse == 0):
            # we are starting to move
            if ((pulse_goal > 0) and (pulse_goal > self.mot_jump_f)) \
			or ((pulse_goal < 0) and (pulse_goal < self.mot_jump_r)):
                # we are starting fast, so just do it
                self.mot_this_pulse = pulse_goal
                self.mot_goal = pulse_goal
                self.mot_ramp = 0
                return
            else:
                # we are starting slow, need to make an initial jump to overcome standing inertia
                self.mot_goal = pulse_goal
                if pulse_goal > 0:
                    self.mot_this_pulse = self.mot_jump_f
                    self.mot_ramp = -1
                else:
                    self.mot_this_pulse = self.mot_jump_r
                    self.mot_ramp = +1
                return
        # this is speed change while moving
        self.mot_this_pulse = pulse_goal
        self.mot_goal = pulse_goal
        self.mot_ramp = 0

    def RampSpeeed(self):
        self.mot_this_pulse += self.mot_ramp
        print("Ramp:", self.mot_this_pulse, self.mot_ramp, self.mot_goal)
        if self.mot_goal > 0:
            if self.mot_ramp > 0:
                if self.mot_this_pulse >= self.mot_goal:
                    self.mot_this_pulse = self.mot_goal
                    self.mot_ramp = 0
            else:
                if self.mot_this_pulse <= self.mot_goal:
                    self.mot_this_pulse = self.mot_goal
                    self.mot_ramp = 0
        else:
            if self.mot_ramp > 0:		# positive ramp, slowing down toward zero
                if self.mot_this_pulse >= self.mot_goal:
                    self.mot_this_pulse = self.mot_goal
                    self.mot_ramp = 0
            else:
                if self.mot_this_pulse <= self.mot_goal:
                    self.mot_this_pulse = self.mot_goal
                    self.mot_ramp = 0

    def Motor(self, speed_goal):
        # This sends commands to the hardware motor controller (ESC or H-Bridge).
        # This handles ramping if not handled by hardware motor controller.
        # This only considers forward motion right now.
        # This is fragile. Need to soften states to avoid race conditions.
        pulse_goal = self.ConvertSpeedToPulseParameter(speed_goal)
        if pulse_goal != self.mot_goal:
            # the goal has changed, need to reset ramping variables
            self.NewGoal(speed_goal)
        else:
            # No change in goal, keep ramping toward that
            if self.mot_ramp != 0:
                self.RampSpeeed()

        # we know our pulse requirement, tell the hardware
        self.motor.write(self.mot_offset + self.mot_this_pulse)
        if self.mot_last_pulse != self.mot_this_pulse:
           print('Motor: ', self.mot_this_pulse)
           self.mot_last_pulse = self.mot_this_pulse

    def Steering(self, direction):
         self.steering.write(90+direction)

def cameraman(helmsman):
    # This will run in its own thread.
    # Touch helmsman as little as possible to avoid thread glitches.
    with picamera.PiCamera() as camera:
        camera.iso = 800
        camera.shutter_speed = 10000		# microseconds, 1000 = 1ms
        camera.vflip = True
        # Camera warm-up time
        time.sleep(2)
        prev_mode = 'x'				# x is invalid, forces startup in single mode
        while True:
            if helmsman.camera_mode != prev_mode:
                if prev_mode == 's':
                    # switching to run mode
                    prev_mode = 'r'
                    sleep_interval = 0.1
                    run_ct = 0
                else:
                    # switching to single mode
                    prev_mode = 's'
                    sleep_interval = 1
            if prev_mode == 's':
                picfn = 'temp/single.jpg'
            else: 
                run_ct += 1
                picfn = 'temp/R%s_%s_%s_S%s_T%s.jpg' % (helmsman.camera_run, run_ct, int(time.clock()*1000), helmsman.speed_goal, helmsman.steering_goal)
            #my_stream = io.BytesIO()
            #camera.capture(my_stream, 'jpeg')
            if (prev_mode == 'r') or (helmsman.camera_snap == True):
              camera.capture(picfn)
              (res, mid) = helmsman.mqttc.publish('helmsman/pic_ready', picfn)
              print("PIC", picfn)
              if res != mqtt.MQTT_ERR_SUCCESS:
                  print("MQTT Publish Error")
              """
              with picamera.array.PiRGBArray(camera) as stream:
                  print(time.clock())
                  camera.capture(stream, format='bgr')
                  print(time.clock())
                  brain = OpticChiasm.ImageAnalyzer()
                  brain.do_save_snaps = False
                  brain.img_crop=(250,450)
                  brain.FindLines(image=stream.array)
                  print(time.clock())
                  cv2.imwrite(picfn, brain.img_annotated)
                  print(time.clock())
              """
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
        self.camera_run = str(int(time.clock() * 1000))		# set by helmsman, id for series of pics
        self.speed_goal = 0		# (int) mm/sec
        self.steering_goal = 0		# (int) degrees (0 = straigh, neg is degrees left, pos is degrees right)
        self.camera = threading.Thread(target=cameraman, args=(self,))
        self.camera.start()

    def rmsg_helmsman_take_pic(self, msg):
        # should we verify mode and report if a problem?
        self.camera_snap = True

    def rmsg_helmsman_set_speed(self, msg):
        self.GetGoalSpeed(msg)
        print(self.speed_goal)

    def rmsg_helmsman_steer(self, msg):
        self.GetGoalSteering(msg)
        print(self.steering_goal)

    def Loop(self):
        # Speed and Steering goals are set asynchronously via MQTT messages
        while True:
            if self.speed_goal == 0:
                self.camera_mode = 's'
            else:
                self.camera_mode = 'r'
                self.camera_run = str(int(time.clock() * 1000))
            self.v.Motor(self.speed_goal)
            self.v.Steering(self.steering_goal)
            time.sleep(0.1)

    def ProcessImage(self):
        brain = OpticChiasm.ImageAnalyzer()
        brain.do_save_snaps = False
        #brain.FindLines(image(

    def GetGoalSpeed(self, speed_request):
        # This gets called when an MQTT message arrives, which is asyncronous
        # from Loop(). It is possible that Loop() has not seen or acted upon
        # the previous goal. This means care must be exercised when processing
        # incremental requests. A subsequent +1 could be sent due to impatience
        # rather than an actual intent to increment speed in additiion to any
        # pending increments. There shouldn't be much latency, but for big
        # fast bots, some caution is in order.
        if speed_request in '+=':
          speed_goal = self.speed_goal + self.v.speed_increment
        elif speed_request == '-':
          speed_goal = self.speed_goal - self.v.speed_increment
        elif speed_request in 'fd':			# move forward slowly
          if self.speed_goal <= 0:
            speed_goal = self.v.speed_crawl_forward
          else:
            if speed_request == 'f':			# move reveerse slowly
              speed_goal = self.v.speed_crawl_forward + 1
            else:
              speed_goal = self.v.speed_crawl_forward
        elif speed_request == 'r':			# move reveerse slowly
          speed_goal = self.v.speed_crawl_reverse
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
