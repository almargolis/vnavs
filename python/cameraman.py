#from __future__ import absolute_import, division, print_function
#from past.builtins import basestring    # pip install future
#from builtins import (bytes, str, open, super, range,
#                      zip, round, input, int, pow, object)

import base64
import cv2
import io
import json
import numpy as np
import os
picamera = None					# imported below if needed
import pickle
import sys
import threading
import time
import traceback

import vnavs_mqtt as vmqtt
import vnavs_const as vconst
import vnavs_data as vdata

import OpticChiasm

import signal
print("CONFIGURING SIGNAL")
stop_process = False
def signal_handler(signal, frame):
        global stop_process
        print('You pressed Ctrl+C!')
        stop_process = True
        vmqtt.stop_process = True
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
        assert isinstance(output, str)
        assert format == 'jpeg'
        ret, frame = self.read()
        if frame is None:
            return False
        if isinstance(output, str):
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
            if isinstance(output, str):
                path = output.format(counter=ctr)
                if self.capture(path, **kwargs):
                    yield path
                else:
                    raise StopIteration
            else:
                self.capture(output, **kwargs)
                yield 'buffer'

class CameramanOrdersDict(vdata.Dict):
    def __init__(self):
        super().__init__()
        self.AddAttrib(vdata.DataAttribStr('loop_mode', 'idle',
                        values=['idle', 'pause', 'run', 'single']))
        self.AddAttrib(vdata.DataAttribStr('loop_format', 'jpeg',
                        values=['bgr', 'jpeg', 'yuv']))
        self.AddAttrib(vdata.DataAttribStr('loop_publish', 'file',
                        values=['file', 'stream']))
        self.AddAttrib(vdata.DataAttribStr('capture_format', 'jpeg',
                        values=['bgr', 'jpeg']))
        self.AddAttrib(vdata.DataAttribStr('capture_publish', 'file',
                        values=['file', 'stream']))
        self.AddAttrib(vdata.DataAttribInt('iso', 100,
                        min_value=0, max_value=800))
        self.AddAttrib(vdata.DataAttribInt('shutter_speed', 0))

class cameraman(vmqtt.mqtt_node):
    __slots__ = ('burst_fps_ct', 'burst_fps_rate', 'burst_fps_start_time',
			'camera', 'camera_resolution', 'camera_type',
			'capture_format', 'capture_publish',
			'do_auto_iso',
			'image_ct', 'iso', 'idle_image_max',
			'last_fn', 'last_format', 'loop_format', 'loop_mode', 'loop_publish',
			'mark_hsv_spec', 'mark_payload', 'mark_rect',
			'mission_id', 'mission_logging',
			'orders_dict', 'orders_payload', 'post_processes',
			'shutter_speed',
                    )

    def __init__(self, Verbose=True):
        global picamera
        super().__init__(Subscriptions=[
						vmqtt.Subscription(vconst.cameraman_mark_topic, async_delivery=True, handler=self.OnCameramanMark),
						vmqtt.Subscription(vconst.cameraman_orders_topic, async_delivery=True, handler=self.OnCameramanOrders),
						vmqtt.Subscription(vconst.cameraman_process_topic, async_delivery=True, handler=self.OnCameramanProcess),
						vmqtt.Subscription(vconst.mission_init_topic, async_delivery=True, handler=self.OnMissionInit),
						vmqtt.Subscription(vconst.mission_log_start_topic, async_delivery=True, handler=self.OnMissionLogStart),
						vmqtt.Subscription(vconst.mission_log_stop_topic, async_delivery=True, handler=self.OnMissionLogStop)
					],
							SingleThreaded=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.burst_fps_rate = 0			# capture speed of last burst
        self.burst_fps_ct = 0
        self.burst_fps_start_time = time.time()
        self.iso = 100
        self.shutter_speed = 0
        self.camera_resolution = (640, 480)
        self.camera_resolution = (160, 120)
        self.camera_resolution = (320, 240)
        self.camera_type = self.config.get("Cameraman", "Camera")
        if self.camera_type == 'Picamera':
            import picamera
            import picamera.array
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
        #
        # capture format/publish are specs for how to save the captured image
        #
        self.capture_format = 'jpeg'		# jpeg, bgr
        self.capture_publish = 'file'		# file, stream
        self.do_auto_iso = False
        self.do_auto_iso = True
        self.idle_image_max = 20
        self.iso = self.camera.iso
        self.camera.shutter_speed = self.shutter_speed
        #
        # loop mode/format/publish are specs for how to configure picamera.capture_continuous().
        #
        self.loop_mode = 'idle'			# idle, single, run, pause
        self.loop_format = 'jpeg'		# jpeg, bgr, yuv, rgb
        self.loop_publish = 'file'		# file, stream
        self.mark_payload = None
        self.mark_hsv_spec = None
        self.mark_rect = None
        self.mission_id = None
        self.mission_logging = False
        self.orders_dict = CameramanOrdersDict()
        self.orders_payload = None
        self.post_processes = []
        self.image_ct = 0			# ct of images captured since __init__
        time.sleep(2)				# camera setling time, needed?
        self.last_fn = ''
        self.last_format = ''

    def OnCameramanProcess(self, payload):
        if payload['Type'] == 'clear':
            self.post_processes = []
        else:
            self.post_processes.append(payload)

    def OnCameramanMark(self, payload):
        print(payload)
        self.mark_rect = OpticChiasm.RectFromPayload(payload)
        self.mark_payload = payload

    def OnCameramanOrders(self, payload):
        # capture orders asynchronously so it can be used to tell the
        # burst loop to break in order to apply the new orders.
        self.orders_payload = payload

    def OnMissionInit(self, payload):
        self.mission_id = payload['mission_id']

    def OnMissionLogStart(self, payload):
        self.mission_logging = True

    def OnMissionLogStop(self, payload):
        self.mission_logging = False

    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which handles exceptions and proper shutdown.
        # if paused, maybe sleep for a bit or changed os.nice. Not sure if important.
        if self.orders_payload is not None:
            payload, self.orders_payload = self.orders_payload, None
            self.orders_dict.ValidatePayload(payload, self)
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
        rect_list = []
        if self.mark_rect is None:
            return rect_list
        if self.mark_hsv_spec is None:
            return rect_list

        kernel_dim = 7
        iterations = 1
        box_reps = 10
        end_y = self.mark_rect.TopY(0) - (self.mark_rect.height * box_reps)
        if end_y < 0:
            end_y = 0

        rect_list = im.ChaseLine(hsvspec=self.mark_hsv_spec, rect=self.mark_rect, end_y=end_y,
                                kernel_dim=kernel_dim, iterations=iterations)
        list_list = OpticChiasm.ListOfOpenCvRectAsListOfDicts(rect_list)
        #print("MAKER ==>", list_list)
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

        last_time = 0
        burst_image_ct = 0
        burst_timestamp = vmqtt.NowStr()
        if self.mission_logging:
            image_file_name_format = self.mission_id + "_" + burst_timestamp + "_{counter}." + self.loop_format
        else:
            image_file_name_format = "Idle_{counter}." + self.loop_format
        if self.loop_publish == 'file':
            burst_dest = os.path.join(self.imageDir, image_file_name_format)
        else:
            # streams can be jpeg, rgb, bgr, or yuv
            if self.loop_format == 'yuv':
                burst_dest = picamera.array.PiYUVArray(self.camera)
            elif self.loop_format in [OpticChiasm.IM_RGB, OpticChiasm.IM_BGR]:
                burst_dest = picamera.array.PiRGBArray(self.camera)
            else:				# jpeg
                burst_dest = io.BytesIO()
        #
        # Capture some pictures. This might be a single image or a long run of them.
        #
        if self.verbose:
            print("Cameraman.ImageBurst() Begin Burst", self.loop_mode, self.loop_format, self.loop_publish, burst_dest, self.image_ct)
        for picam_return in self.camera.capture_continuous(burst_dest, format=self.loop_format, use_video_port=True):
            burst_image_ct += 1
            self.image_ct += 1
            if self.loop_publish == 'file':
                image_path = picam_return
                image_fn = os.path.basename(image_path)
                # the file is already written, make sure its the correct capture format
                assert self.capture_format == self.loop_format
                this_image = None			# the image is in a file, not directly modifiable
            else:
                # capture_continuous returns burst_dest if it is a buffer
                image_fn = image_file_name_format.format(counter=burst_image_ct, timestamp=burst_timestamp)
                #print("CAPT", image_fn, self.imageDir)
                image_path = os.path.join(self.imageDir, image_fn)
                this_image = OpticChiasm.ImageFromPicamera(burst_dest, self.loop_format, file_path=image_path)
                if self.capture_publish == 'file':
                    this_image.Write()

                """
                if burst_publish == 's':
                    #buffer = burst_dest.getvalue()
                    buffer = burst_dest.array
                    #buffer = pickle.dumps(burst_dest.array)
                    payload = {}
                    payload['filename'] = image_fn
                    payload['format'] = burst_format
                    payload['publish'] = burst_publish
                    payload['buflen'] = len(buffer)
                    self.streamer.write(json.dumps(payload) + chr(26) + buffer)
                """
                if self.verbose:
                    print("PIC", image_fn)
            #
            # At this point we have an image captured
            #
            rect_list = None
            if (len(self.post_processes) > 0) or (self.mark_payload is not None) or True:
                # we need an OpenCv image for post processing
                if this_image is None:
                    this_image = OpticChiasm.Image(opencv_fn=image_path)
            if self.mark_payload is not None:
                # self.mark_rect was unconditionally created when the message was received.
                # The rectangle might be used for muiltiple things.
                # If an HsvSpec is in the payload, use that. Otherwise create an HsvSpec from
                # the image at the rectangle.
                # If the payload has a save parameter, save it in mission persistant data.
                hsv_spec = OpticChiasm.HsvSpecFromPayload(self.mark_payload)
                if hsv_spec is None:
                    self.mark_hsv_spec = OpticChiasm.NextHsvSpec(this_image.ImAsHSV(), rect=self.mark_rect)
                else:
                    self.mark_hsv_spec = hsv_spec
                if 'save' in self.mark_payload:
                    hsv_payload = self.PrepareResponse(self.mark_payload, ConfResponse=True)
                    hsv_payload.update(self.mark_hsv_spec.AsPayload())
                    print("MARK HSV", hsv_payload)
                    hsv_payload[vconst.dname_field_name]  = self.mark_payload['save']
                    self.Publish(vconst.data_save_topic, hsv_payload)
                self.mark_payload = None		# only do the HSV processing once
            if len(self.post_processes) > 0:
                annotated = img.copy()
                for this in self.post_processes:
                    self.PostProcess(this, Im=img, An=annotated)
                pos = image_fn.rfind('.')
                an_fn = image_fn[:pos] + '-A' + im_fn[pos:]
                an_path = os.path.join(self.imageDir, an_fn)
                cv2.imwrite(an_path, annotated)
            else:
                rect_list = self.MakerFaire2018(this_image)
                annotated = None
            #
            # Imsge process, now publish
            #
            self.burst_fps_ct += 1
            burst_elapsed_time = time.time() - self.burst_fps_start_time
            self.burst_fps_rate = self.burst_fps_ct / burst_elapsed_time
            payload = {}
            payload['filename'] = image_fn
            if annotated is not None:
                payload['annotated'] = an_fn
            payload['iso'] = self.camera.iso
            payload['shutter_speed'] = self.camera.exposure_speed
            payload['capture_format'] = self.capture_format
            payload['capture_publish'] = self.capture_publish
            payload['capture_fps'] = self.burst_fps_rate
            payload['center_line'] = rect_list
            self.Publish(vconst.cameraman_pic_ready_topic, payload)
            #print("P", self.mqttc.connected, payload)
            if self.camera.iso != self.iso:
                # The camera may not use the exact ISO specified. Save the corrected value in
                # self.iso so we don't keep repeating the request.
                print("CHANGING ISO", self.camera.iso, self.iso)
                self.camera.iso = self.iso
                self.iso = self.camera.iso
            if self.camera.shutter_speed != self.shutter_speed:
                self.camera.shutter_speed = self.shutter_speed
            if self.loop_publish == 'stream':
                # prepare for next image. This is needed even when not published
                burst_dest.truncate()
                burst_dest.seek(0)   # ?? needed for io.Bytes?? Required for PiRGBArray for subsequent images
            if self.loop_mode == 'idle':
                #print("END IDLE")
                # need conditional to determin conversion paramter for different formats
                if self.do_auto_iso:
                    self.AutoIso(this_image.im)
                if burst_image_ct >= self.idle_image_max:
                    # idle takes a limited number of images per "burst" to cycle throrugh a limited number of file names.
                    break
            if self.loop_mode == 'single':
                # enter paused mode if we have taken our single picture
                self.loop_mode = 'pause'
                break

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        vmqtt.LaunchNode(cameraman)
