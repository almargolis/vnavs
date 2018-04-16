from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

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
from easytk import SAME_ROW, NEXT_ROW, SAME_COL, NEXT_COL, LEFT_COL, RIGHT_COL
import OpticChiasm
import vnavs_mqtt
import vnavs_const as vconst

BOT_1_MAP_TRANSPOSE = [

			[ -1.30565584e-01,  -1.56472861e+00,   4.58333935e+02],
			[ -2.57693172e-15,  -3.10871493e+00,   1.04702945e+03],
			[ -2.95275685e-18,  -3.83178162e-03,   1.00000000e+00]
		]

BOT_1_H = np.array(BOT_1_MAP_TRANSPOSE, dtype="float32")

class FilterParm(object):
    __slots__ = ('caption', 'default', 'name')
    def __init__(self, name, default, click_point=False):
        self.name = name
        self.default = default
        self.click_point = click_point
        if self.click_point:
            self.caption = self.name + ' (PP)'
        else:
            self.caption = self.name

class FilterParmFloat(FilterParm):
    def GetValue(self, raw_value):
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
        return str(float(raw_value))

class FilterParmInt(FilterParm):
    def GetValue(self, raw_value):
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
        return str(int(raw_value))

class FilterParmStr(FilterParm):
    def GetValue(self, raw_value):
        if raw_value is None:
            raw_value = ''
        v = raw_value.strip()
        if '"' in v:
            v = ''
        if "'" in v:
            v = ''
        return v

class FilterParmPoint(FilterParm):
    # This is a numpy / mathematical point

    def GetValue(self, raw_value):
        v = raw_value.split(',')
        x = int(v[0].strip())
        y = int(v[1].strip())
        return "({},{})".format(x, y)

class FilterParmPointSym(FilterParm):
    def __init__(self, name, default, click_point=True):
        super().__init__(name, default, click_point=click_point)

    def GetValue(self, raw_value):
        # The defaults of 'b' and 'e' works well for ranges like CropYX.
        # Not so much for points like CropPP.
        v = raw_value.split(',')
        x = v[0].strip()
        y = v[1].strip()
        if x == '':
            x = 'b'
        if y == '':
            y = 'e'
        return "('{}','{}')".format(x, y)

# Filter functions should modify only:
#	xstep.im
# GetParm() must filter parameters to avoid code injection attacks


SRC_LOCAL_CAMERA = 'local'
SRC_BOT_CAMERA = 'bot'

FILTER_NAME_FILEIMAGE		= 'FileImage'
FILTER_NAME_CAPTUREDIMAGE	= 'CapturedImage'
FILTER_NAME_ANALYZER		= 'Analyzer'
FILTER_NAME_CROPPP		= 'CropPP'

class ImageFilter(object):
    __slots__ = ('annotate_code', 'filter_names', 'filters', 'flags', 'code', 'name', 'parms')
    filters = {}
    filter_names = []

    def __init__(self, name, code, parms, Flags=None):
        self.name = name
        self.code = code
        self.parms = parms		# a list of FilterParm() and descendent objects
        self.flags = Flags		# a list of string flag names
        self.annotate_code = None
        self.filters[name] = self
        self.filter_names.append(name)
        self.filter_names.sort()

#
# Filter code is processed with exec with available globals OpticCiasm, cv2,
#	previous step exec_im and its shape as im, h, w and c,
#	xstep is the current ProcessStep() with exec_im set to None.
#
ImageFilter(FILTER_NAME_CAPTUREDIMAGE,
			'xstep.exec_im = xstep.source_im.copy()',
			[],
			Flags=['isbase'])

ImageFilter('ColorMask',
			'xstep.exec_im = oc.Image(oc.ColorMask(im_in.ImAsHSV(), colors=[{colors}], huerange={huerange}, threshold={threshold}),\n' \
				+ '	colorcode=oc.IM_GRAY)',
                        [FilterParmInt('huerange', '25'), FilterParmInt('threshold', '50'), FilterParmInt('wthreshold', '50'),
                                FilterParmStr('colors', 'oc.HSV_WHITE, oc.HSV_RED')],
                        Flags=[])

ImageFilter(FILTER_NAME_FILEIMAGE,
			"xstep.exec_im = oc.Image(opencv_fn='{opencv_fn}')",
			[FilterParmStr('opencv_fn', '')],
			Flags=['isbase'])


filter = ImageFilter(FILTER_NAME_CROPPP,
			'r = im_in.RectFromSymbolicPP({p1}, {p2})\n'
				+ 'xstep.exec_im = im_in.Crop(r)\n'
				+ 'print(im_in.shape, r)\n',
			[FilterParmPointSym('p1', 'm-50,m+50'), FilterParmPointSym('p2', '-100,e')],
			Flags=['isbase'])
filter.annotate_code = 'xstep.exec_annotated = im_base.copy()\n' \
				+ 'xstep.exec_annotated.DrawRectangle(r, color=oc.DRAW_BGR_GREEN, thickness=2)\n'

filter = ImageFilter('CropYX',
			'r = im_in.RectFromSymbolicYX({y_range}, {x_range})\n'
				+ 'xstep.exec_im = im_in.Crop(r)\n'
				+ 'print(im_in.shape, r)\n',
			[FilterParmPointSym('y_range', '-100,'), FilterParmPointSym('x_range', 'm-50,m+50')], 
			Flags=['isbase'])
filter.annotate_code = 'xstep.exec_annotated = im_base.copy()\n' \
				+ 'xstep.exec_annotated.DrawRectangle(r, color=oc.DRAW_BGR_GREEN, thickness=2)\n'

ImageFilter('Gray',
			'xstep.exec_im = im_in.CopyAsGray()',
			[],
			Flags=[])

ImageFilter('Blur',
			'xstep.exec_im = oc.Image(im=cv2.blur(im_in.im, {ksize}), colorcode=im_in.colorcode)',
			[FilterParmPoint('ksize', '3,3')],
			Flags=[])

ImageFilter('CannyAuto',
			'xstep.exec_im = oc.Image(im=oc.auto_canny(im_in.ImAsGray(), {sigma}), colorcode=oc.IM_GRAY)',
			[FilterParmFloat('sigma', '0.33')],
			Flags=[])

ImageFilter('ColorBalance',
			'xstep.exec_im = oc.simplest_cb(im, {pct})',
			[FilterParmInt('pct', '20')],
			Flags=[])

ImageFilter('Erode',
			'kernel = np.ones(({kernel_dim}, {kernel_dim}), np.uint8)\n'
				+ 'xstep.exec_im = oc.Image(im=cv2.erode(im_in.im, kernel, iterations={iterations}),\n'
				+ '			colorcode=im_in.colorcode)\n',
			[FilterParmInt('kernel_dim', '1'),
				FilterParmInt('iterations', '1')],
			Flags=[])

# findContours modifies the soure image. The image is assumed to be binary, ususally from canny
filter = ImageFilter('FindContours',
			'cont2, xstep.exec_contours, xstep.exec_hierarchy = cv2.findContours(im_in.ImAsGray(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)\n',
			[FilterParmInt('MaxLevel', '-1')],
			Flags=[])
filter.annotate_code = 'xstep.exec_annotated = im_base.CopyAsGray().CopyAsBGR()\n' \
				+ 'oc.CrayolaContours(xstep.exec_annotated.im, xstep.exec_contours, xstep.exec_hierarchy, MaxLevel={MaxLevel})\n' \
				+ 'oc.ContoursToLineVectors(xstep.exec_annotated.im, xstep.exec_contours, xstep.exec_hierarchy)\n'
		#		+ 'cv2.drawContours(xstep.exec_annotated.im, xstep.exec_contours, -1, oc.DRAW_BGR_RED, 1)\n'
		#		+ 'for i in xrange(0, len(xstep.exec_contours)):\n'
		#		+ '    color = (np.random.uniform(0, 255), np.random.uniform(0, 255), np.random.uniform(0, 255))\n'
		#		+ '    cv2.drawContours(xstep.exec_im, xstep.exec_contours, 1, color, 1)\n',

ImageFilter('DrawContours',
			'cv2.drawContours(im, contours, -1, (0, 0, 255))',
			[],
			Flags=['incont'])

ImageFilter('EqualizeHistogram',
			'xstep.exec_im = cv2.equalizeHist(im)',
			[],
			Flags=[])

ImageFilter('HistogramCB',
			'oc.Histogram_CB(im)',
			[],
			Flags=[])

filter = ImageFilter(FILTER_NAME_ANALYZER,
			'r = im_in.RectFromSymbolicPP({p1}, {p2})\n',
			[FilterParmPointSym('p1', 'm-3,m-3'), FilterParmPointSym('p2', 'p+3,p+3')],
			Flags=[])
filter.annotate_code = 'xstep.exec_annotated = im_base.copy()\n' \
				+ 'xstep.exec_annotated.DrawRectangle(r, color=oc.DRAW_BGR_GREEN, thickness=2)\n'

filter = ImageFilter('HoughLinesP',
			'xstep.exec_lines = cv2.HoughLinesP(im_in.im, 1, np.pi/180, 15, minLineLength={MinLineLength}, maxLineGap={MaxLineGap})',
			[FilterParmInt('MinLineLength', '30'), FilterParmInt('MaxLineGap', 10)],
			Flags=[''])
filter.annotate_code = 'xstep.exec_annotated = im_base.copy()\n' \
				+ 'print(xstep.exec_lines)\n' \
				+ 'color_ix = -1\n' \
				+ 'if (xstep.exec_lines is not None) and (len(xstep.exec_lines) > 0):\n' \
				+ '    for line  in xstep.exec_lines:\n' \
				+ '        for x1,y1,x2,y2 in line:\n' \
				+ '            color_ix = oc.NextColorIx(color_ix)\n' \
				+ '            color = oc.DRAW_COLORS[color_ix]\n' \
				+ '            cv2.line(xstep.exec_annotated.im, (x1,y1), (x2,y2), color, 1)\n'

ImageFilter('Map',
			'cv2.warpPerspective(im, transform, (int(w*3), int(h*4)))',
			[],
			Flags=[])

class ProcessStep(object):
    __slots__ = ('cv_filter_name', 'cv_specs',
			'deposition', 
			'exec_annotated', 'exec_contours', 'exec_hierarchy', 'exec_im', 'exec_lines',
			'filter_selection',
			'image_widget', 'info_data', 'info_widgets', 'input_panel', 'ix', 'output_panel', 
			'parm_widgets', 'parm_values', 'parms_specs', 'point_target', 'source_im', 'tab', 'tab_title', 'thumbnail',
			'zoom_popup'
		)
    app = None
    steps = []
    process_file_extension = 'drk'
    process_file_types = (('Darkroom Process', '*.'+process_file_extension), )

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
        self.filter_selection = self.input_panel.AddListbox('Filters', ImageFilter.filter_names, Selection=FilterName, command=self.NewFilter, rowspan=4)
        self.info_data = []
        self.info_widgets = []
        for ix in range(4):
            info_label = self.input_panel.AddLabel('', row=NEXT_ROW, col=LEFT_COL)
            info_value = self.input_panel.AddLabel('', row=SAME_ROW, col=NEXT_COL)
            self.info_widgets.append((info_label, info_value))
        self.parm_widgets = []
        self.parm_widgets.append(self.input_panel.AddEntryField('Parm1', row=self.filter_selection.row, col=NEXT_COL, OnDoubleClick=self.OnPickPoint))
        parm_col = self.parm_widgets[0].col
        self.parm_widgets.append(self.input_panel.AddEntryField('Parm2', col=parm_col, OnDoubleClick=self.OnPickPoint))
        self.parm_widgets.append(self.input_panel.AddEntryField('Parm3', col=parm_col))
        self.parm_widgets.append(self.input_panel.AddEntryField('Parm4', col=parm_col))
        self.input_panel.AddButton('Update', command=self.OnUpdateStep, col=parm_col)
        self.input_panel.AddButton('Delete Step', command=self.OnDeleteStep, row=SAME_ROW, col=NEXT_COL)
        #
        # output_panel
        #
        self.image_widget = self.output_panel.AddCanvas(OnClick=self.OnImageClick)
        self.deposition = self.output_panel.AddLabel(row=0, col=2)
        self.thumbnail = self.app.thumbnailFrame.AddLabelImage(thumbnailof=self.image_widget, row=0, col=NEXT_COL)
        self.thumbnail.tkw.bind("<Button-1>", self.SelectTab)
        self.source_im = None			# captured image
        self.point_target = None
        self.SetFilter()

    def ClearInfo(self):
        self.info_data = []

    def AddInfo(self, label, value):
        self.info_data.append((label, value))

    def OnPickPoint(self, event):
        # This configures OnImageClick() to save the clicked point in a parm.
        # event.widget is the tkw object. We could use that to use this
        # method for multiple points.
        self.point_target = None
        for ix, this in enumerate(self.parm_widgets):
            if this.tkw == event.widget:
                # this is the tkeasy widget that was double-clicked
                if self.parms_specs[ix].click_point:
                    # the parm_spec indicates the paramter is a point in the image
                    # that can be slected by clicking on the image.
                    self.point_target = this
        if self.point_target is not None:
            self.point_target.ReplaceValue('<click image>')

    def OnUpdateStep(self):
        # Click this to refresh after changing a parameter. We don't automatically do
        # that in case intermediate updates might fail when make several changes.
        self.SetFilter()			# This saves the parameter values
        self.UpdateAll()			# this processes all steps

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
    def UpdateAll(cls):
        for this_step in cls.steps:
            this_step.Update()

    def SaveParameters(self):
        for ix, this_widget in enumerate(self.parm_widgets):
            if this_widget.parm_id is not None:
                # save prior value
                self.parm_values[this_widget.parm_id] = this_widget.Value()

    def NewFilter(self, *args):
        # TK callbacks seem to incude *args
        self.SetFilter()
        self.UpdateAll()

    def SetFilter(self, FilterName=None, NewParms=None):
        self.SaveParameters()
        if NewParms is not None:
            for key, value in NewParms.items():
                self.parm_values[key] = value
        if FilterName is None:
            new_filter_name = self.filter_selection.Value()
        else:
            new_filter_name = FilterName
        #print("SetFilter()", new_filter_name,  self.cv_filter_name)
        if new_filter_name != self.cv_filter_name:
            self.filter_selection.ReplaceValue(new_filter_name)
            self.cv_filter_name = new_filter_name
            self.cv_specs = ImageFilter.filters[self.cv_filter_name]
            self.parms_specs = self.cv_specs.parms
            for ix, this_widget in enumerate(self.parm_widgets):
                if ix < len(self.parms_specs):
                    parm_name = self.cv_filter_name + '_' + self.parms_specs[ix].name
                    parm_caption = self.parms_specs[ix].caption
                    parm_default_value = self.parms_specs[ix].default
                    if parm_name not in self.parm_values:
                        self.parm_values[parm_name] = parm_default_value
                    parm_value = self.parm_values[parm_name]
                else:
                    parm_name = None
                    parm_caption = "Parm" + str(ix+1)
                    parm_value = ""
                this_widget.ReplaceValue(parm_value, Caption=parm_caption)
                this_widget.parm_id = parm_name

    def Update(self):
        exec_global_vars = {}
        exec_global_vars['__builtins__'] = __builtins__
        exec_global_vars['cv2'] = cv2
        exec_global_vars['np'] = np
        exec_global_vars['oc'] = OpticChiasm
        exec_global_vars['xstep'] = self
        #
        base_image = None
        for ix, this in enumerate(self.steps):
            if ix >= self.ix:
                break
            if this.exec_im is not None:
                exec_global_vars['im_in'] = this.exec_im
                if 'isbase' in this.cv_specs.flags:
                    exec_global_vars['im_base'] = this.exec_im
                    base_image = this.exec_im
            if this.exec_contours is not None:
                exec_global_vars['contours_in'] = this.exec_contours
            if this.exec_hierarchy is not None:
                exec_global_vars['hierarchy_in'] = this.exec_hierarchy

        for ix, this in enumerate(self.info_widgets):
            if ix < len(self.info_data):
                this[0].ReplaceValue(self.info_data[ix][0])
                this[1].ReplaceValue(self.info_data[ix][1])
            else:
                this[0].ReplaceValue('')
                this[1].ReplaceValue('')

        code_substitutions = {}
        for this_parm in self.parms_specs:
            raw_value = self.parm_values[self.cv_filter_name + '_' + this_parm.name]
            code_substitutions[this_parm.name] = this_parm.GetValue(raw_value)
        trace = None
        self.exec_im = None
        self.exec_contours = None
        self.exec_hierarchy = None
        self.exec_lines = None
        self.exec_annotated = None
        deposition = ''
        self.deposition.ReplaceValue(deposition)
        code = self.cv_specs.code
        if self.cv_specs.annotate_code is not None:
            code += '\n' + self.cv_specs.annotate_code
        if code != '':
            exec_code_str = code.format(**code_substitutions)
            print("EXEC", exec_code_str)
            try:
                exec(exec_code_str, exec_global_vars)
            except:
                trace = traceback.format_exc()
                print(trace)
        if self.cv_specs.annotate_code is None:
            if self.exec_im is None:
                self.exec_annotated = base_image
            else:
                self.exec_annotated = self.exec_im.copy()
        if trace is not None:
            deposition = trace + "\n\n" + deposition
            self.deposition.ReplaceValue(deposition)
        self.image_widget.UpdateImage(source_im=self.exec_annotated)
        return


class Darkroom(vnavs_mqtt.mqtt_node):
    __slots__ = (
				'camera_iso', 'camera_last_filename', 'camera_shutter_speed',
				'delete_process_step_ix', 'downloadDir', 'file_client', 'image',
				'last_pic_payload', 'load_filter_name', 'load_new_filter_ct', 'load_parms', 'load_process_file_name',
				'loading', 'local_cam',
				'new_step', 'notebook', 'notebook_add_id',
				'pic_continuous', 'pic_fn', 'pic_get', 'pic_needed', 'pic_source',
				'scriptsDir', 'source_widget', 'statusFrame', 'thumbnailFrame', 'tk'
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
        self.pic_get = True
        self.pic_fn = None
        self.pic_source = None
        if vnavs_mqtt.ARG_IMAGE_GET in self.args:
            self.pic_get = self.args[vnavs_mqtt.ARG_IMAGE_GET]

        self.source_widget = self.statusFrame.AddDropDown(s_items=[SRC_LOCAL_CAMERA, SRC_BOT_CAMERA], command=self.OnSelectSource, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Capture', command=self.OnCaptureImage, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Continuous', command=self.OnContinuousImage, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Open File', command=self.OnOpenImageFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Open Process', command=self.OpenProcessFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Save Process', command=self.SaveProcessFile, row=SAME_ROW, col=NEXT_COL)

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

    def ConfigureImageSource(self, new_filter_name, path=None, new_image=None, iso=None, shutter_speed=None):
        new_parms = {}
        new_parms['opencv_fn'] = path
        if len(ProcessStep.steps) == 0:
            ProcessStep(new_filter_name, Parms=new_parms, Where=self.notebook_add_id)
        else:
            ProcessStep.steps[0].SetFilter(FilterName=new_filter_name, NewParms=new_parms)
        ProcessStep.steps[0].source_im = new_image
        ProcessStep.steps[0].ClearInfo()
        if iso is not None:
            ProcessStep.steps[0].AddInfo('ISO', iso)
        if shutter_speed is not None:
            ProcessStep.steps[0].AddInfo('Shutter', shutter_speed)
        ProcessStep.steps[0].UpdateAll()

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
        self.source_widget.ReplaceValue(SRC_LOCAL_CAMERA)	# temporary - needs more optrions
        ProcessStep.UpdateAll()
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
        self.ConfigureCamera()					# we don't wait for this to take effect
        self.pic_needed = True
        self.pic_continuous = False
        if self.source_widget.Value() is None:
            print("On Capture update source")
            self.source_widget.ReplaceValue(SRC_LOCAL_CAMERA)
        self.ConfigureImageSource(FILTER_NAME_CAPTUREDIMAGE)
        print("SOURCE", self.source_widget.Value())
        print("FILTER", ProcessStep.steps[0].filter_selection.Value())

    def OnContinuousImage(self):
        self.ConfigureCamera()					# we don't wait for this to take effect
        self.pic_continuous = True
        if self.source_widget.Value() is None:
            self.source_widget.ReplaceValue(SRC_LOCAL_CAMERA)
        self.ConfigureImageSource(FILTER_NAME_CAPTUREDIMAGE)

    def OnOpenImageFile(self):
        self.pic_continuous = False
        self.pic_needed = False
        fn = self.statusFrame.DoFileNameDialog()
        self.ConfigureImageSource(FILTER_NAME_FILEIMAGE, path=fn)

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
        self.last_pic_payload = payload

    def DeleteProcessStep(self, ix):
        self.notebook.DeleteTab(ix)
        ProcessStep.steps.pop(ix)
        for adjust_ix, this_step in enumerate(ProcessStep.steps[ix:]):
            this_step.ix = ix + adjust_ix
            this_step.tab_title = "Step %d" % (this_step.ix)
            self.notebook.tkw.tab(ix, text=this_step.tab_title)
        ProcessStep.steps[ix-1].SelectTab(None)

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
        new_image = None
        path = None
        iso = None
        shutter_speed = None
        if self.pic_continuous or self.pic_needed:
            if self.pic_source == SRC_LOCAL_CAMERA:
                self.pic_needed = False				# don't process others until requested
                new_image = self.local_cam.capture_image()
                iso = self.local_cam.iso
                shutter_speed = self.local_cam.shutter_speed
            elif self.pic_source == SRC_BOT_CAMERA:
                if self.last_pic_payload is not None:
                    self.pic_needed = False			# if single frame mode, mark done
                    payload = self.last_pic_payload			# capture payload because self.last_pic_payload is updated asynchronously
                    self.pic_fn = payload['filename']
                    #print("ProcessImage()", self.pic_fn, path)
                    if self.pic_get:
                        path = os.path.join(self.downloadDir, self.pic_fn)
                        if not self.file_client.GetFile(self.pic_fn, path=path):
                            print("Unable to fetch PIC", self.pic_fn)
                            return
                    else:
                        path = os.path.join(self.imageDir, self.pic_fn)
                    iso = payload['iso']
                    shutter_speed = payload['shutter_speed']
                    print("CAM", iso, shutter_speed)
            if (new_image is not None) or (path is not None):
                new_parms = {}
                if path is None:
                    self.ConfigureImageSource(FILTER_NAME_CAPTUREDIMAGE, path=path, new_image=new_image, iso=iso, shutter_speed=shutter_speed)
                else:
                    self.ConfigureImageSource(FILTER_NAME_FILEIMAGE, path=path, new_image=new_image, iso=iso, shutter_speed=shutter_speed)
        self.tk.Update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

if __name__ == '__main__':
    m = Darkroom()
    m.Loop()
