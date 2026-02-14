import json
import math
import os
import sys
import threading
import time
import traceback
import types

import cv2
import numpy as np
from PIL import ImageTk, Image

from eztk import eztk
from vnavslib import image_analyzer
from vnavslib import image_filters
from vnavslib import opticchiasm as oc
from vnavslib import vnavs_const as vconst
from vnavslib import vnavs_data as vdata
from vnavslib import vnavs_file_xfer_client
from vnavslib import vnavs_node as vmqtt
from eztk.eztk import (
    FIRST_ROW,
    SAME_ROW,
    NEXT_ROW,
    OVERLAY_ROW,
    SAME_COL,
    NEXT_COL,
    LEFT_COL,
    RIGHT_COL,
    OVERLAY_COL,
)
from vnavsrun import cameraman

BOT_1_MAP_TRANSPOSE = [
    [-1.30565584e-01, -1.56472861e00, 4.58333935e02],
    [-2.57693172e-15, -3.10871493e00, 1.04702945e03],
    [-2.95275685e-18, -3.83178162e-03, 1.00000000e00],
]

BOT_1_H = np.array(BOT_1_MAP_TRANSPOSE, dtype="float32")

SRC_LOCAL_CAMERA = "local"
SRC_BOT_CAMERA = "bot"
SHOW_ANNOTATION = "ShowAnnotation"


class ProcessStep:
    __slots__ = (
        "cv_filter_name",
        "cv_specs",
        "deposition",
        "exec_annotated",
        "exec_contours",
        "exec_hierarchy",
        "exec_hsvspec",
        "exec_im",
        "exec_objects",
        "exec_rect",
        "execution_time",
        "filter_selection",
        "image_widget",
        "info_data",
        "info_widgets",
        "input_panel",
        "ix",
        "output_panel",
        "parm_widgets",
        "parm_values",
        "parms_specs",
        "point_target",
        "source_im",
        "source_path",
        "tab",
        "tab_title",
        "thumbnail",
        "use_annotation",
        "use_objects",
        "zoom_popup",
    )
    app = None
    steps = []
    process_file_extension = "drk"
    process_file_types = (("CvLab Process", "*." + process_file_extension),)
    python_file_extension = "py"
    python_file_types = (("CvLab Python", "*." + python_file_extension),)
    cameraman_file_extension = "cam"
    cameraman_file_types = (("CvLab Python", "*." + python_file_extension),)
    imports = []  # imports for exec or script
    # imports.append(('__builtins__', __builtins__, None))
    imports.append(("cv2", cv2, None))
    imports.append(("np", np, "numpy"))
    imports.append(("oc", oc, "oc"))
    imports.append(("cameraman", None, None))

    def __init__(self, filter_name=None, where=None, parms={}):
        self.ix = len(self.steps)
        self.exec_im = None  # this is an oc.Image produced by the filter
        self.steps.append(self)
        self.cv_filter_name = None  # this gets set by NewFilter()

        self.parm_values = parms  # key is FilterParm.name
        self.tab_title = f"Step {self.ix}"
        self.tab = self.app.notebook.add_tab(self.tab_title, where=where)
        self.input_panel = self.tab.add_label_frame("Input")
        self.output_panel = self.tab.add_label_frame("Output")
        self.zoom_popup = None
        #
        # input_panel
        #
        self.filter_selection = self.input_panel.add_listbox(
            "Filters",
            image_filters.ImageFilterCollection.image_filter_names,
            selection=filter_name,
            command=self.new_filter,
            rowspan=4,
        )
        self.info_data = []
        self.info_widgets = []
        for ix in range(6):
            info_label = self.input_panel.add_label("", row=NEXT_ROW, col=LEFT_COL)
            info_value = self.input_panel.add_label("", row=SAME_ROW, col=NEXT_COL)
            self.info_widgets.append((info_label, info_value))
        self.parm_widgets = []
        for ix in range(8):
            if ix == 0:
                parm_row = self.filter_selection.row
                parm_col = NEXT_COL
            else:
                parm_row = NEXT_ROW
                parm_col = self.parm_widgets[0][1].col
            parm_caption = f"Parm{ix + 1}"
            entry_label = self.input_panel.add_label(
                parm_caption, row=parm_row, col=parm_col
            )
            entry_box = self.input_panel.add_entry_field(
                row=SAME_ROW, col=NEXT_COL, on_double_click=self.on_pick_point
            )
            entry_slider = self.input_panel.add_slider_field(col=OVERLAY_COL)
            entry_checkbox = self.input_panel.add_checkbox(col=OVERLAY_COL)
            self.parm_widgets.append(
                [entry_box, entry_label, entry_box, entry_slider, entry_checkbox]
            )
        self.input_panel.add_button("Run", command=self.on_execute_step, col=parm_col)
        self.input_panel.add_button(
            "Delete Step", command=self.on_delete_step, row=SAME_ROW, col=NEXT_COL
        )
        #
        # output_panel
        #
        self.image_widget = self.output_panel.add_canvas(
            on_click=self.on_image_click, rowspan=2
        )
        self.execution_time = self.output_panel.add_label(row=FIRST_ROW, col=NEXT_COL)
        self.deposition = self.output_panel.add_label(row=NEXT_ROW, col=SAME_COL)
        self.thumbnail = self.app.thumbnail_frame.add_label_image(
            thumbnailof=self.image_widget, row=0, col=NEXT_COL
        )
        self.thumbnail.tkw.bind("<Button-1>", self.select_tab)
        self.source_im = None  # captured image
        self.source_path = None
        self.point_target = None
        self.set_filter()

    #
    # info_data are display fields under the image.
    # They are generally outputs from the step processing.
    #
    def clear_info(self):
        self.info_data = []

    def add_info(self, label, value):
        ix = len(self.info_data)
        self.info_data.append((label, value))
        return ix

    def add_info_sliders(self):
        for ix, this in enumerate(self.parm_widgets):
            if (ix < len(self.parms_specs)) and (self.parms_specs[ix].use_slider):
                self.add_info(self.parms_specs[ix].caption, this[0].value())

    def set_info(self, ix, label, value):
        while len(self.info_data) < (ix + 1):
            self.info_data.append(("", ""))
        self.info_data[ix] = (label, value)

    def on_pick_point(self, event):
        # This configures OnImageClick() to save the clicked point in a parm.
        # event.widget is the tkw object. We could use that to use this
        # method for multiple points.
        self.point_target = None
        for ix, this in enumerate(self.parm_widgets):
            if this[0].tkw == event.widget:
                # this is the tkeasy widget that was double-clicked
                if self.parms_specs[ix].click_point:
                    # the parm_spec indicates the paramter is a point in the image
                    # that can be slected by clicking on the image.
                    self.point_target = this[0]
        if self.point_target is not None:
            self.point_target.replace_value("<click image>")

    def on_execute_step(self):
        # Click this to refresh after changing a parameter. We don't automatically do
        # that in case intermediate updates might fail when make several changes.
        self.set_filter()  # This saves the parameter values
        self.app.step_execution_needed = True

    def on_delete_step(self):
        # This event is here because it is associated with the step and
        # identifies which event is to be deleted. We can't do the
        # actual deletion here because because we also need to delete
        # this ProcessStep() instance.
        self.app.delete_process_step_ix = self.ix

    def select_tab(self, event):
        # This is called as both a TK event and a general method.
        # Event is None if called as a general method.
        self.app.notebook.tkw.select(self.tab.tkw)

    def on_image_click(self, event):
        # The image has been clicked. What we do depends on the filter and
        # other state values.
        print("OnImageClick() *************")
        # Convert the mouse click coordinates of the scrolled and shrunken image
        # to coordinates of the full image.
        # event.x and event.y reference the visible area.
        # canvasx() and canvasy() translate to canvas size.
        x = self.image_widget.tkw.canvasx(event.x)
        y = self.image_widget.tkw.canvasy(event.y)
        if self.image_widget.pil_resize_ratio is not None:
            x = int(x / self.image_widget.pil_resize_ratio)
            y = int(y / self.image_widget.pil_resize_ratio)
        #
        # Now use the click appropriately
        #
        if self.point_target is not None:
            # save the point as a parm
            v = f"{int(x)},{int(y)}"
            self.point_target.replace_value(v)
            self.point_target = None
            return
        # Default action: pop-up a window with a larger image.
        print("ZOOM IM", self.exec_im.__class__.__name__)
        self.exec_im.write("zoom.jpeg")
        # Reference to popup must be maintained or image gets lost in garbage collection.
        self.zoom_popup = self.app.tk.make_popup_window(self.cv_filter_name)
        self.zoom_popup.add_label("Sum Thing")
        canvas = self.zoom_popup.add_canvas(width=800, height=400)
        canvas.update_image(pil_fn="zoom.jpeg")

    @classmethod
    def execute_all_steps(cls):
        for this_step in cls.steps:
            this_step.execute_step()

    def save_parameters(self):
        for ix, this_widget in enumerate(self.parm_widgets):
            if this_widget[0].parm_id is not None:
                # save prior value
                self.parm_values[this_widget[0].parm_id] = this_widget[0].value()

    def new_filter(self, *args):
        # TK callbacks seem to incude *args
        self.set_filter()
        self.app.step_execution_needed = True

    def set_filter(self, filter_name=None, new_parms=None):
        self.save_parameters()
        if new_parms is not None:
            for key, value in new_parms.items():
                self.parm_values[filter_name + "_" + key] = value
        if filter_name is None:
            new_filter_name = self.filter_selection.value()
        else:
            new_filter_name = filter_name
        # print("SetFilter()", new_filter_name,  self.cv_filter_name)
        if new_filter_name != self.cv_filter_name:
            self.filter_selection.replace_value(new_filter_name)
            self.cv_filter_name = new_filter_name
            self.cv_specs = image_filters.ImageFilterCollection.image_filters[self.cv_filter_name]
            self.parms_specs = self.cv_specs.parms
            if self.cv_specs.annotate_code is not None:
                annotation_control = False
                for this in self.parms_specs:
                    if this.name == SHOW_ANNOTATION:
                        annotation_control = True
                        break
                if not annotation_control:
                    self.parms_specs.append(
                        vdata.DataAttribBoolean(SHOW_ANNOTATION, "False")
                    )
            for ix, this_widget in enumerate(self.parm_widgets):
                print(
                    this_widget[0].col,
                    this_widget[1].col,
                    this_widget[2].col,
                    this_widget[3].col,
                    this_widget[4].col,
                )
                if ix < len(self.parms_specs):
                    parms_specs = self.parms_specs[ix]
                    parm_name = self.cv_filter_name + "_" + parms_specs.name
                    parm_caption = parms_specs.caption
                    parm_default_value = parms_specs.default
                    if parm_name not in self.parm_values:
                        self.parm_values[parm_name] = parm_default_value
                    parm_value = self.parm_values[parm_name]
                    if parms_specs.use_slider:
                        slider = this_widget[3]
                        this_widget[0] = slider  # use slider widget
                        min_value = parms_specs.min_value
                        if min_value is None:
                            min_value = 0
                        max_value = parms_specs.max_value
                        if max_value is None:
                            max_value = 0
                        slider.tkw.config(from_=min_value, to=max_value)
                    elif isinstance(parms_specs, vdata.DataAttribBoolean):
                        this_widget[0] = this_widget[4]  # use checkbox widget
                    else:
                        this_widget[0] = this_widget[2]  # use entry box widget
                else:
                    # Unused parameter widgets -- clear to generic value
                    parms_specs = None
                    parm_name = None
                    parm_caption = "Parm" + str(ix + 1)
                    parm_value = ""
                    this_widget[0] = this_widget[2]  # use entry box widget
                # print("set_filter() parm", ix, parm_caption, parms_specs)
                this_widget[1].replace_value(parm_caption)  # parameter label
                this_widget[0].tkw.lift()  # make active control visible (top of stack)
                this_widget[0].replace_value(parm_value)
                this_widget[0].parm_id = parm_name

    @classmethod
    def write_program(cls, py_fn):
        f = codecs.open(py_fn, "w", encoding="utf-8")
        f.write("\n")

        f.write("from __future__ import absolute_import, division, print_function\n")
        f.write("from builtins import (bytes, str, open, super, range,\n")
        f.write("              zip, round, input, int, pow, object)\n")
        f.write("\n")

        for this in cls.imports:
            if this[2] is None:
                f.write(f"import {this[0]}\n")
            else:
                f.write(f"import {this[2]} as {this[0]}\n")

        f.write("\n")
        source_path = cls.steps[0].source_path
        if source_path is None:
            f.write("cam = cameraman.MacbookCamera()\n")
            f.write("im_in = cam.capture_image()\n")
        else:
            f.write(f'im_in = oc.Image("opencv_fn={source_path}")\n')
        f.write("im_base = im_in.copy()\n")
        f.write("\n")

        for ix, this in enumerate(cls.steps[1:]):
            f.write(f"#\n# Step {this.ix} - {this.cv_filter_name}\n#\n")
            code_str = this.get_code_str(script=True)
            f.write(code_str)

        if cls.steps[-1].cv_specs.annotate_code is None:
            display_image = "im_in"
        else:
            display_image = "annotated"

        f.write("\n")
        f.write(f'cv2.imshow("im_in", {display_image}.im)\n')
        f.write("cv2.waitKey(0)\n")
        f.write("cv2.destroyAllWindows()\n")
        f.close()

    @classmethod
    def write_cameraman(cls, cam_fn):
        # Writes a snipet of code that will be used for compile/exec in cameraman
        # All imports will be provided via the global parameter:
        # 	cv2, oc (oc)
        # The source image object will be provided in the exec locals object:
        # 	im_base
        # The output image in the exec locals object is:
        # 	display_image

        f = codecs.open(cam_fn, "w", encoding="utf-8")

        f.write("im_in = im_base.copy()\n")

        for ix, this in enumerate(cls.steps[1:]):
            code_str = this.get_code_str(script=True)
            f.write(code_str)

        if cls.steps[-1].cv_specs.annotate_code is None:
            f.write("display_image = im_in\n")
        else:
            f.write("display_image = annotated\n")

        f.close()

    def get_code_str(self, script=True):
        self.save_parameters()
        code_substitutions = {}
        show_annotation = False
        for this_parm in self.parms_specs:
            raw_value = self.parm_values[self.cv_filter_name + "_" + this_parm.name]
            translated_value = this_parm.GetValue(raw_value)
            code_substitutions[this_parm.name] = translated_value
            # print("get_code_str() parms", this_parm.name, raw_value, translated_value)
            if this_parm.name == SHOW_ANNOTATION:
                show_annotation = translated_value
        if script:
            code_substitutions["x_output_annotated"] = "annotated"
            code_substitutions["x_output_contours"] = "contours_in"
            code_substitutions["x_output_hierarchy"] = "hierarchy_in"
            code_substitutions["x_output_hsvspec"] = "hsvspec_in"
            code_substitutions["x_output_im"] = "im_in"
            code_substitutions["x_output_objects"] = "objects_in"
            code_substitutions["x_output_rect"] = "rect_in"
        else:
            code_substitutions["x_output_annotated"] = "xstep.exec_annotated"
            code_substitutions["x_output_contours"] = "xstep.exec_contours"
            code_substitutions["x_output_hierarchy"] = "xstep.exec_hierarchy"
            code_substitutions["x_output_hsvspec"] = "xstep.exec_hsvspec"
            code_substitutions["x_output_im"] = "xstep.exec_im"
            code_substitutions["x_output_objects"] = "xstep.exec_objects"
            code_substitutions["x_output_rect"] = "xstep.exec_rect"
        code = self.cv_specs.code
        if code[-1:] != "\n":
            code += "\n"
        if script and (image_filters.FLAG_ISBASE in self.cv_specs.flags):
            code += "im_base = im_in\n"
        if self.cv_specs.annotate_code is not None:
            if show_annotation:
                code += "\n" + self.cv_specs.annotate_code
        if code != "":
            exec_code_str = code.format(**code_substitutions)
            return exec_code_str
        return ""

    def execute_step(self):
        execution_start = time.time()
        #
        # Collect output from prior steps
        #
        latest_base_image = None
        latest_im = None
        latest_contours = None
        latest_hierarchy = None
        latest_hsvspec = None
        latest_objects = None  # output of object identification filters
        latest_rect = None
        for ix, this in enumerate(self.steps):
            if ix >= self.ix:
                break
            if this.exec_im is not None:
                latest_im = this.exec_im
                if image_filters.FLAG_ISBASE in this.cv_specs.flags:
                    latest_base_image = this.exec_im
            if this.exec_contours is not None:
                latest_contours = this.exec_contours
            if this.exec_hierarchy is not None:
                latest_hierarchy = this.exec_hierarchy
            if this.exec_hsvspec is not None:
                latest_hsvspec = this.exec_hsvspec
            if this.exec_objects is not None:
                latest_objects = this.exec_objects
            if this.exec_rect is not None:
                latest_rect = this.exec_rect

        #
        # Create environment for this step's execution
        #
        exec_global_vars = {}
        for this in self.imports:
            if this[1] is not None:
                exec_global_vars[this[0]] = this[1]
        exec_global_vars["xstep"] = self
        exec_global_vars["im_base"] = latest_base_image
        exec_global_vars["im_in"] = latest_im
        exec_global_vars["contours_in"] = latest_contours
        exec_global_vars["hierarchy_in"] = latest_hierarchy
        exec_global_vars["hsvspec_in"] = latest_hsvspec
        exec_global_vars["objects_in"] = latest_objects
        exec_global_vars["rect_in"] = latest_rect

        for ix, this in enumerate(self.info_widgets):
            if ix < len(self.info_data):
                try:
                    this[0].replace_value(self.info_data[ix][0])
                    this[1].replace_value(self.info_data[ix][1])
                except:
                    # tried to execute deleted step
                    print("ExecuteStep()", self.ix, self.tab_title)
                    # raise
            else:
                this[0].replace_value("")
                this[1].replace_value("")

        trace = None
        self.exec_annotated = None
        self.exec_contours = None
        self.exec_hierarchy = None
        self.exec_hsvspec = None
        self.exec_im = None
        self.exec_objects = None
        self.exec_rect = None
        deposition = ""
        self.deposition.replace_value(deposition)
        exec_code_str = self.get_code_str(script=False)
        if exec_code_str != "":
            # print("EXEC", exec_code_str)
            if "im_in" in exec_global_vars:
                # print("XXXX-vv", exec_global_vars['im_in'].__class__.__name__)
                ximin = exec_global_vars["im_in"]
                # if isinstance(ximin, oc.Image):
                #    print("XXXX-im", ximin._im.__class__.__name__)
            try:
                exec(exec_code_str, exec_global_vars)
            except:
                trace = traceback.format_exc()
                print(trace)
        #
        # Step code has been executed, now update step tab to show results.
        #
        if trace is not None:
            deposition = trace + "\n\n" + deposition
            self.deposition.replace_value(deposition)
        if image_filters.FLAG_SLIDERS in self.cv_specs.flags:
            self.clear_info()
            self.add_info_sliders()
        if self.exec_annotated is not None:
            step_display_image = self.exec_annotated
        else:
            # maybe assert an error if there was annotation code which
            # didn't create an image
            if self.exec_im is None:
                step_display_image = latest_base_image
            else:
                step_display_image = self.exec_im
        if step_display_image is not None:
            # This can happen while steps are being changed
            self.image_widget.update_image(source_im=step_display_image.im)
        self.execution_time.replace_value(
            f"{(time.time() - execution_start) / 1000:f}ms"
        )
        return


class CvLab(vmqtt.VnavsNode):
    __slots__ = (
        "camera_iso",
        "camera_last_filename",
        "camera_shutter_speed",
        "delete_process_step_ix",
        "download_dir",
        "file_client",
        "gui_update_mode",
        "image",
        "last_pic_payload",
        "last_pic_time",
        "last_process_time",
        "load_filter_name",
        "load_new_filter_ct",
        "load_parms",
        "load_process_file_name",
        "loading",
        "local_cam",
        "new_step",
        "notebook",
        "notebook_add_id",
        "pic_continuous",
        "pic_fn",
        "pic_needed",
        "pic_source",
        "scripts_dir",
        "source_widget",
        "status_frame",
        "step_execution_needed",
        "thumbnail_frame",
        "tk",
    )

    def __init__(self):
        super().__init__(
            subscriptions=[
                vmqtt.Subscription(
                    vconst.cameraman_pic_ready_topic, handler=self.do_cameraman_pic_ready
                )
            ],
            single_threaded=True,
            broker_type="F",
            automatically_connect=False,
            wait_if_not_connected=False,
            select_timeout_secs=0.1,
            verbose=False,
        )
        self.load_process_file_name = None
        self.delete_process_step_ix = None
        self.file_client = vnavs_file_xfer_client.FileClient(verbose=False)
        self.download_dir = self.config.get("FileClient", "DownloadDir")
        self.download_dir = os.path.expanduser(
            self.download_dir
        )  # this expands tilde in path
        self.scripts_dir = self.config.get("MissionControl", "Scripts")

        self.load_filter_name = None
        self.load_parms = {}
        self.load_new_filter_ct = 0
        self.loading = False
        self.step_execution_needed = False

        self.image = image_analyzer.ImageAnalyzer()
        self.image.img_crop = (300, 200)
        self.image.img_crop = (250, 450)
        self.image.img_crop = (150, 550)
        self.image.img_crop = None
        self.image.img_cropped_height = 100
        self.image.img_fpath = "opencv_6"
        self.image.img_source_dir = "/volumes/pi/projects/vnavs/temp"
        self.image.img_fname_suffix = ""

        self.gui_update_mode = True
        self.tk = eztk.EasyTk()
        self.tk.tkw.title("VNAVS OpenCV Visualizer")
        self.status_frame = self.tk.add_label_frame("Status", row=1)
        self.thumbnail_frame = self.tk.add_label_frame("Thumbnails", row=2)
        self.notebook = self.tk.add_notebook(row=3, on_tab_selected=self.on_tab_selected)
        plus = self.notebook.add_tab("+")
        self.notebook_add_id = self.notebook.tkw.tabs()[-1]
        self.camera_iso = self.status_frame.add_entry_field("ISO", value=800)
        self.camera_shutter_speed = self.status_frame.add_entry_field(
            "Shutter Speed", value=10000, row=SAME_ROW, col=NEXT_COL
        )
        self.camera_last_filename = ""
        self.last_pic_payload = None
        self.last_pic_time = 0
        self.last_process_time = time.time()
        self.local_cam = None
        self.pic_needed = False
        self.pic_continuous = True
        self.pic_fn = None
        self.pic_source = None

        self.source_widget = self.status_frame.add_dropdown(
            s_items=[SRC_LOCAL_CAMERA, SRC_BOT_CAMERA],
            command=self.on_select_source,
            row=SAME_ROW,
            col=NEXT_COL,
        )
        self.status_frame.add_button(
            "Capture", command=self.on_capture_image, row=SAME_ROW, col=NEXT_COL
        )
        self.status_frame.add_button(
            "Continuous", command=self.on_continuous_image, row=SAME_ROW, col=NEXT_COL
        )
        self.status_frame.add_button(
            "Open File", command=self.on_open_image_file, row=SAME_ROW, col=NEXT_COL
        )
        self.status_frame.add_button(
            "Open Process", command=self.open_process_file, row=SAME_ROW, col=NEXT_COL
        )
        self.status_frame.add_button(
            "Save Process", command=self.save_process_file, row=SAME_ROW, col=NEXT_COL
        )

        ProcessStep.app = self
        self.new_step = None
        self.gui_update_mode = False

    def configure_camera(self):
        print("ConfigureCamera", self.pic_source, SRC_BOT_CAMERA)
        payload = {}
        payload["iso"] = self.camera_iso.value()
        payload["shutter_speed"] = self.camera_shutter_speed.value()
        if self.pic_source == SRC_BOT_CAMERA:
            print(payload)
            self.publish(vconst.cameraman_orders_topic, payload)

    def configure_image_source(
        self, path=None, new_image=None, iso=None, shutter_speed=None, colorcode=None
    ):
        new_parms = {}
        if len(ProcessStep.steps) == 0:
            ProcessStep(
                image_filters.FILTER_NAME_IMAGE,
                parms=new_parms,
                where=self.notebook_add_id,
            )
        else:
            ProcessStep.steps[0].set_filter(
                filter_name=image_filters.FILTER_NAME_IMAGE, new_parms=new_parms
            )
        if (new_image is None) and (path is not None):
            new_image = cv2.imread(path)
            colorcode = oc.IM_BGR
        if isinstance(new_image, oc.Image):
            ProcessStep.steps[0].source_im = new_image
            ProcessStep.steps[0].source_path = path
        else:
            ProcessStep.steps[0].source_im = oc.Image(im=new_image, colorcode=colorcode)
            ProcessStep.steps[0].source_path = path
        ProcessStep.steps[0].clear_info()
        if path is not None:
            ProcessStep.steps[0].add_info("Path", path)
        if iso is not None:
            ProcessStep.steps[0].add_info("ISO", iso)
        if shutter_speed is not None:
            ProcessStep.steps[0].add_info("Shutter", shutter_speed)
        if colorcode is not None:
            ProcessStep.steps[0].add_info("Colorcode", colorcode)
        self.step_execution_needed = True

    def open_process_file(self):
        self.load_process_file_name = self.status_frame.do_file_name_dialog(
            directory=self.scripts_dir, file_types=ProcessStep.process_file_types
        )

    # While interacting with the process the parms dictionary can get
    # cluttered with values that are not needed for the current filter. This
    # is intentional because it lets you go back to previous filter with the
    # parms you had set. Save/LoadProcessFile keep thse dirty values. There
    # is something to be said to filter the parts based on the current step.
    def load_process_file(self, fn):
        # load_filter_name, load_parms and load_new_filter_ct are essentially local variables.
        # They are made instance properties so they can be modified by AssignFilter()
        self.load_filter_name = None
        self.load_parms = {}
        self.load_new_filter_ct = 0
        self.loading = True

        def AssignFilter():
            # We redefine the existing steps before creating new ones. This is done because if we try to delete all the
            # existitng tabs, OnTabSelected() creates a default tab as soon as we delete the last one.
            # This is neater than the options for modifying OnTabSelected() behavior and may be slightly
            # more efficient.
            self.load_new_filter_ct += 1
            print("ASSIGN", self.load_filter_name, self.load_new_filter_ct)
            if self.load_new_filter_ct <= len(ProcessStep.steps):
                ProcessStep.steps[self.load_new_filter_ct - 1].set_filter(
                    filter_name=self.load_filter_name, new_parms=self.load_parms
                )
            else:
                ProcessStep(
                    filter_name=self.load_filter_name,
                    parms=self.load_parms,
                    where=self.notebook_add_id,
                )
            self.load_filter_name = None
            self.load_parms = {}

        # This needs error checking. Needs a mechanism for displaying errors to user.
        # Parm values can be checked via GetParm()
        f = open(fn, "r")
        for ln in f:
            ln = ln.strip()
            if ln == "":
                continue
            print("LOAD", self.load_filter_name, ln)
            if ln[0] == "/":
                if self.load_filter_name is not None:
                    AssignFilter()
                self.load_filter_name = ln[1:]
            else:
                sep = ln.find("=")
                if sep > 0:
                    key = ln[:sep][5:]  # eliminate "parm." prefix
                    value = ln[sep + 1 :]
                    self.load_parms[key] = value
        if self.load_filter_name is not None:
            AssignFilter()
        f.close()
        while len(ProcessStep.steps) > self.load_new_filter_ct:
            # The old process had more steps than the current, get rid of the old steps.
            ix = len(ProcessStep.steps) - 1
            print("XXXX", ix)
            self.delete_process_step(ix)
        self.source_widget.replace_value(
            SRC_LOCAL_CAMERA
        )  # temporary - needs more options
        self.step_execution_needed = True
        self.loading = False

    def save_process_file(self):
        drk_fn = self.status_frame.do_file_save_as_name_dialog(
            directory=self.scripts_dir,
            file_name=self.load_process_file_name,
            file_types=ProcessStep.process_file_types,
        )
        fn_root, fn_ext = os.path.splitext(drk_fn)
        drk_f = open(drk_fn, "w")
        for this_step in ProcessStep.steps:
            drk_f.write(f"/{this_step.cv_filter_name}\n")
            for this_key, this_value in this_step.parm_values.items():
                drk_f.write(f"parm.{this_key}={this_value}\n")
        drk_f.close()
        cam_fn = fn_root + "." + ProcessStep.cameraman_file_extension
        py_fn = fn_root + "." + ProcessStep.python_file_extension
        ProcessStep.write_cameraman(cam_fn)
        ProcessStep.write_program(py_fn)

    def on_capture_image(self):
        print("OnCaptureImage()")
        self.pic_needed = True
        self.pic_continuous = False
        if self.source_widget.value() is None:
            print("On Capture update source")
            self.source_widget.replace_value(SRC_LOCAL_CAMERA)
        self.configure_camera()  # we don't wait for this to take effect

    def on_continuous_image(self):
        self.pic_continuous = True
        if self.source_widget.value() is None:
            self.source_widget.replace_value(SRC_LOCAL_CAMERA)
        self.configure_camera()  # we don't wait for this to take effect

    def on_open_image_file(self):
        self.pic_continuous = False
        self.pic_needed = False
        fn = self.status_frame.do_file_name_dialog()
        self.configure_image_source(path=fn)

    def on_select_source(self, *args):
        self.pic_source = self.source_widget.value()
        if self.pic_source == SRC_LOCAL_CAMERA:
            self.local_cam = cameraman.MacbookCamera()
        elif self.pic_source == SRC_BOT_CAMERA:
            self.connect_to_mqtt_server()

    def on_tab_selected(self, x):
        # This ends up with the initial view being a default filter tab created here
        # and the plus tab to add filters. When the page is initialialy displayed, the
        # only tab that exists is the plus. It is automatically selected by TK, which
        # executes this callback, creating the default filter as if the user had hit plus.
        # This was unexpected but probably the best compromise.
        #
        # The above makes it impossible to delete all filter tabs. As soon as the last
        # one is deleted, the plus tab is selected and we end up here, creating a default
        # filter. Again not expected, but not a serious usability issue.
        #
        # self.gui_update_mode added because deleting the last tab caused a similar
        # problem to above by making the plus tab active for a moment while re-aranging
        # the notebook. It turns out that select() gets flashed a lot while updating
        # the gui and TK delivers events very quickly.
        #
        if self.gui_update_mode:
            return
        tabid = self.notebook.tkw.select()
        print("CvLab.OnTabSelected()", tabid, self.notebook_add_id)
        if tabid == self.notebook_add_id:
            # The plus tab was clicked, add a new tab just before that.
            # We want the new tab to be selected but TK ignores select() here,
            # because this is an on_select() callback. To get around this,
            # we set self.new_step and make the selection within update loop.
            self.new_step = ProcessStep(where=tabid)

    def do_cameraman_pic_ready(self, payload):
        # Do as little as possible here in mqtt thread.
        # Process image in tk thread.
        # print("rmsg_cameraman_pic_ready()", payload)
        self.last_pic_payload = payload

    def delete_process_step(self, ix):
        # Don't forget that there is one more tab than there
        # are processing steps because of the add tab (self.notebook_add_id)
        #
        target_step = ProcessStep.steps[ix]
        print("cvlab.DeleteProcessStep() BEGIN", ix)
        self.gui_update_mode = True
        self.notebook.delete_tab(ix)
        target_step.thumbnail.destroy()
        ProcessStep.steps.pop(ix)
        for adjust_ix, this_step in enumerate(ProcessStep.steps[ix:]):
            this_step.ix = ix + adjust_ix
            this_step.tab_title = f"Step {this_step.ix}"
            print("cvlab.DeleteProcessStep() rename tab", ix, this_step.tab_title)
            self.notebook.tkw.tab(this_step.ix, text=this_step.tab_title)
        self.step_execution_needed = True
        self.gui_update_mode = False
        ProcessStep.steps[ix - 1].select_tab(None)
        print("cvlab.DeleteProcessStep() END", len(ProcessStep.steps))

    #
    # All work gets done here in DoLoop() in the main thread.
    # Methods in the Tkinter and VnavsMqtt threads should just set flags
    # and return quickly.
    #
    def client_loop_code(self):
        if self.loading:
            # This was added in order to avoid crashes due to trying to load images
            # while a new process is being loaded. I am a little surprised that
            # we get here during that process.
            return

        if self.delete_process_step_ix is not None:
            self.delete_process_step(self.delete_process_step_ix)
        self.delete_process_step_ix = None

        if self.load_process_file_name is not None:
            # print("LOAD PROCESS", len(ProcessStep.steps))
            self.load_process_file(self.load_process_file_name)
        self.load_process_file_name = None

        if self.new_step is not None:
            self.new_step.select_tab(None)
            self.new_step = None

        #
        # Get a new image if needed.
        #
        new_image = None
        path = None
        iso = None
        shutter_speed = None
        colorcode = None
        if self.pic_continuous or self.pic_needed:
            # We need a new image
            if self.pic_source == SRC_LOCAL_CAMERA:
                self.pic_needed = False  # don't process others until requested
                new_image = self.local_cam.capture_image()
                iso = self.local_cam.iso
                shutter_speed = self.local_cam.shutter_speed
                colorcode = self.local_cam.colorcode
            elif self.pic_source == SRC_BOT_CAMERA:
                if (self.last_pic_payload is not None) and (
                    (time.time() - self.last_pic_time) > 1.0
                ):
                    self.pic_needed = False  # if single frame mode, mark done
                    payload = (
                        self.last_pic_payload
                    )  # capture payload because self.last_pic_payload is updated asynchronously
                    self.pic_fn = payload["filename"]
                    path = os.path.join(self.download_dir, self.pic_fn)
                    # print("DoLoop() GetFile: ", path)
                    if not self.file_client.get_file("i", self.pic_fn, path=path):
                        print("Unable to fetch PIC", self.pic_fn)
                        return
                    self.last_pic_time = time.time()
                    iso = payload["iso"]
                    shutter_speed = payload["shutter_speed"]
                    # print("CAM", iso, shutter_speed)
            if (new_image is not None) or (path is not None):
                # We have a new image. We might not. We don't get a picture if Capture hasn't been
                # clicked or if this loop is running faster than new images are published in
                # continuous SRC_BOT_CAMERA mode.
                # print("DoLoop() process image ", path, new_image is not None)
                self.configure_image_source(
                    path=path,
                    new_image=new_image,
                    iso=iso,
                    shutter_speed=shutter_speed,
                    colorcode=colorcode,
                )
        if (not self.pic_continuous) and ((time.time() - self.last_process_time) > 0.1):
            # We don't want to process the image on every pass of the loop because that can use too many CPU
            # cycles and make the system laggy. In continuous mode, we update frequently with each new image.
            # When in single capture mode, we need to update periodically so reflect the user updating
            # controls. Especially sliders.
            self.step_execution_needed = True
        if self.step_execution_needed:
            ProcessStep.execute_all_steps()
            self.step_execution_needed = False
            self.last_process_time = time.time()
        self.tk.update()
        # when tk is destroyed by close window, self.disconnect()	# stop mqtt client loop


if __name__ == "__main__":
    m = CvLab()
    m.main_loop()
