import base64
import configparser
import io
import json
import os
import pickle
import signal
import sys
import threading
import time
import traceback

import cv2
import numpy as np

from cvpipeline import opticchiasm
from ezcomms import vnavs_comms as vcomms
from ezcomms import vnavs_const as vconst
from ezcomms import vnavs_data as vdata
from ezcomms import vnavs_node as vmqtt
from vnavsrun import helmsman
from cvpipeline.macbookcamera import MacbookCamera

PICAMERA2_FORMATS = {
    "bgr": "BGR888",
    "rgb": "RGB888",
    "yuv": "YUV420",
}


def _ini_bool(config, section, option, default=False):
    """Read a 0/1/true/false ini value, tolerating a missing section/option."""
    try:
        return config.getboolean(section, option)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return default
    except ValueError:
        print("Cameraman: [{}] {} is not boolean, using {}".format(
            section, option, default))
        return default


class CaptureBuffer:
    """Mimics the PiRGBArray/PiYUVArray interface for picamera2."""

    __slots__ = ("array",)

    def __init__(self):
        self.array = None

    def truncate(self):
        pass

    def seek(self, pos):
        pass


class Picamera2Wrapper:
    """Wraps picamera2.Picamera2 to present the same interface as legacy PiCamera.

    Works with both global shutter (e.g. IMX296) and rolling shutter
    (e.g. IMX219, IMX477) cameras -- libcamera handles sensor differences
    transparently.
    """

    __slots__ = (
        "_cam",
        "_iso",
        "_shutter_speed",
        "hflip",
        "resolution",
        "vflip",
    )

    def __init__(self, resolution=(320, 240), hflip=False, vflip=False, controls=None):
        from picamera2 import Picamera2
        from libcamera import Transform

        self._cam = Picamera2()
        self.resolution = resolution
        self.vflip = bool(vflip)
        self.hflip = bool(hflip)
        self._iso = 100
        self._shutter_speed = 0
        config_opts = {
            "main": {"size": resolution, "format": "BGR888"},
            "transform": Transform(hflip=self.hflip, vflip=self.vflip),
        }
        if controls:
            # Any libcamera control name -> value, straight from vnavs.ini.
            config_opts["controls"] = dict(controls)
        config = self._cam.create_video_configuration(**config_opts)
        self._cam.configure(config)
        self._cam.start()

    @property
    def iso(self):
        return self._iso

    @iso.setter
    def iso(self, value):
        self._iso = value
        # picamera2 uses AnalogueGain; ISO 100 ~ gain 1.0
        gain = max(1.0, value / 100.0)
        self._cam.set_controls({"AnalogueGain": gain})

    @property
    def shutter_speed(self):
        return self._shutter_speed

    @shutter_speed.setter
    def shutter_speed(self, value):
        self._shutter_speed = value
        if value > 0:
            self._cam.set_controls({"ExposureTime": value})
        else:
            self._cam.set_controls({"AeEnable": True})

    @property
    def exposure_speed(self):
        metadata = self._cam.capture_metadata()
        return metadata.get("ExposureTime", 0)

    def capture_continuous(self, output, format=None, use_video_port=True):
        """Generator that yields file paths or filled CaptureBuffer objects."""
        ctr = 0
        while True:
            ctr += 1
            array = self._cam.capture_array("main")
            if isinstance(output, str):
                path = output.format(counter=ctr)
                cv2.imwrite(path, array)
                yield path
            else:
                output.array = array
                yield output

print("CONFIGURING SIGNAL")
stop_process = False


def signal_handler(signal, frame):
    global stop_process
    print("You pressed Ctrl+C!")
    stop_process = True
    vmqtt.stop_process = True


signal.signal(signal.SIGINT, signal_handler)

RACE_SPEED = 2
RACE_STEERING_2 = 0.1


class CameramanOrdersDict(vdata.Dict):
    def __init__(self):
        super().__init__()
        self.AddAttrib(
            vdata.DataAttribStr(
                "loop_mode", "idle", values=["idle", "pause", "run", "single"]
            )
        )
        self.AddAttrib(
            vdata.DataAttribStr("loop_format", "jpeg", values=["bgr", "jpeg", "yuv"])
        )
        self.AddAttrib(
            vdata.DataAttribStr("loop_publish", "file", values=["file", "stream"])
        )
        self.AddAttrib(
            vdata.DataAttribStr("capture_format", "jpeg", values=["bgr", "jpeg"])
        )
        self.AddAttrib(
            vdata.DataAttribStr("capture_publish", "file", values=["file", "stream"])
        )
        self.AddAttrib(vdata.DataAttribInt("iso", 100, min_value=0, max_value=800))
        self.AddAttrib(vdata.DataAttribInt("shutter_speed", 0))


class Cameraman(vmqtt.VnavsNode):
    __slots__ = (
        "blob_specs",
        "burst_fps_ct",
        "burst_fps_rate",
        "burst_fps_start_time",
        "cam_compiled",
        "cam_script",
        "camera",
        "camera_resolution",
        "camera_type",
        "capture_format",
        "capture_publish",
        "do_auto_iso",
        "image_ct",
        "image_dir",
        "iso",
        "idle_image_max",
        "last_fn",
        "last_format",
        "loop_format",
        "loop_mode",
        "loop_publish",
        "mark_hsv_spec",
        "mark_payload",
        "mark_rect",
        "mission_id",
        "mission_logging",
        "orders_dict",
        "orders_payload",
        "post_processes",
        "shutter_speed",
    )

    # ### post_process() and post_processes are deprecated?
    # ### self.maker_faire_2018 deprecated

    def __init__(self, verbose=True):
        global picamera
        super().__init__(
            subscriptions=[
                vmqtt.Subscription(
                    vconst.cameraman_mark_topic,
                    async_delivery=True,
                    handler=self.on_cameraman_mark,
                ),
                vmqtt.Subscription(
                    vconst.cameraman_orders_topic,
                    async_delivery=True,
                    handler=self.on_cameraman_orders,
                ),
                vmqtt.Subscription(
                    vconst.cameraman_process_topic,
                    async_delivery=True,
                    handler=self.on_cameraman_process,
                ),
                vmqtt.Subscription(
                    vconst.mission_init_topic,
                    async_delivery=True,
                    handler=self.on_mission_init,
                ),
                vmqtt.Subscription(
                    vconst.mission_log_start_topic,
                    async_delivery=True,
                    handler=self.on_mission_log_start,
                ),
                vmqtt.Subscription(
                    vconst.mission_log_stop_topic,
                    async_delivery=True,
                    handler=self.on_mission_log_stop,
                ),
                vmqtt.Subscription(
                    vconst.cameraman_blob_spec_topic,
                    async_delivery=True,
                    handler=self.on_cameraman_blob_spec,
                ),
            ],
            single_threaded=False,
            broker_type="F",
            streamer=False,
            verbose=verbose,
        )
        self.burst_fps_rate = 0  # capture speed of last burst
        self.burst_fps_ct = 0
        self.burst_fps_start_time = time.time()
        self.image_ct = 0  # ct of images captured since __init__
        self.image_dir = self.get_ini_directory(
            "Cameraman", "imageDir", IsWriteable=True
        )
        self.iso = 100
        self.shutter_speed = 0
        self.camera_resolution = (640, 480)
        self.camera_resolution = (160, 120)
        self.camera_resolution = (320, 240)
        self.camera_type = self.config.get("Cameraman", "Camera")
        hflip, vflip, camera_controls = self.read_camera_options()
        if self.camera_type == "Picamera2":
            try:
                self.camera = Picamera2Wrapper(
                    resolution=self.camera_resolution,
                    hflip=hflip,
                    vflip=vflip,
                    controls=camera_controls,
                )
            except RuntimeError as e:
                print(
                    "Camera error:", e,
                    "Camera is probably in-use by another node."
                )
                sys.exit(1)
        else:
            self.camera = MacbookCamera(resolution=self.camera_resolution)
            self.camera.hflip = hflip
            self.camera.vflip = vflip
        self.camera.iso = self.iso
        #
        # capture format/publish are specs for how to save the captured image
        #
        self.capture_format = "jpeg"  # jpeg, bgr
        self.capture_publish = "file"  # file, stream
        self.do_auto_iso = False
        self.do_auto_iso = True
        self.idle_image_max = 20
        self.iso = self.camera.iso
        self.camera.shutter_speed = self.shutter_speed
        #
        # loop mode/format/publish are specs for how to configure picamera.capture_continuous().
        #
        self.loop_mode = "idle"  # idle, single, run, pause
        self.loop_format = "jpeg"  # jpeg, bgr, yuv, rgb
        self.loop_publish = "file"  # file, stream
        self.blob_specs = {}
        self.mark_payload = None
        self.mark_hsv_spec = None
        self.mark_rect = None
        self.mission_id = None
        self.mission_logging = False
        self.orders_dict = CameramanOrdersDict()
        self.orders_payload = None
        self.post_processes = []
        time.sleep(2)  # camera setling time, needed?
        self.last_fn = ""
        self.last_format = ""

    def read_camera_options(self):
        """Camera orientation and libcamera controls from [Cameraman] in vnavs.ini.

        HFlip / VFlip (0 or 1) drive the libcamera Transform -- set both for a
        camera mounted upside down. Controls is a JSON object mapping any
        libcamera control name to a value, passed straight through to
        picamera2's create_video_configuration(), e.g.

            [Cameraman]
            HFlip = 1
            VFlip = 1
            Controls = {"Brightness": 0.1, "Sharpness": 2.0, "FrameRate": 40}
        """
        hflip = _ini_bool(self.config, "Cameraman", "HFlip", False)
        vflip = _ini_bool(self.config, "Cameraman", "VFlip", False)
        controls = {}
        try:
            raw = self.config.get("Cameraman", "Controls").strip()
        except (configparser.NoSectionError, configparser.NoOptionError):
            raw = ""
        if raw:
            try:
                controls = json.loads(raw)
            except ValueError as e:
                print("Cameraman: ignoring invalid [Cameraman] Controls JSON:", e)
        print("Cameraman options: hflip={} vflip={} controls={}".format(
            hflip, vflip, controls))
        return hflip, vflip, controls

    def on_cameraman_process(self, payload):
        if payload["Type"] == "clear":
            self.post_processes = []
            self.cam_compiled = None
            self.cam_script = None
        else:
            self.post_processes.append(payload)
            self.cam_script = payload["cam_script"]
            self.cam_compiled = compile(
                self.cam_script, "cvcode.py", "exec", dont_inherit=True
            )

    def on_cameraman_mark(self, payload):
        print(payload)
        self.mark_rect = opticchiasm.right_from_payload(payload)
        self.mark_payload = payload

    def on_cameraman_blob_spec(self, payload):
        action = payload.get("action", "set")
        if action == "set":
            label = payload["label"]
            hsv_spec = opticchiasm.hsv_spec_from_payload(payload)
            if "y_min" in payload:
                rect = opticchiasm.right_from_payload(payload)
            else:
                rect = None
            self.blob_specs[label] = (hsv_spec, rect)
        elif action == "clear":
            label = payload["label"]
            self.blob_specs.pop(label, None)
        elif action == "clear_all":
            self.blob_specs = {}

    def on_cameraman_orders(self, payload):
        # capture orders asynchronously so it can be used to tell the
        # burst loop to break in order to apply the new orders.
        self.orders_payload = payload

    def on_mission_init(self, payload):
        self.mission_id = payload["mission_id"]

    def on_mission_log_start(self, payload):
        self.mission_logging = True

    def on_mission_log_stop(self, payload):
        self.mission_logging = False

    def client_loop_code(self):
        # executed repetitively by VnavsNode.main_loop() which handles exceptions and proper shutdown.
        # if paused, maybe sleep for a bit or changed os.nice. Not sure if important.
        if self.orders_payload is not None:
            payload, self.orders_payload = self.orders_payload, None
            self.orders_dict.ValidatePayload(payload, self)
        self.image_burst()

    # def post_process(self, process, Im=None, An=None):
    def post_process(self, im):
        glb = {}
        glb["cv2"] = cv2
        glb["oc"] = oc
        glb["np"] = np
        loc = {}
        loc["im_base"] = im
        exec(c, glb, loc)
        return loc["display_image"]

        green = (0, 255, 0)
        blue = (0, 0, 255)
        r = Im.shape[0]
        c = Im.shape[1]
        x1 = int(process["x1"])
        y1 = int(process["y1"])
        x2 = int(process["x2"])
        y2 = int(process["y2"])
        if x1 < 0:
            x1 += c
        if y1 < 0:
            y1 += r
        if x2 < 0:
            x2 += c
        if y2 < 0:
            y2 += r
        roi = opticchiasm.roi(Im, x1, y1, x2, y2)
        d = opticchiasm.ReflexEntities(
            roi, process=process["process"], colors=process["colors"]
        )
        mid_x = int((x2 - x1) / 2)
        sensor_point = d.process_lines()
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
            payload[helmsman.HELMSMAN_RAD_PER_SEC] = -s
            self.publish(vconst.helmsman_orders_topic, payload)
        if An is not None:
            cv2.rectangle(An, (x1, y1), (x2, y2), green, thickness=2)
            d.annotate_full_image(An, x1=x1, y1=y1, linect=1, color=blue)
        return
        fpx = im_fn[:-4]
        im_fn = fpx + "-A.jpeg"
        im_path = os.path.join(self.image_dir, im_fn)
        cv2.imwrite(im_path, d.original)
        annotated_fn = fpx + "-B.jpeg"
        annotated_path = os.path.join(self.image_dir, annotated_fn)
        cv2.imwrite(annotated_path, d.annotated)
        directions = {}
        directions["timeout"] = 3
        directions["speed"] = RACE_SPEED
        avg_slope = int(d.avg_slope)
        if (abs(avg_slope) > 4) or (d.slope_ct < 1):
            directions["heading"] = "AWS"
        else:
            if abs(avg_slope) > 2:
                steering_angle = "1"
            elif abs(avg_slope) > RACE_STEERING_2:
                steering_angle = "2"
            else:
                steering_angle = "3"
            if avg_slope > 0:
                directions["heading"] = "RR-" + steering_angle
            else:
                directions["heading"] = "RL+" + steering_angle
        self.publish(vconst.helmsman_orders_topic, directions)
        #
        self.last_fn = annotated_fn
        self.last_format = "jpeg"
        payload = {}
        payload["filename"] = self.last_fn
        payload["format"] = self.last_format
        self.publish("last", payload)

    def auto_iso(self, img):
        bw = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([bw], [0], None, [256], [0, 256])
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

    def maker_faire_2018(self, im):
        rect_list = []
        if self.mark_rect is None:
            return rect_list
        if self.mark_hsv_spec is None:
            return rect_list

        kernel_dim = 7
        iterations = 1
        box_reps = 10
        end_y = self.mark_rect.top_y(0) - (self.mark_rect.height * box_reps)
        if end_y < 0:
            end_y = 0

        rect_list = im.chase_line(
            hsvspec=self.mark_hsv_spec,
            rect=self.mark_rect,
            end_y=end_y,
            kernel_dim=kernel_dim,
            iterations=iterations,
        )
        list_list = opticchiasm.list_of_rotated_rect_as_list_of_dicts(rect_list)
        # print("MAKER ==>", list_list)
        return list_list

    def image_burst(self):
        # establish paramters for this burst. Since MQTT is running in a separate thread
        # there is a potential race condition if several conflicting instructions arrive
        # in a short period of time. This window is very small and the results easily
        # recoverable so I'm not fixing it now.
        #
        # Discussion of how to get images captured and processed quickly
        # http://picamera.readthedocs.io/en/release-1.12/recipes2.html
        #
        if self.loop_mode == "pause":
            return

        last_time = 0
        burst_image_ct = 0
        burst_timestamp = vmqtt.NowStr()
        if self.mission_logging:
            image_file_name_format = (
                self.mission_id
                + "_"
                + burst_timestamp
                + "_{counter}."
                + self.loop_format
            )
        else:
            image_file_name_format = "Idle_{counter}." + self.loop_format
        if self.loop_publish == "file":
            burst_dest = os.path.join(self.image_dir, image_file_name_format)
        else:
            # streams can be jpeg, rgb, bgr, or yuv
            if self.loop_format in ["yuv", opticchiasm.IM_RGB, opticchiasm.IM_BGR]:
                burst_dest = CaptureBuffer()
            else:  # jpeg
                burst_dest = io.BytesIO()
        #
        # Capture some pictures. This might be a single image or a long run of them.
        #
        if self.verbose:
            print(
                "Cameraman.image_burst() Begin Burst",
                self.loop_mode,
                self.loop_format,
                self.loop_publish,
                burst_dest,
                self.image_ct,
            )
        for picam_return in self.camera.capture_continuous(
            burst_dest, format=self.loop_format, use_video_port=True
        ):
            burst_image_ct += 1
            self.image_ct += 1
            if self.loop_publish == "file":
                image_path = picam_return
                image_fn = os.path.basename(image_path)
                # the file is already written, make sure its the correct capture format
                assert self.capture_format == self.loop_format
                this_image = None  # the image is in a file, not directly modifiable
            else:
                # capture_continuous returns burst_dest if it is a buffer
                image_fn = image_file_name_format.format(
                    counter=burst_image_ct, timestamp=burst_timestamp
                )
                # print("CAPT", image_fn, self.image_dir)
                image_path = os.path.join(self.image_dir, image_fn)
                this_image = opticchiasm.image_from_picamera(
                    burst_dest, self.loop_format, file_path=image_path
                )
                if self.capture_publish == "file":
                    this_image.write()

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
            if (
                (len(self.post_processes) > 0)
                or (self.mark_payload is not None)
                or True
            ):
                # we need an OpenCv image for post processing
                if this_image is None:
                    this_image = opticchiasm.Image(opencv_fn=image_path)
            if self.mark_payload is not None:
                # self.mark_rect was unconditionally created when the message was received.
                # The rectangle might be used for muiltiple things.
                # If an HsvSpec is in the payload, use that. Otherwise create an HsvSpec from
                # the image at the rectangle.
                # If the payload has a save parameter, save it in mission persistant data.
                hsv_spec = opticchiasm.hsv_spec_from_payload(self.mark_payload)
                if hsv_spec is None:
                    self.mark_hsv_spec = opticchiasm.next_hsv_spec_fn(
                        this_image.im_as_hsv(), rotated_rect=self.mark_rect
                    )
                else:
                    self.mark_hsv_spec = hsv_spec
                if "save" in self.mark_payload:
                    hsv_payload = vcomms.prepare_response(
                        self.mark_payload, conf_request=True
                    )
                    hsv_payload.update(self.mark_hsv_spec.as_payload())
                    print("MARK HSV", hsv_payload)
                    hsv_payload[vconst.dname_field_name] = self.mark_payload["save"]
                    self.publish(vconst.data_save_topic, hsv_payload)
                self.mark_payload = None  # only do the HSV processing once
            annotated = None
            an_fn = None
            rect_list = self.maker_faire_2018(this_image)
            blobs_result = {}
            for label, (hsv_spec, rect) in self.blob_specs.items():
                blob_list, _ = this_image.find_color_blobs(
                    hsv_spec, rect=rect, minimum_blob_area=20
                )
                if blob_list:
                    blobs_result[label] = (
                        opticchiasm.list_of_rotated_rect_as_list_of_dicts(blob_list)
                    )
            #
            # Imsge process, now publish
            #
            self.burst_fps_ct += 1
            burst_elapsed_time = time.time() - self.burst_fps_start_time
            self.burst_fps_rate = self.burst_fps_ct / burst_elapsed_time
            payload = {}
            payload["filename"] = image_fn
            if annotated is not None:
                payload["annotated"] = an_fn
            payload["iso"] = self.camera.iso
            payload["shutter_speed"] = self.camera.exposure_speed
            payload["capture_format"] = self.capture_format
            payload["capture_publish"] = self.capture_publish
            payload["capture_fps"] = self.burst_fps_rate
            payload["center_line"] = rect_list
            payload["blobs"] = blobs_result
            self.publish(vconst.cameraman_pic_ready_topic, payload)
            # print("P", self.mqttc.connected, payload)
            if self.camera.iso != self.iso:
                # The camera may not use the exact ISO specified. Save the corrected value in
                # self.iso so we don't keep repeating the request.
                print("CHANGING ISO", self.camera.iso, self.iso)
                self.camera.iso = self.iso
                self.iso = self.camera.iso
            if self.camera.shutter_speed != self.shutter_speed:
                self.camera.shutter_speed = self.shutter_speed
            if self.loop_publish == "stream":
                # prepare for next image. This is needed even when not published
                burst_dest.truncate()
                burst_dest.seek(
                    0
                )  # ?? needed for io.Bytes?? Required for PiRGBArray for subsequent images
            if self.loop_mode == "idle":
                # print("END IDLE")
                # need conditional to determin conversion paramter for different formats
                if self.do_auto_iso:
                    self.auto_iso(this_image.im)
                if burst_image_ct >= self.idle_image_max:
                    # idle takes a limited number of images per "burst" to cycle throrugh a limited number of file names.
                    break
            if self.loop_mode == "single":
                # enter paused mode if we have taken our single picture
                self.loop_mode = "pause"
                break


if __name__ == "__main__":
    if sys.argv[1] == "node":
        m = Cameraman()
        m.main_loop()
