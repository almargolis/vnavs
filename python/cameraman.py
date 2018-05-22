from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import base64
import cv2
import datetime
import io
import json
import numpy as np
import os
import pickle
import sys
import threading
import time
import traceback

try:
    import picamera
    import picamera.array
except:
    picamera = None

import vnavs_mqtt
import vnavs_const as vconst

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

class macbook_camera(object):
    # This s a wrapper around OpenCv image capture that makes a macbbok
    # built-in camera work like a picamera as closely as I need to.
    # This likely works on the pi too, but is probably slower because it
    # doesn't take full advantage of the hardwre for continuous reads.
    __slots__ = ('colorcode', 'device_id', 'hflip', '_iso', 'vflip',
                        'resolution', 'shutter_speed', 'source_fn',
                        '_video'
                        )
    def __init__(self, device_id=0, resolution=(640,480), source_fn=None):
        # macbook default resolution was 1280x720
        self.colorcode = OpticChiasm.IM_RGB
        self._iso = 0
        self.hflip = False
        self.vflip = False
        self.resolution = resolution
        self.shutter_speed = 0
        self.source_fn = source_fn
        self.device_id = device_id
        if self.source_fn is not None:
            self._video = cv2.VideoCapture(self.source_fn)
        else:
            self._video = cv2.VideoCapture(self.device_id)
            self._video.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
            self._video.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])

    @property
    def exposure_speed(self):
        return 0

    @property
    def iso(self):
        return self._iso

    @iso.setter
    def iso(self, value):
        self._iso = value

    def read(self):
        ret, frame = self._video.read()
        if frame is not None:
            self._iso = self._video.get(cv2.CAP_PROP_ISO_SPEED)
            self.shutter_speed = self._video.get(cv2.CAP_PROP_EXPOSURE)
        return ret, frame

    def capture(self, output, format=None, use_video_port=False, resize=None, splitter_port=0, bayer=False, **options):
        assert isinstance(output, basestring)
        assert format == 'jpeg'
        ret, frame = self.read()
        if frame is None:
            return False
        if isinstance(output, basestring):
            rgb_image = OpticChiasm.BGR2RGB(frame)
            cv2.imwrite(output, rgb_image)
            return True
        else:
            return False

    def capture_opencv(self):
        ret, frame = self.read()
        return frame

    def capture_image(self):
        ret, frame = self.read()
        return OpticChiasm.Image(im=frame, colorcode=OpticChiasm.IM_BGR)

    def capture_continuous(self, output, format=None, use_video_port=False, resize=None, splitter_port=0, burst=False, bayer=False, **options):
        kwargs = options
        kwargs['format'] = format
        kwargs['use_video_port'] = use_video_port
        kwargs['resize'] = resize
        kwargs['splitter_port'] = splitter_port
        kwargs['bayer'] = bayer
        ctr = 0
        while True:
            ctr += 1
            if isinstance(output, basestring):
                path = output.format(counter=ctr)
                if self.capture(path, **kwargs):
                    yield path
                else:
                    raise StopIteration
            else:
                self.capture(output, **kwargs)
                yield 'buffer'

class cameraman(vnavs_mqtt.mqtt_node):
    __slots__ = ('burst_fps_ct', 'burst_fps_rate', 'burst_fps_start_time',
                    'camera', 'camera_resolution',
                    'capture_format', 'capture_publish',
                    'image_ct',
                    'iso',
                    'idle_image_id', 'idle_image_id_max',
                    'last_fn', 'last_format',
                    'loop_format', 'loop_mode', 'loop_publish'
                    'orders_parms', 'post_processes', 'run',
                    'shutter_speed',
                    )
    orders_parms = [
			{'key': 'loop_mode', 'values': ['idle', 'pause', 'run', 'single'] },
			{'key': 'loop_format', 'values': ['bgr', 'jpeg', 'yuv'] },
			{'key': 'loop_publish', 'values': ['file', 'stream'] },
			{'key': 'capture_format', 'values': ['bgr', 'jpeg'] },
			{'key': 'capture_publish', 'values': ['file', 'stream'] },
			{'key': 'run', 'type': 's' },
			{'key': 'iso', 'type': 'i', 'min': 0, 'max': 800 },
			{'key': 'shutter_speed', 'type': 'i' }
    ]

    def __init__(self, Verbose=True):
        super().__init__(Subscriptions=[
						vconst.cameraman_orders_topic,
						vconst.cameraman_process_topic,
						vconst.mission_specs_topic
					],
							SingleThreaded=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.burst_fps_rate = 0			# capture speed of last burst
        self.burst_fps_ct = 0
        self.burst_fps_start_time = time.time()
        self.iso = 100
        self.shutter_speed = 0
        self.camera_resolution = (320, 240)
        self.camera_resolution = (160, 120)
        self.camera_resolution = (640, 480)
        if picamera is not None:
            try:
                self.camera = picamera.PiCamera(resolution=self.camera_resolution)
            except picamera.exc.PiCameraMMALError:
                print("Camera out of resources exception. Camera is probably in-use by another node.")
                sys.exit(1)
        else:
                self.camera = macbook_camera(resolution=self.camera_resolution)
        self.camera.vflip = True
        self.camera.vflip = False
        self.camera.hflip = True
        self.camera.hflip = False
        self.camera.iso = self.iso
        self.do_auto_iso = False
        self.do_auto_iso = True
        self.idle_image_id = 0
        self.idle_image_id_max = 20
        self.iso = self.camera.iso
        self.camera.shutter_speed = self.shutter_speed
        self.loop_mode = 'run'			# idle, single, run, pause
        self.loop_mode = 'idle'			# idle, single, run, pause
        self.loop_format = 'jpeg'		# jpeg, bgr
        self.loop_publish = 'file'
        self.mission_specs = None
        self.mission_hsv_spec = None
        self.capture_format = 'jpeg'		# jpeg, bgr
        self.capture_publish = 'file'		# file, stream
        self.post_processes = []
        self.run = ''				# identifier to add to file names
        self.image_ct = 0			# ct of images captured since __init__
        time.sleep(2)				# camera setling time, needed?
        self.timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        self.last_fn = ''
        self.last_format = ''

    def rmsg_cameraman_process(self, payload):
        if payload['Type'] == 'clear':
            self.post_processes = []
        else:
            self.post_processes.append(payload)

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
        print(payload)
        self.ValidateMessage(self.orders_parms, payload)

    def rmsg_mission_specs(self, payload):
        self.mission_specs = payload
        self.mission_hsv_spec = None

    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which handles exceptions and propper shutdown.
        # if paused, maybe sleep for a bit or changed os.nice. Not sure if important.
        self.ImageBurst()

    def PostProcess(self, process, Im=None, An=None):
        green = (0, 255, 0)
        blue = (0, 0, 255)
        r = Im.shape[0]
        c = Im.shape[1]
        x1 = int(process['x1'])
        y1 = int(process['y1'])
        x2 = int(process['x2'])
        y2 = int(process['y2'])
        if x1 < 0:
            x1 += c
        if y1 < 0:
            y1 += r
        if x2 < 0:
            x2 += c
        if y2 < 0:
            y2 += r
        roi = OpticChiasm.ROI(Im, x1, y1, x2, y2)
        d = OpticChiasm.ReflexEntities(roi, process=process['process'], colors=process['colors'])
        mid_x = int((x2 - x1) / 2)
        sensor_point = d.ProcessLines()
        if sensor_point is not None:
            # e = sensor_point[0] - mid_x		# guide by x
            e = sensor_point[2]
            print("ERR", e, sensor_point)
            if e > 0.85:
                e = 0.85
            if e < 0.45:
                e = 0.45
            s = (e - 0.65) * 200
            payload = {}
            payload['heading'] = -s
            self.Publish(vconst.helmsman_orders_topic, payload)
        if An is not None:
            cv2.rectangle(An, (x1, y1), (x2, y2), green, thickness=2)
            d.AnnotateFullImage(An, x1=x1, y1=y1, linect=1, color=blue)
        return
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
        self.Publish(vconst.helmsman_orders_topic, directions)
        #
        self.last_fn = annotated_fn
        self.last_format = 'jpeg'
        payload = {}
        payload['filename'] = self.last_fn
        payload['format'] = self.last_format
        self.Publish('last', payload)

    def AutoIso(self, img):
        bw = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([bw], [0], None, [256], [0,256])
        rows, cols = bw.shape
        hist_limit = (rows * cols) * 0.5
        pixel_sum = 0
        for ix, this in enumerate(hist):
            pixel_sum += this
            if pixel_sum > hist_limit:
                break
        if ix < 100:
            self.iso += 100
        if self.iso > 800:
            self.iso = 800

    def MakerFaire2018(self, im):
        spec = self.mission_specs		# copy to be thread safe
        print("MakerFaire", spec)

        default_hue = 90
        default_huerange = 30
        default_saturation = 0
        default_saturationrange = 40
        default_value = 170
        default_valuerange = 30
        try:
            crop1_start_x = int(spec['l1x'])
            crop1_start_y = int(spec['l1y'])
            crop1_height = int(spec['l1h'])
            crop1_width = int(spec['l1w'])
            end_y = int(spec['end_y'])
        except:
            return []

        if 'hue' in spec:
            hue = int(spec['hue'])
        else:
            hue = default_hue
        if 'huerange' in spec:
            huerange = int(spec['huerange'])
        else:
            huerange = default_huerange
        if 'saturation' in spec:
            saturation = int(spec['saturation'])
        else:
            saturation = default_saturation
        if 'saturationrange' in spec:
            saturationrange = int(spec['saturationrange'])
        else:
            saturationrange = default_saturationrange
        if 'value' in spec:
            value = int(spec['value'])
        else:
            value = default_value
        if 'valuerange' in spec:
            valuerange = int(spec['valuerange'])
        else:
            valuerange = default_valuerange
        kernel_dim = 11
        iterations = 1
        #
        im_in = OpticChiasm.Image(im, colorcode=OpticChiasm.IM_BGR)
        rect=OpticChiasm.Rect(crop1_start_y-crop1_height, crop1_start_y, crop1_start_x, crop1_start_x+crop1_width)
        if self.mission_hsv_spec is None:
            """
            hsvspec = OpticChiasm.HsvSpec(
                                hue=hue, huerange=huerange,
                                saturation=saturation, saturationrange=saturationrange,
                                value=value, valuerange=valuerange)
            """
            self.mission_hsv_spec = OpticChiasm.NextHsvSpec(im_in.Crop(rect).ImAsHSV())
        rect_list = im_in.ChaseLine(hsvspec=self.mission_hsv_spec, rect=rect, end_y=end_y,
                                kernel_dim=kernel_dim, iterations=iterations)
        list_list = OpticChiasm.ListOfOpenCvRectAsListOfDicts(rect_list)
        print("MAKER ==>", list_list)
        return list_list

    def ImageBurst(self):
        # establish paramters for this burst. Since MQTT is running in a separate thread
        # there is a potential race condition if several conflicting instructions arrive
        # in a short period of time. This window is very small and the results easily
        # recoverable so I'm not fixing it now.
        #
        # Discussion of how to get images captured and processed quickly
        # http://picamera.readthedocs.io/en/release-1.12/recipes2.html
        #
        if self.loop_mode == 'pause':
            return
        burst_loop_mode = self.loop_mode
        burst_loop_format = self.loop_format
        burst_loop_publish = self.loop_publish
        burst_run = self.run
        if burst_loop_mode == 'idle':
            # Rotate through a long-ish series of names to avoid race conditions
            # due to latencies.
            if self.idle_image_id >= self.idle_image_id_max:
                self.idle_image_id = 0
            image_file_name_format = "Idle_%d.jpeg" % (self.idle_image_id)
            self.idle_image_id += 1
        else:
            image_file_name_format = 'R' + self.timestamp
            if self.run != '':
                image_file_name_format += '_' + self.run
            image_file_name_format += '_%d_{counter:04d}.%s' % (self.image_ct, burst_loop_format)
        if burst_loop_publish == 'stream':
            if burst_loop_format == 'yuv':
                burst_dest = picamera.array.PiYUVArray(self.camera)
            elif burst_loop_format in [OpticChiasm.IM_RGB, OpticChiasm.IM_BGR]:
                burst_dest = picamera.array.PiRGBArray(self.camera)
            else:				# jpeg
                burst_dest = io.BytesIO()
        else:
            assert burst_loop_format == 'jpeg'
            burst_dest = os.path.join(self.imageDir, image_file_name_format)
        #
        # Capture some pictures. This might be a single image or a long run of them.
        #
        if self.verbose:
            print("READY", burst_loop_mode, burst_loop_format, burst_loop_publish, burst_dest)
        last_time = 0
        for im_path in self.camera.capture_continuous(burst_dest, format=burst_loop_format, use_video_port=True):
            self.image_ct += 1
            # mqtt can change values asynchronously. copy so values are consistent during capture
            capture_format = self.capture_format
            capture_publish = self.capture_publish
            if burst_loop_publish == 'file':
                im_fn = os.path.basename(im_path)
                # the file is already written, make sure its the correct format
                assert capture_format == burst_loop_format
            else:
                # capture_continuous returns burst_dest if it is a buffer
                im_fn = image_file_name_format.format(counter=self.image_ct)
                print("CAPT", im_fn, self.imageDir)
                im_path = os.path.join(self.imageDir, im_fn)
                file_written = True
                if capture_format == 'jpeg':
                    # to keep understandable, keep following if consistent with buffer creation if
                    if burst_loop_format == 'yuv':
                        cv2.imwrite(im_path, burst_dest.rgb_array)
                    elif burst_loop_format in [OpticChiasm.IM_RGB, OpticChiasm.IM_BGR]:
                        cv2.imwrite(im_path, burst_dest.array)
                    else:
                        try:
                            f = open(im_fn, 'wb')
                            f.write(burst_dest.getvalue())
                            f.close()
                        except IOError as e:
                            # IOError: [Errno 28] Out of disk space
                            if e.errno == 28:
                                file_written = False
                    if file_written:
                        self.last_fn = im_fn
                        self.last_format = capture_format
                        payload = {}
                        payload['filename'] = im_fn
                        payload['capture_format'] = capture_format
                        payload['capture_publish'] = capture_publish
                        self.Publish(vconst.cameraman_pic_ready_topic, payload)
                        last_time = time.time()
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
            #
            # At this point we have an image captured and in the requested format.
            #
            rect_list = None
            if (len(self.post_processes) > 0) or (burst_loop_mode == 'idle') or True:
                # we need an OpenCv image for post processing
                if burst_loop_publish == 'file':
                    img = cv2.imread(im_path)
            if len(self.post_processes) > 0:
                annotated = img.copy()
                for this in self.post_processes:
                    self.PostProcess(this, Im=img, An=annotated)
                pos = im_fn.rfind('.')
                an_fn = im_fn[:pos] + '-A' + im_fn[pos:]
                an_path = os.path.join(self.imageDir, an_fn)
                cv2.imwrite(an_path, annotated)
            else:
                rect_list = self.MakerFaire2018(img)
                annotated = None
            #
            # Imsge process, now publish
            #
            self.burst_fps_ct += 1
            burst_elapsed_time = time.time() - self.burst_fps_start_time
            self.burst_fps_rate = self.burst_fps_ct / burst_elapsed_time
            payload = {}
            payload['filename'] = im_fn
            if annotated is not None:
                payload['annotated'] = an_fn
            payload['iso'] = self.camera.iso
            payload['shutter_speed'] = self.camera.exposure_speed
            payload['capture_format'] = capture_format
            payload['capture_publish'] = capture_publish
            payload['capture_fps'] = self.burst_fps_rate
            payload['center_line'] = rect_list
            self.Publish(vconst.cameraman_pic_ready_topic, payload)
            print("P", self.mqttc.connected)
            if self.camera.iso != self.iso:
                # The camera may not use the exact ISO specified. Save the corrected value in
                # self.iso so we don't keep repeating the request.
                print("CHANGING ISO", self.camera.iso, self.iso)
                self.camera.iso = self.iso
                self.iso = self.camera.iso
            if self.camera.shutter_speed != self.shutter_speed:
                self.camera.shutter_speed = self.shutter_speed
            if burst_loop_publish == 'stream':
                # prepare for next image. This is needed even when not published
                burst_dest.truncate()
                burst_dest.seek(0)   # ?? needed for io.Bytes?? Required for PiRGBArray for subsequent images
            if burst_loop_mode == 'idle':
                #print("END IDLE")
                # need conditional to determin conversion paramter for different formats
                if self.do_auto_iso:
                    self.AutoIso(img)
                # idle takes one image per "burst". Mainly to control file names.
                break
            if burst_loop_mode == 'single':
                # enter paused mode if we have taken our single picture
                self.loop_mode = 'pause'
                break
            if burst_loop_mode != self.loop_mode:
                break

if __name__ == '__main__':
    h = cameraman()
    h.Loop()
    h.Disconnect()
