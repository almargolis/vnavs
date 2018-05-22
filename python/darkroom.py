from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import codecs
import json
import math
import os
import sys
import traceback
import types
from PIL import ImageTk, Image

import threading
import time

import cv2
import numpy as np

import cameraman
import easytk
from easytk import FIRST_ROW, SAME_ROW, NEXT_ROW, OVERLAY_ROW, SAME_COL, NEXT_COL, LEFT_COL, RIGHT_COL, OVERLAY_COL
import OpticChiasm
import vnavs_mqtt
import vnavs_const as vconst

BOT_1_MAP_TRANSPOSE = [

			[ -1.30565584e-01,  -1.56472861e+00,   4.58333935e+02],
			[ -2.57693172e-15,  -3.10871493e+00,   1.04702945e+03],
			[ -2.95275685e-18,  -3.83178162e-03,   1.00000000e+00]
		]

BOT_1_H = np.array(BOT_1_MAP_TRANSPOSE, dtype="float32")

SRC_LOCAL_CAMERA = 'local'
SRC_BOT_CAMERA = 'bot'

class ProcessStep(object):
    __slots__ = ('cv_filter_name', 'cv_specs',
			'deposition',
			'exec_annotated', 'exec_contours', 'exec_hierarchy', 'exec_hsvspec', 'exec_im', 'exec_lines', 'exec_rect',
			'filter_selection',
			'image_widget', 'info_data', 'info_widgets', 'input_panel', 'ix', 'output_panel',
			'parm_widgets', 'parm_values', 'parms_specs', 'point_target',
			'source_im', 'source_path',
			'tab', 'tab_title', 'thumbnail',
			'zoom_popup'
		)
    app = None
    steps = []
    process_file_extension = 'drk'
    process_file_types = (('Darkroom Process', '*.'+process_file_extension), )
    imports = []                   # imports for exec or script
    # imports.append(('__builtins__', __builtins__, None))
    imports.append(('cv2', cv2, None))
    imports.append(('np', np, 'numpy'))
    imports.append(('oc', OpticChiasm, 'OpticChiasm'))
    imports.append(('cameraman', None, None))

    def __init__(self, FilterName=None, Where=None, Parms={}):
        self.ix = len(self.steps)
        self.exec_im = None				# this is an OpticChiasm.Image produced by the filter
        self.steps.append(self)
        self.cv_filter_name = None			# this gets set by NewFilter()

        self.parm_values = Parms			# key is FilterParm.name
        self.tab_title = "Step %d" % (self.ix)
        self.tab = self.app.notebook.AddTab(self.tab_title, Where=Where)
        self.input_panel = self.tab.AddLabelFrame('Input')
        self.output_panel = self.tab.AddLabelFrame('Output')
        self.zoom_popup = None
        #
        # input_panel
        #
        self.filter_selection = self.input_panel.AddListbox('Filters', OpticChiasm.ImageFilter.filter_names, Selection=FilterName, command=self.NewFilter, rowspan=4)
        self.info_data = []
        self.info_widgets = []
        for ix in range(6):
            info_label = self.input_panel.AddLabel('', row=NEXT_ROW, col=LEFT_COL)
            info_value = self.input_panel.AddLabel('', row=SAME_ROW, col=NEXT_COL)
            self.info_widgets.append((info_label, info_value))
        self.parm_widgets = []
        for ix in range(8):
            if ix == 0:
                parm_row = self.filter_selection.row
                parm_col = NEXT_COL
            else:
                parm_row = NEXT_ROW
                parm_col = self.parm_widgets[0][1].col
            parm_caption = 'Parm{0}'.format(ix+1)
            entry_label = self.input_panel.AddLabel(parm_caption, row=parm_row, col=parm_col)
            entry_box = self.input_panel.AddEntryField(row=SAME_ROW, col=NEXT_COL, OnDoubleClick=self.OnPickPoint)
            entry_slider = self.input_panel.AddSliderField(col=OVERLAY_COL)
            self.parm_widgets.append([entry_box, entry_label, entry_box, entry_slider])
        self.input_panel.AddButton('Run', command=self.OnExecuteStep, col=parm_col)
        self.input_panel.AddButton('Delete Step', command=self.OnDeleteStep, row=SAME_ROW, col=NEXT_COL)
        #
        # output_panel
        #
        self.image_widget = self.output_panel.AddCanvas(OnClick=self.OnImageClick, rowspan=2)
        self.execution_time = self.output_panel.AddLabel(row=FIRST_ROW, col=NEXT_COL)
        self.deposition = self.output_panel.AddLabel(row=NEXT_ROW, col=SAME_COL)
        self.thumbnail = self.app.thumbnailFrame.AddLabelImage(thumbnailof=self.image_widget, row=0, col=NEXT_COL)
        self.thumbnail.tkw.bind("<Button-1>", self.SelectTab)
        self.source_im = None			# captured image
        self.source_path = None
        self.point_target = None
        self.SetFilter()


    #
    # info_data are display fields under the image.
    # They are generally outputs from the step processing.
    #
    def ClearInfo(self):
        self.info_data = []

    def AddInfo(self, label, value):
        ix = len(self.info_data)
        self.info_data.append((label, value))
        return ix

    def AddInfoSliders(self):
        for ix, this in enumerate(self.parm_widgets):
            if (ix < len(self.parms_specs)) and (self.parms_specs[ix].use_slider):
                self.AddInfo(self.parms_specs[ix].caption, this[0].Value())

    def SetInfo(self, ix, label, value):
        while len(self.info_data) < (ix + 1):
            self.info_data.append(('', ''))
        self.info_data[ix] = (label, value)

    def OnPickPoint(self, event):
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
            self.point_target.ReplaceValue('<click image>')

    def OnExecuteStep(self):
        # Click this to refresh after changing a parameter. We don't automatically do
        # that in case intermediate updates might fail when make several changes.
        self.SetFilter()			# This saves the parameter values
        self.app.step_execution_needed = True

    def OnDeleteStep(self):
        # This event is here because it is associated with the step and
        # identifies which event is to be deleted. We can't do the
        # actual deletion here because because we also need to delete
        # this ProcessStep() instance.
        self.app.delete_process_step_ix = self.ix

    def SelectTab(self, event):
        # This is called as both a TK event and a general method.
        # Event is None if called as a general method.
        self.app.notebook.tkw.select(self.tab.tkw)

    def OnImageClick(self, event):
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
            v = "{},{}".format(int(x), int(y))
            self.point_target.ReplaceValue(v)
            self.point_target = None
            return
        # Default action: pop-up a window with a larger image.
        print("ZOOM IM", self.exec_im.__class__.__name__)
        self.exec_im.Write('zoom.jpeg')
        # Reference to popup must be maintained or image gets lost in garbage collection.
        self.zoom_popup = self.app.tk.MakePopupWindow(self.cv_filter_name)
        self.zoom_popup.AddLabel("Sum Thing")
        canvas = self.zoom_popup.AddCanvas(width=800, height=400)
        canvas.UpdateImage(pil_fn='zoom.jpeg')

    @classmethod
    def ExecuteAllSteps(cls):
        for this_step in cls.steps:
            this_step.ExecuteStep()

    def SaveParameters(self):
        for ix, this_widget in enumerate(self.parm_widgets):
            if this_widget[0].parm_id is not None:
                # save prior value
                self.parm_values[this_widget[0].parm_id] = this_widget[0].Value()

    def NewFilter(self, *args):
        # TK callbacks seem to incude *args
        self.SetFilter()
        self.app.step_execution_needed = True

    def SetFilter(self, FilterName=None, NewParms=None):
        self.SaveParameters()
        if NewParms is not None:
            for key, value in NewParms.items():
                self.parm_values[FilterName + '_' + key] = value
        if FilterName is None:
            new_filter_name = self.filter_selection.Value()
        else:
            new_filter_name = FilterName
        #print("SetFilter()", new_filter_name,  self.cv_filter_name)
        if new_filter_name != self.cv_filter_name:
            self.filter_selection.ReplaceValue(new_filter_name)
            self.cv_filter_name = new_filter_name
            self.cv_specs = OpticChiasm.ImageFilter.filters[self.cv_filter_name]
            self.parms_specs = self.cv_specs.parms
            for ix, this_widget in enumerate(self.parm_widgets):
                if ix < len(self.parms_specs):
                    parm_name = self.cv_filter_name + '_' + self.parms_specs[ix].name
                    parm_caption = self.parms_specs[ix].caption
                    parm_default_value = self.parms_specs[ix].default
                    if parm_name not in self.parm_values:
                        self.parm_values[parm_name] = parm_default_value
                    parm_value = self.parm_values[parm_name]
                    if self.parms_specs[ix].use_slider:
                        slider = this_widget[3]
                        this_widget[0] = slider				# use slider widget
                        min_value = self.parms_specs[ix].min_value
                        if min_value is None:
                            min_value = 0
                        max_value = self.parms_specs[ix].max_value
                        if max_value is None:
                            max_value = 0
                        slider.tkw.config(from_=min_value, to=max_value)
                    else:
                        this_widget[0] = this_widget[2]			# use entry box widget
                else:
                    parm_name = None
                    parm_caption = "Parm" + str(ix+1)
                    parm_value = ""
                    this_widget[0] = this_widget[2]			# use entry box widget
                this_widget[1].ReplaceValue(parm_caption)
                this_widget[0].tkw.lift()				# make active control visible (top of stack)
                this_widget[0].ReplaceValue(parm_value)
                this_widget[0].parm_id = parm_name

    @classmethod
    def WriteScript(cls):
        f = codecs.open('python/darkroom_script.py', 'w', encoding='utf-8')
        f.write('\n')


        f.write('from __future__ import absolute_import, division, print_function\n')
        f.write('from builtins import (bytes, str, open, super, range,\n')
        f.write('              zip, round, input, int, pow, object)\n')
        f.write('\n')

        for this in cls.imports:
            if this[2] is None:
                f.write('import {}\n'.format(this[0]))
            else:
                f.write('import {} as {}\n'.format(this[2], this[0]))

        f.write('\n')
        source_path = cls.steps[0].source_path
        if source_path is None:
            f.write('cam = cameraman.macbook_camera()\n')
            f.write('im_in = cam.capture_image()\n')
        else:
            f.write('im_in = oc.ReadImage("{}")\n'.format(source_path))
        f.write('im_base = im_in.copy()\n')
        f.write('\n')

        for ix, this in enumerate(cls.steps[1:]):
            f.write('#\n# Step {} - {}\n#\n'.format(this.ix, this.cv_filter_name))
            code_str = this.GetCodeStr(Script=True)
            f.write(code_str)

        if cls.steps[-1].cv_specs.annotate_code is None:
            display_image = 'im_in'
        else:
            display_image = 'annotated'

        f.write('\n')
        f.write('cv2.imshow("im_in", {display}.im)\n'.format(display=display_image))
        f.write('cv2.waitKey(0)\n')
        f.write('cv2.destroyAllWindows()\n')
        f.close()

    def GetCodeStr(self, Script=True):
        self.SaveParameters()
        code_substitutions = {}
        for this_parm in self.parms_specs:
            raw_value = self.parm_values[self.cv_filter_name + '_' + this_parm.name]
            code_substitutions[this_parm.name] = this_parm.GetValue(raw_value)
        if Script:
            code_substitutions['x_output_annotated'] = 'annotated'
            code_substitutions['x_output_contours'] = 'contours_in'
            code_substitutions['x_output_hierarchy'] = 'hierarchy_in'
            code_substitutions['x_output_hsvspec'] = 'hsvspec_in'
            code_substitutions['x_output_im'] = 'im_in'
            code_substitutions['x_output_lines'] = 'lines_in'
            code_substitutions['x_output_rect'] = 'rect_in'
        else:
            code_substitutions['x_output_annotated'] = 'xstep.exec_annotated'
            code_substitutions['x_output_contours'] = 'xstep.exec_contours'
            code_substitutions['x_output_hierarchy'] = 'xstep.exec_hierarchy'
            code_substitutions['x_output_hsvspec'] = 'xstep.exec_hsvspec'
            code_substitutions['x_output_im'] = 'xstep.exec_im'
            code_substitutions['x_output_lines'] = 'xstep.exec_lines'
            code_substitutions['x_output_rect'] = 'xstep.exec_rect'
        code = self.cv_specs.code
        if code[-1:] != '\n':
            code += '\n'
        if Script and (OpticChiasm.FLAG_ISBASE in self.cv_specs.flags):
            code += 'im_base = im_in\n'
        if self.cv_specs.annotate_code is not None:
            code += '\n' + self.cv_specs.annotate_code
        if code != '':
            exec_code_str = code.format(**code_substitutions)
            return exec_code_str
        return ''

    def ExecuteStep(self):
        execution_start = time.time()
        #
        # Collect output from prior steps
        #
        latest_base_image = None
        latest_im = None
        latest_contours = None
        latest_hierarchy = None
        latest_hsvspec = None
        latest_lines = None
        latest_rect = None
        for ix, this in enumerate(self.steps):
            if ix >= self.ix:
                break
            if this.exec_im is not None:
                latest_im = this.exec_im
                if OpticChiasm.FLAG_ISBASE in this.cv_specs.flags:
                    latest_base_image = this.exec_im
            if this.exec_contours is not None:
                latest_contours = this.exec_contours
            if this.exec_hierarchy is not None:
                latest_hierarchy = this.exec_hierarchy
            if this.exec_hsvspec is not None:
                latest_hsvspec = this.exec_hsvspec
            if this.exec_lines is not None:
                latest_lines = this.exec_lines
            if this.exec_rect is not None:
                latest_rect = this.exec_rect

        #
        # Create environment for this step's execution
        #
        exec_global_vars = {}
        for this in self.imports:
            if this[1] is not None:
                exec_global_vars[this[0]] = this[1]
        exec_global_vars['xstep'] = self
        exec_global_vars['im_base'] = latest_base_image
        exec_global_vars['im_in'] = latest_im
        exec_global_vars['contours_in'] = latest_contours
        exec_global_vars['hierarchy_in'] = latest_hierarchy
        exec_global_vars['hsvspec_in'] = latest_hsvspec
        exec_global_vars['lines_in'] = latest_lines
        exec_global_vars['rect_in'] = latest_rect

        for ix, this in enumerate(self.info_widgets):
            if ix < len(self.info_data):
                this[0].ReplaceValue(self.info_data[ix][0])
                this[1].ReplaceValue(self.info_data[ix][1])
            else:
                this[0].ReplaceValue('')
                this[1].ReplaceValue('')

        trace = None
        self.exec_annotated = None
        self.exec_contours = None
        self.exec_hierarchy = None
        self.exec_hsvspec = None
        self.exec_im = None
        self.exec_lines = None
        self.exec_rect = None
        deposition = ''
        self.deposition.ReplaceValue(deposition)
        exec_code_str = self.GetCodeStr(Script=False)
        if exec_code_str != '':
            print("EXEC", exec_code_str)
            if 'im_in' in exec_global_vars:
                print("XXXX-vv", exec_global_vars['im_in'].__class__.__name__)
                ximin = exec_global_vars['im_in']
                if isinstance(ximin, OpticChiasm.Image):
                    print("XXXX-im", ximin._im.__class__.__name__)
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
            self.deposition.ReplaceValue(deposition)
        if OpticChiasm.FLAG_SLIDERS in self.cv_specs.flags:
            self.ClearInfo()
            self.AddInfoSliders()
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
            self.image_widget.UpdateImage(source_im=step_display_image.im)
        self.execution_time.ReplaceValue("{:f}ms".format((time.time() - execution_start) / 1000))
        return


class Darkroom(vnavs_mqtt.mqtt_node):
    __slots__ = (
				'camera_iso', 'camera_last_filename', 'camera_shutter_speed',
				'delete_process_step_ix', 'downloadDir', 'file_client', 'image',
				'last_pic_payload', 'load_filter_name', 'load_new_filter_ct', 'load_parms', 'load_process_file_name',
				'loading', 'local_cam',
				'new_step', 'notebook', 'notebook_add_id',
				'pic_continuous', 'pic_fn', 'pic_needed', 'pic_source',
				'scriptsDir', 'source_widget', 'statusFrame',
 				'step_execution_needed',
				'thumbnailFrame', 'tk'
		)
    def __init__(self):
        super().__init__(Subscriptions=[vconst.cameraman_pic_ready_topic],
					SingleThreaded=True, BrokerType='F',
					AutomaticallyConnect=False, BlockIfNotConnected=False, SelectTimeoutSecs=0.1,
					Verbose=False)
        self.load_process_file_name = None
        self.delete_process_step_ix = None
        self.file_client = vnavs_mqtt.FileClient(Verbose=False)
        self.downloadDir = self.config.get("FileClient", "DownloadDir")
        self.downloadDir = os.path.expanduser(self.downloadDir)               # this expands tilde in path
        self.scriptsDir = self.config.get("MissionControl", "Scripts")

        self.load_filter_name = None
        self.load_parms = {}
        self.load_new_filter_ct = 0
        self.loading = False
        self.step_execution_needed = False

        self.image = OpticChiasm.ImageAnalyzer()
        self.image.img_crop=(300,200)
        self.image.img_crop=(250,450)
        self.image.img_crop=(150,550)
        self.image.img_crop=None
        self.image.img_cropped_height = 100
        self.image.img_fpath = 'opencv_6'
        self.image.img_source_dir = '/volumes/pi/projects/vnavs/temp'
        self.image.img_fname_suffix = ''

        self.tk = easytk.EasyTk()
        self.tk.tkw.title("VNAVS OpenCV Visualizer")
        self.statusFrame = self.tk.AddLabelFrame('Status', row=1)
        self.thumbnailFrame = self.tk.AddLabelFrame('Thumbnails', row=2)
        self.notebook = self.tk.AddNotebook(row=3, OnTabSelected=self.OnTabSelected)
        plus = self.notebook.AddTab('+')
        self.notebook_add_id = self.notebook.tkw.tabs()[-1]
        self.camera_iso = self.statusFrame.AddEntryField('ISO', value=800)
        self.camera_shutter_speed = self.statusFrame.AddEntryField('Shutter Speed', value=10000, row=SAME_ROW, col=NEXT_COL)
        self.camera_last_filename = ''
        self.last_pic_payload = None
        self.local_cam = None
        self.pic_needed = False
        self.pic_continuous = True
        self.pic_fn = None
        self.pic_source = None

        self.source_widget = self.statusFrame.AddDropDown(s_items=[SRC_LOCAL_CAMERA, SRC_BOT_CAMERA], command=self.OnSelectSource, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Capture', command=self.OnCaptureImage, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Continuous', command=self.OnContinuousImage, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Open File', command=self.OnOpenImageFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Open Process', command=self.OpenProcessFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Save Process', command=self.SaveProcessFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Script', command=ProcessStep.WriteScript, row=SAME_ROW, col=NEXT_COL)

        ProcessStep.app = self
        self.new_step = None

    def ConfigureCamera(self):
        print("ConfigureCamera", self.pic_source, SRC_BOT_CAMERA)
        payload = {}
        payload['iso'] = self.camera_iso.Value()
        payload['shutter_speed'] = self.camera_shutter_speed.Value()
        if self.pic_source == SRC_BOT_CAMERA:
            print(payload)
            self.Publish(vconst.cameraman_orders_topic, payload)

    def ConfigureImageSource(self, path=None, new_image=None, iso=None, shutter_speed=None, colorcode=None):
        new_parms = {}
        if len(ProcessStep.steps) == 0:
            ProcessStep(OpticChiasm.FILTER_NAME_IMAGE, Parms=new_parms, Where=self.notebook_add_id)
        else:
            ProcessStep.steps[0].SetFilter(FilterName=OpticChiasm.FILTER_NAME_IMAGE, NewParms=new_parms)
        if (new_image is None) and (path is not None):
            new_image = cv2.imread(path)
            colorcode = OpticChiasm.IM_BGR
        if isinstance(new_image, OpticChiasm.Image):
            ProcessStep.steps[0].source_im = new_image
            ProcessStep.steps[0].source_path = path
        else:
            ProcessStep.steps[0].source_im = OpticChiasm.Image(im=new_image, colorcode=colorcode)
            ProcessStep.steps[0].source_path = path
        ProcessStep.steps[0].ClearInfo()
        if path is not None:
            ProcessStep.steps[0].AddInfo('Path', path)
        if iso is not None:
            ProcessStep.steps[0].AddInfo('ISO', iso)
        if shutter_speed is not None:
            ProcessStep.steps[0].AddInfo('Shutter', shutter_speed)
        if colorcode is not None:
            ProcessStep.steps[0].AddInfo('Colorcode', colorcode)
        self.step_execution_needed = True

    def OpenProcessFile(self):
        self.load_process_file_name = self.statusFrame.DoFileNameDialog(Dir=self.scriptsDir, FileTypes=ProcessStep.process_file_types)

    # While interacting with the process the parms dictionary can get
    # cluttered with values that are not needed for hte current filter. This
    # is intentional because it lets you go back to previous filter with the
    # parms you had set. Save/LoadProcessFile keep thse dirty values. There
    # is something to be said to filter the parts based on the current step.
    def LoadProcessFile(self, fn):
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
                ProcessStep.steps[self.load_new_filter_ct-1].SetFilter(FilterName=self.load_filter_name, NewParms=self.load_parms)
            else:
                ProcessStep(FilterName=self.load_filter_name, Parms=self.load_parms, Where=self.notebook_add_id)
            self.load_filter_name = None
            self.load_parms = {}
        # This needs error checking. Needs a mechanism for displaying errors to user.
        # Parm values can be checked via GetParm()
        f = open(fn, 'r')
        for ln in f:
            ln = ln.strip()
            if ln == '':
                continue
            print("LOAD", self.load_filter_name, ln)
            if ln[0] == '/':
                if self.load_filter_name is not None:
                    AssignFilter()
                self.load_filter_name = ln[1:]
            else:
                sep = ln.find('=')
                if sep > 0:
                    key = ln[:sep][5:]				# eliminate "parm." prefix
                    value = ln[sep+1:]
                    self.load_parms[key] = value
        if self.load_filter_name is not None:
            AssignFilter()
        f.close()
        while len(ProcessStep.steps) > self.load_new_filter_ct:
            # The old process had more steps than the current, get rid of the old steps.
            ix = len(ProcessStep.steps) - 1
            print("XXXX", ix)
            self.DeleteProcessStep(ix)
        self.source_widget.ReplaceValue(SRC_LOCAL_CAMERA)	# temporary - needs more options
        self.step_execution_needed = True
        self.loading = False

    def SaveProcessFile(self):
        fn = self.statusFrame.DoFileSaveAsNameDialog(Dir=self.scriptsDir,
							FileName=self.load_process_file_name,
							FileTypes=ProcessStep.process_file_types)
        f = open(fn, 'w')
        for this_step in ProcessStep.steps:
            f.write(u'/{}\n'.format(this_step.cv_filter_name))
            for this_key, this_value in this_step.parm_values.items():
                f.write(u'parm.{}={}\n'.format(this_key, this_value))
        f.close()

    def OnCaptureImage(self):
        print("OnCaptureImage()")
        self.pic_needed = True
        self.pic_continuous = False
        if self.source_widget.Value() is None:
            print("On Capture update source")
            self.source_widget.ReplaceValue(SRC_LOCAL_CAMERA)
        self.ConfigureCamera()					# we don't wait for this to take effect

    def OnContinuousImage(self):
        self.pic_continuous = True
        if self.source_widget.Value() is None:
            self.source_widget.ReplaceValue(SRC_LOCAL_CAMERA)
        self.ConfigureCamera()					# we don't wait for this to take effect

    def OnOpenImageFile(self):
        self.pic_continuous = False
        self.pic_needed = False
        fn = self.statusFrame.DoFileNameDialog()
        self.ConfigureImageSource(path=fn)

    def OnSelectSource(self, *args):
        self.pic_source = self.source_widget.Value()
        if self.pic_source == SRC_LOCAL_CAMERA:
            self.local_cam = cameraman.macbook_camera()
        elif self.pic_source == SRC_BOT_CAMERA:
            self.ConnectToMqttServer()

    def OnTabSelected(self, x):
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
        tabid = self.notebook.tkw.select()
        if tabid == self.notebook_add_id:
            # The plus tab was clicked, add a new tab just before that.
            # We want the new tab to be selected but TK ignores select() here,
            # because this is an on_select() callback. To get around this,
            # we set self.new_step and make the selection within update loop.
            self.new_step = ProcessStep(Where=tabid)


    def rmsg_cameraman_pic_ready(self, payload):
        # Do as little as possible here in mqtt thread.
        # Process image in tk thread.
        #print("rmsg_cameraman_pic_ready()", payload)
        self.last_pic_payload = payload

    def DeleteProcessStep(self, ix):
        self.notebook.DeleteTab(ix)
        ProcessStep.steps.pop(ix)
        for adjust_ix, this_step in enumerate(ProcessStep.steps[ix:]):
            this_step.ix = ix + adjust_ix
            this_step.tab_title = "Step %d" % (this_step.ix)
            self.notebook.tkw.tab(ix, text=this_step.tab_title)
        ProcessStep.steps[ix-1].SelectTab(None)
        self.step_execution_needed = True

    #
    # All work gets done here in DoLoop() in the main thread.
    # Methods in the Tkinter and VnavsMqtt threads should just set flags
    # and return quickly.
    #
    def DoLoop(self):
        if self.loading:
            # This was added in order to avoid crashes due to trying to load images
            # while a new process is being loaded. I am a little surprised that
            # we get here during that process.
            return

        if self.delete_process_step_ix is not None:
            self.DeleteProcessStep(self.delete_process_step_ix)
        self.delete_process_step_ix = None

        if self.load_process_file_name is not None:
            print("LOAD PROCESS", len(ProcessStep.steps))
            self.LoadProcessFile(self.load_process_file_name)
        self.load_process_file_name = None

        if self.new_step is not None:
            self.new_step.SelectTab(None)
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
                self.pic_needed = False				# don't process others until requested
                new_image = self.local_cam.capture_image()
                iso = self.local_cam.iso
                shutter_speed = self.local_cam.shutter_speed
                colorcode = self.local_cam.colorcode
            elif self.pic_source == SRC_BOT_CAMERA:
                if self.last_pic_payload is not None:
                    self.pic_needed = False			# if single frame mode, mark done
                    payload = self.last_pic_payload			# capture payload because self.last_pic_payload is updated asynchronously
                    self.pic_fn = payload['filename']
                    path = os.path.join(self.downloadDir, self.pic_fn)
                    if not self.file_client.GetFile(self.pic_fn, path=path):
                        print("Unable to fetch PIC", self.pic_fn)
                        return
                    iso = payload['iso']
                    shutter_speed = payload['shutter_speed']
                    print("CAM", iso, shutter_speed)
            if (new_image is not None) or (path is not None):
                # We have a new image. We might not. We don't get a picture if Capture hasn't been
                # clicked or if this loop is running faster than new images are published in
                # continuous SRC_BOT_CAMERA mode.
                print("DoLoop() process image ", path, new_image is not None)
                self.ConfigureImageSource(path=path, new_image=new_image, iso=iso, shutter_speed=shutter_speed, colorcode=colorcode)
        if self.step_execution_needed:
            ProcessStep.ExecuteAllSteps()
            self.step_execution_needed = False
        self.tk.Update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

if __name__ == '__main__':
    m = Darkroom()
    m.Loop()
