from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import base64
import cv2
import datetime
import io
import json
import numpy
import os
import pickle
import sys
import threading
import time
import traceback


import picamera
import picamera.array

import vnavs_mqtt
import paho.mqtt.client as mqtt

import OpticChiasm

import signal
print("CONFIGURING SIGNAL")
stop_process = False
def signal_handler(signal, frame):
        global stop_process
        print('You pressed Ctrl+C!')
        stop_process = True
        vnavs_mqtt.stop_process = True
signal.signal(signal.SIGINT, signal_handler)

RACE_SPEED = 2
RACE_STEERING_2 = 0.1

#
# Streamer() is the socket_xfer writer function which runs in its own process.

class cameraman(vnavs_mqtt.mqtt_node):
    orders_parms = [
			{'key': 'loopMode', 'values': ['pause', 'run', 'single'] },
			{'key': 'loopFormat', 'values': ['bgr', 'jpeg', 'yuv'] },
			{'key': 'loopPublish', 'values': ['file', 'stream'] },
			{'key': 'captureMode', 'values': ['none', 'run', 'single'] },
			{'key': 'captureFormat', 'values': ['bgr', 'jpeg'] },
			{'key': 'capturePublish', 'values': ['file', 'mqtt', 'sample', 'stream'] },
			{'key': 'run', 'type': 's' },
			{'key': 'iso', 'type': 'i', 'min': 0, 'max': 800 },
			{'key': 'shutterSpeed', 'type': 'i' }
    ]

    def __init__(self, Verbose=True):
        super().__init__(Subscriptions=['cameraman/orders', 'cameraman/ask_last', 'cameraman/process'],
							SingleThreaded=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.burst_fps = 0			# capture speed of last burst
        self.camera_last_fn = None
        self.iso = 100
        self.shutterSpeed = 0
        self.camera_resolution = (720, 480)
        self.camera = picamera.PiCamera()
        self.camera.vflip = True
        self.camera.hflip = True
        self.camera.iso = self.iso
        self.iso = self.camera.iso
        self.camera.shutter_speed = self.shutterSpeed
        self.loopMode = 'pause'			# single, run, pause
        self.loopFormat = 'jpeg'		# jpeg, bgr
        self.loopPublish = 'file'
        self.captureMode = 'none'		# n=none, s=single, r=run
        self.captureFormat = 'jpeg'		# jpeg, bgr
        self.capturePublish = 'file'		# f=file system, m=mqtt, s=streamer
        self.post_processes = []
        self.run = ''				# identifier to add to file names
        self.image_ct = 0			# ct of images captured since __init__
        time.sleep(2)				# camera setling time, needed?
        self.timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        self.last_fn = ''
        self.last_format = ''
        self.imageDir = self.config.get("Cameraman", "ImageDir")

    def rmsg_cameraman_process(self, payload):
        if payload['type'] = 'clear':
            self.post_processes = []
        else:
            self.post_processes.append(payload)

    def rmsg_cameraman_ask_last(self, payload):
        payload = {}
        payload['filename'] = self.last_fn
        payload['CaptureFormat'] = self.last_format
        self.Publish('last', payload)
        print("ASK LAST")

    def ValidateMessage(self, specs, payload):
        for this_spec in specs:
            fld_error = False
            key = this_spec['key']
            if key in payload:
                value = payload[key]
                if 'type' in this_spec:
                    p_type = this_spec['type']
                    if p_type == 'i':
                        value = int(value)
                    elif p_type == 's':
                        value = str(value)
                if 'min' in this_spec:
                    p_min = this_spec['min']
                    if value < p_min:
                        fld_error = True
                        print("Payload Error @ %s, '%s' < '%s'." % (key, value, p_min))
                if 'max' in this_spec:
                    p_max = this_spec['max']
                    if value > p_max:
                        fld_error = True
                        print("Payload Error @ %s, '%s' > '%s'." % (key, value, p_max))
                if 'values' in this_spec:
                    if value not in this_spec['values']:
                        fld_error = True
                        print("Payload Error @ %s, invalid value '%s'." % (key, value))
                if not fld_error:
                    setattr(self, key, value)

    def rmsg_cameraman_orders(self, payload):
        self.ValidateMessage(self.orders_parms, payload)

    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which handles exceptions and propper shutdown.
        # if paused, maybe sleep for a bit or changed os.nice. Not sure if important.
        self.ImageBurst()

    def PostProcess(self, process, burst_dest, im_fn):
        roi = OpticChiasm.ROI(burst_dest, process['x1'], process['y1'], process['x2'], process['y2'])
        d = OpticChiasm.Race(burst_dest.array.copy())
        d.ProcessLines()
        fpx = im_fn[:-4]
        im_fn = fpx + '-A.jpeg'
        im_path = os.path.join(self.imageDir, im_fn)
        cv2.imwrite(im_path , d.original)
        annotated_fn = fpx + '-B.jpeg'
        annotated_path = os.path.join(self.imageDir, annotated_fn)
        cv2.imwrite(annotated_path , d.annotated)
        directions = {}
        directions['timeout'] = 3
        directions['speed'] = RACE_SPEED
        avg_slope = int(d.avg_slope)
        if (abs(avg_slope) > 4) or (d.slope_ct < 1):
            directions['heading'] = 'AWS'
        else:
            if abs(avg_slope) > 2:
                steering_angle = "1"
            elif abs(avg_slope) > RACE_STEERING_2:
                steering_angle = "2"
            else:
                steering_angle = "3"
            if avg_slope > 0:
                directions['heading'] = 'RR-' + steering_angle
            else:
                directions['heading'] = 'RL+' + steering_angle
        self.Publish('orders', directions, source='helmsman')
        #
        self.last_fn = annotated_fn
        self.last_format = 'jpeg'
        payload = {}
        payload['filename'] = self.last_fn
        payload['format'] = self.last_format
        self.Publish('last', payload)

    def ImageBurst(self):
        # establish paramters for this burst. Since MQTT is running in a separate thread
        # there is a potential race condition if several conflicting instructions arrive
        # in a short period of time. This window is very small and the results easily
        # recoverable so I'm not fixing it now.
        #
        # Discussion of how to get images captured and processed quickly
        # http://picamera.readthedocs.io/en/release-1.12/recipes2.html
        #
        if self.loopMode == 'pause':
            return
        burst_loopMode = self.loopMode
        burst_loopFormat = self.loopFormat
        burst_loopPublish = self.loopPublish
        burst_run = self.run
        fn = 'R' + self.timestamp
        if self.run != '':
            fn += '_' + self.run
        fn += '_%d_{counter:04d}.%s' % (self.image_ct, burst_loopFormat)
        if burst_loopPublish == 'stream':
            if burst_loopFormat == 'yuv':
                burst_dest = picamera.array.PiYUVArray(self.camera)
            elif burst_loopFormat in ['rgb', 'bgr']:
                burst_dest = picamera.array.PiRGBArray(self.camera)
            else:				# jpeg
                burst_dest = io.BytesIO()
        else:
            assert burst_loopFormat == 'jpeg'
            burst_dest = os.path.join(self.imageDir, fn)
        #
        # Capture some pictures. This might be a single image or a long run of them.
        #
        burst_start_time = time.time()
        burst_ct = 0
        print("READY", burst_loopMode, burst_loopFormat, burst_loopPublish, burst_dest)
        last_time = 0
        for im_fn in self.camera.capture_continuous(burst_dest, format=burst_loopFormat, use_video_port=True):
            self.image_ct += 1
            burst_ct += 1
            # mqtt can change values asynchronously. copy so values are consistent during capture
            captureMode = self.captureMode
            captureFormat = self.captureFormat
            capturePublish = self.capturePublish
            if captureMode != 'none':
                print("MODE", capturePublish)
                if burst_loopPublish == 'stream':
                    # Assign file name same as picamera.capture() to file
                    im_fn = fn.format(counter=self.image_ct)
                if capturePublish in ['file', 'sample']:
                    if burst_loopPublish == 'file':
                        # the file is already written, make sure its the correct format
                        assert captureFormat == burst_loopFormat
                        im_path = im_fn
                        im_fn = os.path.split(im_path)[1]
                    else:
                        if capturePublish == 'sample':
                            im_publish_fn = 'sample.' + burst_loopFormat
                            im_publish_path = os.path.join(self.imageDir, im_publish_fn)
                            im_fn = 'temp.' + im_publish_fn
                        if captureFormat == 'jpeg':
                            im_fn = os.path.splitext(im_fn)[0] + '.' + captureFormat
                            im_path = os.path.join(self.imageDir, im_fn)
                            # to keep understandable, keep following if consistent with buffer creation if
                            if burst_loopFormat == 'yuv': 
                                cv2.imwrite(im_path, burst_dest.rgb_array)
                            elif burst_loopFormat in ['rgb', 'bgr']:
                                cv2.imwrite(im_path, burst_dest.array)
                            else:
                                f = open(im_fn, 'wb')
                                f.write(burst_dest.getvalue())
                                f.close()
                            if capturePublish == 'sample':
                                # mission_control.py was reading sample.jpeg while this was writing a new one.
                                # even this fails frequently. maybe round-robin a few file names.
                                # this would be a nice mode to have in order to observe images without
                                # running out of disk space. there is a good amount of lag and no good
                                # locking system with nfs/afp sharing path.
                                os.rename(im_path, im_publish_path)
                                im_fn = im_publish_fn
                    self.last_fn = im_fn
                    self.last_format = captureFormat
                    payload = {}
                    payload['filename'] = im_fn
                    payload['captureFormat'] = captureFormat
                    payload['capturePublish'] = capturePublish
                    if time.time() - last_time > 2:
                        self.Publish('pic_ready', payload)
                        last_time = time.time()
                for this in self.post_processes:
                    self.PostProcess(this)
                """
                if burst_publish == 's':
                    #buffer = burst_dest.getvalue()
                    buffer = burst_dest.array
                    #buffer = pickle.dumps(burst_dest.array)
                    payload = {}
                    payload['filename'] = im_fn
                    payload['format'] = burst_format
                    payload['publish'] = burst_publish
                    payload['buflen'] = len(buffer)
                    self.streamer.write(json.dumps(payload) + chr(26) + buffer)
                """
                if self.verbose:
                    print("PIC", im_fn)
            if self.camera.iso != self.iso:
                # The camera may not use the exact ISO specified. Save the corrected value in
                # self.iso so we don't keep repeating the request.
                self.camera.iso = self.iso
                self.iso = self.camera.iso
            if self.camera.shutter_speed != self.shutterSpeed:
                self.camera.shutter_speed = self.shutterSpeed
            if burst_loopPublish == 'stream':
                # prepare for next image. This is needed even when not published
                burst_dest.truncate()
                burst_dest.seek(0)   # ?? needed for io.Bytes?? Required for PiRGBArray for subsequent images
            if self.captureMode == 'single':
                self.captureMode = 'none'
            if burst_loopMode == 'single':
                # enter paused mode if we have taken our single picture
                self.loopMode = 'pause'
                break
        if burst_ct >= 10:
            burst_time = time.time() - burst_start_time
            self.burst_fps = burst_ct / burst_time

    def PublishStatus(self):
              stop_time = time.time()
              print("%d images %f %5.2d fps" % (image_ct, stop_time - start_time, image_ct / (stop_time - start_time)))
              helmsman.camera_last_fn = picfn
              #if prev_mode == 's':
                  # There is a potential race condition here where we miss the second of two
                  # closely timed requests. We will still have taken a photo very recently
                  # and published that. That shoud be good enough.
              time.sleep(sleep_interval)

if __name__ == '__main__':
    h = cameraman()
    h.Loop()
    h.Disconnect()

