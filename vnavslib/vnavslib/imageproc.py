import json
import os
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

import cv2

from cvpipeline import opticchiasm
from ezcomms import vnavs_const as vconst
from ezcomms import vnavs_data as vdata
from ezcomms import vnavs_node as vmqtt


@dataclass(slots=True)
class ControlState:
    """Settings updated by Cameraman message handlers, read by ImageProc.

    Cameraman owns writes (from MQTT messages); ImageProc reads.
    Exception: ``loop_mode`` may be set to ``"pause"`` by single-shot logic
    at the end of a burst.
    """

    # Hardware / environment (set once by Cameraman.__init__)
    camera: object = None
    image_dir: str = ""
    publish: object = None           # callable(topic, payload)
    verbose: bool = False
    # Camera settings (from orders messages)
    loop_mode: str = "idle"
    loop_format: str = "jpeg"
    loop_publish: str = "file"
    capture_format: str = "jpeg"
    capture_publish: str = "file"
    iso: int = 100
    shutter_speed: int = 0
    do_auto_iso: bool = True
    idle_image_max: int = 20
    # Mark / vision specs (from mark messages)
    mark_hsv_spec: object = None
    mark_rect: object = None
    mark_open_dim: int = 0
    mark_minrange: int = 20
    mark_adapt: bool = True
    mark_payload: object = None
    line_specs: dict = field(default_factory=dict)
    blob_specs: dict = field(default_factory=dict)
    # Mission state (from mission messages)
    mission_id: str = None
    mission_logging: bool = False
    # Post-processing (from process messages)
    post_processes: list = field(default_factory=list)
    cam_script: str = None
    cam_compiled: object = None


@dataclass(slots=True)
class BurstState:
    """Created at the start of each ``image_burst()`` call."""

    timestamp: str = ""
    image_file_name_format: str = ""
    dest: object = None
    image_ct: int = 0
    fps_ct: int = 0
    fps_rate: float = 0.0
    fps_start_time: float = 0.0


@dataclass(slots=True)
class FrameState:
    """Created fresh for each frame inside the capture loop."""

    image_path: str = ""
    image_fn: str = ""
    this_image: object = None
    rect_list: object = None
    lane_lines_result: dict = field(default_factory=dict)
    blobs_result: dict = field(default_factory=dict)


class ImageProc:
    """Image capture/processing loop, extracted from Cameraman.

    Owns ``image_burst()`` and its helpers.  Reads shared ``ControlState``
    for camera/vision settings and publishes results via a callable.
    """

    __slots__ = ("control",)

    def __init__(self, control):
        self.control = control

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
            self.control.iso += 100
        if self.control.iso > 800:
            self.control.iso = 800

    def maker_faire_2018(self, im):
        rect_list = []
        if self.control.mark_rect is None:
            return rect_list
        if self.control.mark_hsv_spec is None:
            return rect_list

        kernel_dim = 7
        iterations = 1
        box_reps = 10
        end_y = self.control.mark_rect.top_y(0) - (self.control.mark_rect.height * box_reps)
        if end_y < 0:
            end_y = 0

        rect_list = im.chase_line(
            hsvspec=self.control.mark_hsv_spec,
            rect=self.control.mark_rect,
            end_y=end_y,
            kernel_dim=kernel_dim,
            iterations=iterations,
            open_dim=self.control.mark_open_dim,
            adapt=self.control.mark_adapt,
        )
        list_list = opticchiasm.list_of_rotated_rect_as_list_of_dicts(rect_list)
        return list_list

    def process_frame(self, frame):
        """Apply mark, line, and blob detection to a captured frame."""
        ctrl = self.control
        frame.rect_list = None
        if (
            (len(ctrl.post_processes) > 0)
            or (ctrl.mark_payload is not None)
            or True
        ):
            if frame.this_image is None:
                frame.this_image = opticchiasm.Image(opencv_fn=frame.image_path)
        if ctrl.mark_payload is not None:
            if "open" in ctrl.mark_payload:
                ctrl.mark_open_dim = int(ctrl.mark_payload["open"])
            if "minrange" in ctrl.mark_payload:
                ctrl.mark_minrange = int(ctrl.mark_payload["minrange"])
            if "adapt" in ctrl.mark_payload:
                ctrl.mark_adapt = bool(int(ctrl.mark_payload["adapt"]))
            hsv_spec = opticchiasm.hsv_spec_from_payload(ctrl.mark_payload)
            if hsv_spec is None:
                hsv_spec = opticchiasm.next_hsv_spec_fn(
                    frame.this_image.im_as_hsv(),
                    rotated_rect=ctrl.mark_rect,
                    minrange=ctrl.mark_minrange,
                )
            label = ctrl.mark_payload.get("label")
            if label:
                ctrl.line_specs[label] = (hsv_spec, ctrl.mark_rect)
            else:
                ctrl.mark_hsv_spec = hsv_spec
            if "save" in ctrl.mark_payload:
                dname = ctrl.mark_payload["save"]
                hsv_dict = {
                    k: int(v) for k, v in hsv_spec.as_payload().items()
                }
                pdata = {
                    vdata.dkey_field_name: dname,
                    vdata.dgroup_field_name: None,
                    vdata.dfqn_field_name: dname,
                    vdata.dclass_field_name: "str",
                    vdata.dpayload_field_name: {
                        vdata.dprimitive_field_name: json.dumps(hsv_dict)
                    },
                }
                print("MARK HSV SAVE", dname, hsv_dict)
                self.control.publish(vconst.data_save_topic, {"pdata": pdata})
            ctrl.mark_payload = None
        frame.rect_list = self.maker_faire_2018(frame.this_image)
        frame.lane_lines_result = {}
        for label, (line_spec, line_rect) in ctrl.line_specs.items():
            if (line_spec is None) or (line_rect is None):
                continue
            line_end_y = line_rect.top_y(0) - (line_rect.height * 10)
            if line_end_y < 0:
                line_end_y = 0
            seg_list = frame.this_image.chase_line(
                hsvspec=line_spec,
                rect=line_rect,
                end_y=line_end_y,
                kernel_dim=7,
                iterations=1,
                open_dim=ctrl.mark_open_dim,
                adapt=ctrl.mark_adapt,
            )
            if seg_list:
                frame.lane_lines_result[label] = (
                    opticchiasm.list_of_rotated_rect_as_list_of_dicts(seg_list)
                )
        frame.blobs_result = {}
        for label, (hsv_spec, rect) in ctrl.blob_specs.items():
            blob_list, _ = frame.this_image.find_color_blobs(
                hsv_spec, rect=rect, minimum_blob_area=20
            )
            if blob_list:
                frame.blobs_result[label] = (
                    opticchiasm.list_of_rotated_rect_as_list_of_dicts(blob_list)
                )

    def publish_frame(self, frame, burst):
        """Publish results and sync camera settings after processing a frame."""
        ctrl = self.control
        burst.fps_ct += 1
        burst_elapsed_time = time.time() - burst.fps_start_time
        burst.fps_rate = burst.fps_ct / burst_elapsed_time
        metadata = ctrl.camera.capture_metadata()
        payload = {}
        payload["filename"] = frame.image_fn
        payload["iso"] = ctrl.iso
        payload["shutter_speed"] = metadata.get("ExposureTime", 0)
        payload["capture_format"] = ctrl.capture_format
        payload["capture_publish"] = ctrl.capture_publish
        payload["capture_fps"] = burst.fps_rate
        payload["center_line"] = frame.rect_list
        payload["lane_lines"] = frame.lane_lines_result
        payload["blobs"] = frame.blobs_result
        ctrl.publish(vconst.cameraman_pic_ready_topic, payload)
        # Sync camera hardware with ControlState (ISO 100 ~ AnalogueGain 1.0)
        ctrl.camera.set_controls({
            "AnalogueGain": max(1.0, ctrl.iso / 100.0),
        })
        if ctrl.shutter_speed > 0:
            ctrl.camera.set_controls({"ExposureTime": ctrl.shutter_speed})

    def capture_frames(self, dest):
        """Generator yielding file paths (when dest is a path template) or
        numpy arrays (when dest is None) from the camera."""
        ct = 0
        while True:
            ct += 1
            array = self.control.camera.capture_array("main")
            if dest is not None:
                path = dest.format(counter=ct)
                cv2.imwrite(path, array)
                yield path
            else:
                yield array

    def image_burst(self):
        ctrl = self.control

        if ctrl.loop_mode == "pause":
            return

        burst = BurstState()
        burst.timestamp = vmqtt.NowStr()
        burst.fps_start_time = time.time()
        if ctrl.mission_logging:
            burst.image_file_name_format = (
                ctrl.mission_id
                + "_"
                + burst.timestamp
                + "_{counter}."
                + ctrl.loop_format
            )
        else:
            burst.image_file_name_format = "Idle_{counter}." + ctrl.loop_format
        if ctrl.loop_publish == "file":
            burst.dest = os.path.join(ctrl.image_dir, burst.image_file_name_format)
        else:
            burst.dest = None

        if ctrl.verbose:
            print(
                "ImageProc.image_burst() Begin Burst",
                ctrl.loop_mode,
                ctrl.loop_format,
                ctrl.loop_publish,
                burst.dest,
            )
        for picam_return in self.capture_frames(burst.dest):
            burst.image_ct += 1

            frame = FrameState()

            if ctrl.loop_publish == "file":
                frame.image_path = picam_return
                frame.image_fn = os.path.basename(frame.image_path)
                assert ctrl.capture_format == ctrl.loop_format
                frame.this_image = None
            else:
                frame.image_fn = burst.image_file_name_format.format(
                    counter=burst.image_ct, timestamp=burst.timestamp
                )
                frame.image_path = os.path.join(ctrl.image_dir, frame.image_fn)
                frame.this_image = opticchiasm.image_from_picamera(
                    SimpleNamespace(array=picam_return),
                    ctrl.loop_format,
                    file_path=frame.image_path,
                )
                if ctrl.capture_publish == "file":
                    frame.this_image.write()

                if ctrl.verbose:
                    print("PIC", frame.image_fn)

            self.process_frame(frame)
            self.publish_frame(frame, burst)

            if ctrl.loop_mode == "idle":
                if ctrl.do_auto_iso:
                    self.auto_iso(frame.this_image.im)
                if burst.image_ct >= ctrl.idle_image_max:
                    break
            if ctrl.loop_mode == "single":
                ctrl.loop_mode = "pause"
                break
