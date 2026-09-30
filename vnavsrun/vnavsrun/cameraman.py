import configparser
import json
import os
import signal
import sys
import time

import cv2
import numpy as np

from cvpipeline import opticchiasm
from ezcomms import vnavs_const as vconst
from ezcomms import vnavs_data as vdata
from ezcomms import vnavs_node as vmqtt
from vnavslib.imageproc import ControlState, ImageProc
from vnavsrun import helmsman


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
        "control",
        "image_proc",
        "last_fn",
        "last_format",
        "orders_dict",
        "orders_payload",
    )

    # ### post_process() and post_processes are deprecated?

    def __init__(self, verbose=True):
        super().__init__(
            subscriptions=[
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
        self.control = ControlState()
        self.control.image_dir = self.get_ini_directory(
            "Cameraman", "imageDir", IsWriteable=True
        )
        self.control.publish = self.publish
        self.control.verbose = self.verbose
        resolution = (320, 240)
        hflip, vflip, camera_controls = self.read_camera_options()
        try:
            from picamera2 import Picamera2
            from libcamera import Transform

            cam = Picamera2()
            config_opts = {
                # picamera2 format names are byte-order (little-endian),
                # reversed from numpy index order: "RGB888" makes
                # capture_array() return a BGR-ordered array -- which is what
                # cv2 (imwrite, cvtColor) and opticchiasm (BGR2HSV) downstream
                # all assume.
                "main": {"size": resolution, "format": "RGB888"},
                "transform": Transform(hflip=hflip, vflip=vflip),
            }
            if camera_controls:
                config_opts["controls"] = dict(camera_controls)
            config = cam.create_video_configuration(**config_opts)
            cam.configure(config)
            cam.start()
            self.control.camera = cam
        except RuntimeError as e:
            print(
                "Camera error:", e,
                "Camera is probably in-use by another node."
            )
            sys.exit(1)
        # ISO 100 ~ AnalogueGain 1.0
        self.control.camera.set_controls({
            "AnalogueGain": max(1.0, self.control.iso / 100.0),
        })
        if self.control.shutter_speed > 0:
            self.control.camera.set_controls({
                "ExposureTime": self.control.shutter_speed,
            })
        self.orders_dict = CameramanOrdersDict()
        self.orders_payload = None
        time.sleep(2)  # camera settling time, needed?
        self.last_fn = ""
        self.last_format = ""
        self.image_proc = ImageProc(self.control)

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
        hflip = vconst.config_getbool(self.config, "Cameraman", "HFlip", False)
        vflip = vconst.config_getbool(self.config, "Cameraman", "VFlip", False)
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
            self.control.post_processes = []
            self.control.cam_compiled = None
            self.control.cam_script = None
        else:
            self.control.post_processes.append(payload)
            self.control.cam_script = payload["cam_script"]
            self.control.cam_compiled = compile(
                self.control.cam_script, "cvcode.py", "exec", dont_inherit=True
            )

    def on_cameraman_blob_spec(self, payload):
        action = payload.get("action", "set")
        if action == "set":
            label = payload["label"]
            hsv_spec = opticchiasm.hsv_spec_from_payload(payload)
            if "y_min" in payload:
                rect = opticchiasm.right_from_payload(payload)
            else:
                rect = None
            self.control.blob_specs[label] = (hsv_spec, rect)
        elif action == "clear":
            label = payload["label"]
            self.control.blob_specs.pop(label, None)
        elif action == "clear_all":
            self.control.blob_specs = {}

    def on_cameraman_orders(self, payload):
        # capture orders asynchronously so it can be used to tell the
        # burst loop to break in order to apply the new orders.
        self.orders_payload = payload

    def on_mission_init(self, payload):
        self.control.mission_id = payload["mission_id"]

    def on_mission_log_start(self, payload):
        self.control.mission_logging = True

    def on_mission_log_stop(self, payload):
        self.control.mission_logging = False

    def client_loop_code(self):
        # executed repetitively by VnavsNode.main_loop() which handles exceptions and proper shutdown.
        # if paused, maybe sleep for a bit or changed os.nice. Not sure if important.
        if self.orders_payload is not None:
            payload, self.orders_payload = self.orders_payload, None
            self.orders_dict.ValidatePayload(payload, self.control)
        self.image_proc.image_burst()

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
        im_path = os.path.join(self.control.image_dir, im_fn)
        cv2.imwrite(im_path, d.original)
        annotated_fn = fpx + "-B.jpeg"
        annotated_path = os.path.join(self.control.image_dir, annotated_fn)
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



if __name__ == "__main__":
    if sys.argv[1] == "node":
        m = Cameraman()
        m.main_loop()
