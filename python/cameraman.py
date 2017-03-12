from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import base64
import datetime
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

import vnavs_mqtt
import paho.mqtt.client as mqtt


class cameramn(vnavs_mqtt.mqtt_node):
    def __init__(self):
        super().__init__(Subscriptions=('camerman/take_pic'), Blocking=False)
        self.mode = 's'			# s=single, r=run
        self.burst_fps = 0		# capture speed of last burst
        self.camera_last_fn = None
        self.camera_iso = 800
        self.camera_shutter_speed = 10000
        self.camera = picamera.PiCamera()
        self.configuration_changed = True
        self.run = ''
        self.publish = 'f'		# f=file system, m=mqtt, s=socket
        self.image_ct = 0		# ct of images captured since __init__
        time.sleep(2)			# camera setling time, needed?
        self.timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

    def rmsg_camerman_take_pic(self, msg):
        # should we verify mode and report if a problem?
        try:
            parms = json.loads(msg)
        except ValueError:
            parms = {}
            print("Invalid JSON", `msg`)
        if 'iso' in parms:
            iso = int(parms['iso'])
            if iso != self.camera_iso:
                if (iso >= 0) and (iso <= 800):
                    configuration_changed = True
                    self.camera_iso = iso
        if 'mode' in parms:
            mode = parms['mode']
            if mode in 'sr':
                if mode != self.mode:
                    configuration_changed = True
                    self.mode = mode
        if 'publish' in parms:
            publish = parms['publish']
            if publish in 'fms':
                if publish != self.publish:
                    configuration_changed = True
                    self.publish = publish
        if 'run' in parms:
            run = parms['run']
            if run != self.run:
                configuration_changed = True
                self.run = run
        if 'shutter_speed' in parms:
            shutter_speed = int(parms['shutter_speed'])
            if shutter_speed != self.camera_shutter_speed:
                configuration_changed = True
                self.camera_shutter_speed = shutter_speed
        if configuration_changed:
            self.ConfigureCamera()

    def Loop(self):
        while True:
            if self.configuration_changed:
                # there is a small posibility of a race condition if a new configuration change
                # arrives between this if and setting the flag to False. This should be
                # infrequent enough and quick enough to recover that its not worth managing
                # a propper queue or semaphore.
                self.configuration_changed = False
                self.camera_iso = self.camera_iso
                self.camera_shutter_speed = self.camera_shutter_speed		# microseconds, 1000 = 1ms
                self.camera.vflip = True
                self.camera.hflip = True
            self.ImageBurst()

    def ImageBurst(self):
        # establish paramters for this burst. Since MQTT is running in a separate thread
        # there is a potential race condition if several conflicting instructions arrive
        # in a short period of time. This window is very small and the results easily
        # recoverable so I'm not fixing it now.
        burst_mode = self.mode
        burst_publish = self.publish
        burst_run = self.run
        #
        # Capture some pictures. This might be a single image or a long run of them.
        #
        picfn = 'temp/R%s_%s_%s_S%s_T%s.jpg' % (helmsman.camera_run, run_ct, int(time.clock()*1000), helmsman.speed_goal, helmsman.steering_goal)
        fn = 'R" + self.timestamp
        if self.run != '':
            fn += '_' + self.run
        fn += '_%d_{counter:04d}.jpeg' % self.image_ct
        if burst_publish in 'ms'
            im_format = 'bgr'
            im_dest = io.BytesIO()
        else:
            im_format = 'jpeg'
            im_dest = 'temp/' + fn
        burst_start_time = time.clock()
        burst_ct = 0
        for im_fn in camera.capture_continuous(im_dest, format=im_format, use_video_port=True):
            self.image_ct += 1
            burst_ct += 1
            if burst_publish in 'ms'
                im_fn = fn.format(counter=burst_ct)
            if burst_publish = 'm':
                payload = {}
                payload['filename'] = picfn
                payload['imageBGR64'] = base64.b64encode(im_dest.getvalue())
                (res, mid) = helmsman.mqttc.publish('cameraman/pic_ready', json.dumps(payload))
                if res != mqtt.MQTT_ERR_SUCCESS:
                    print("MQTT Publish Error")
            if burst_publish in 'ms'
                # prepare for next image
                im_dest.truncate()
                im_dest.seek(0)
            if Verbose:
                print("PIC", im_fn)
            if (burst_mode == 's') or (self.configuration_changed):
                break
        if burst_ct >= 10:
            burst_time = time.clock() - burst_start_time
            self.burst_fps = burst_ct / burst_time

    def PublishStatus(self):
              stop_time = time.clock()
              print("%d images %f %5.2d fps" % (image_ct, stop_time - start_time, image_ct / (stop_time - start_time)))
              helmsman.camera_last_fn = picfn
              if prev_mode == 's':
                  # There is a potential race condition here where we miss the second of two
                  # closely timed requests. We will still have taken a photo very recently
                  # and published that. That shoud be good enough.
              time.sleep(sleep_interval)

if __name__ == '__main__':
    h = cameraman()
    h.Connect()
    h.Loop()
    h.Disconnect()

