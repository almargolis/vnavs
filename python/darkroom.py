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
from easytk import SAME_ROW, NEXT_ROW, NEXT_COL
import OpticChiasm
import vnavs_mqtt
import vnavs_const as vconst

BOT_1_MAP_TRANSPOSE = [

			[ -1.30565584e-01,  -1.56472861e+00,   4.58333935e+02],
			[ -2.57693172e-15,  -3.10871493e+00,   1.04702945e+03],
			[ -2.95275685e-18,  -3.83178162e-03,   1.00000000e+00]
		]

BOT_1_H = np.array(BOT_1_MAP_TRANSPOSE, dtype="float32")


# Filter functions should modify only:
#	ProcessStep.annotation_base
#	xstep.im
# GetParm() must filter parameters to avoid code injection attacks

class ImageFilter(object):
    filters = {}
    filter_names = []

    def __init__(self, name, code, parms, Flags=None):
        self.name = name
        self.code = code
        self.parms = parms
        self.flags = Flags
        self.filters[name] = self
        self.filter_names.append(name)
        self.filter_names.sort()

#
# Filter code is processed with exec with available globals OpticCiasm, cv2,
#	previous step exec_im and its shape as im, h, w and c,
#	xstep is the current ProcessStep() with exec_im set to None.
#
ImageFilter('CapturedImage',
			'xstep.exec_im = xstep.opencv_im.copy()',
			[],
			Flags=['isbase'])

ImageFilter('ColorMask',
			'xstep.exec_im = OpticChiasm.ColorMask(im, colors=[{colors}], threshold={threshold})',
                        [('threshold', 'i', '50'), ('wthreshold', 'i', '50'),
                                ('colors', 's', 'OpticChiasm.HSV_MASK_WHITE, OpticChiasm.HSV_MASK_RED')],
                        Flags=[])

ImageFilter('FileImage',
			"xstep.exec_im = cv2.imread('{opencv_fn}')",
			[('opencv_fn', 's', '')],
			Flags=['isbase'])

ImageFilter('Crop',
			"xstep.exec_im = im.copy()[{y}, {x}]",
			[('x', 'l', 'm-50:m+50', 'w'), ('y', 'l', '-100:', 'h')],
			Flags=['isbase'])

ImageFilter('BW',
			'xstep.exec_im = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)',
			[],
			Flags=[])

ImageFilter('Blur',
			'xstep.exec_im = cv2.blur(im, {ksize})',
			[('ksize', 'p', '3,3')],
			Flags=[])

ImageFilter('CannyAuto',
			'xstep.exec_im = OpticChiasm.auto_canny(im, {sigma})',
			[('sigma', 'f', '0.33')],
			Flags=[])

ImageFilter('ColorBalance',
			'xstep.exec_im = OpticChiasm.simplest_cb(im, {pct})',
			[('pct', 'i', '20')],
			Flags=[])

# findContours modifies the soure image. The image is assumed to be binary, ususally from canny
ImageFilter('FindContours',
			'cont2, xstep.exec_contours, hierarchy = cv2.findContours(im.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)\n'
				+ 'xstep.exec_im = xstep.annotation_base.exec_im.copy()\n'
		#		+ 'for i in xrange(0, len(xstep.exec_contours)):\n'
		#		+ '    color = (np.random.uniform(0, 255), np.random.uniform(0, 255), np.random.uniform(0, 255))\n'
		#		+ '    cv2.drawContours(xstep.exec_im, xstep.exec_contours, 1, color, 1)\n',
				+ 'cv2.drawContours(xstep.exec_im, xstep.exec_contours, -1, (255, 0, 0), 1)\n',
			[],
			Flags=[])

ImageFilter('DrawContours',
			'cv2.drawContours(im, contours, -1, (0, 0, 255))',
			[],
			Flags=['incont'])

ImageFilter('EqualizeHistogram',
			'cv2.equalizeHist(im)',
			[],
			Flags=[])

ImageFilter('HistogramCB',
			'OpticChiasm.Histogram_CB(im)',
			[],
			Flags=[])

ImageFilter('HoughLinesP',
			'cv2.HoughLinesP(im, 1, np.pi/180, 15, minLineLength={MinLineLength}, maxLineGap={MaxLineGap})',
			[('MinLineLength', 'i', '30'), ('MaxLineGap', 'i', 10)],
			Flags=['outlines'])

ImageFilter('Map',
			'cv2.warpPerspective(im, transform, (int(w*3), int(h*4)))',
			[],
			Flags=[])

class ProcessStep(object):
    __slots__ = ('annotation_base', 'app', 'cv_filter',
			'exec_contours', 'exec_im', 'exec_lines',
			'deposition', 
			'image_widget', 'input_panel', 'ix', 'opencv_im', 'output_panel', 
			'parm_entries', 'parm_values', 'steps', 'tab', 'tab_title', 'thumbnail'
		)
    app = None
    steps = []
    annotation_base = None

    def __init__(self, FilterName=None, Where=None, **kwargs):
        self.ix = len(self.steps)
        self.exec_im = None
        self.steps.append(self)
        self.cv_filter = None			# this gets set by NewFilter()
        self.parm_values = kwargs
        self.tab_title = "Step %d" % (self.ix)
        self.tab = self.app.notebook.AddTab(self.tab_title, Where=Where)
        self.input_panel = self.tab.AddLabelFrame('Input')
        self.output_panel = self.tab.AddLabelFrame('Output')
        #
        self.filter_selection = self.input_panel.AddListbox('Filters', ImageFilter.filter_names, Selection=FilterName, command=self.NewFilter, rowspan=4)
        self.parmEntries = []
        self.parmEntries.append(self.input_panel.AddEntryField('Parm1', row=self.filter_selection.row, col=NEXT_COL))
        parm_col = self.parmEntries[0].col
        self.parmEntries.append(self.input_panel.AddEntryField('Parm2', col=parm_col))
        self.parmEntries.append(self.input_panel.AddEntryField('Parm3', col=parm_col))
        self.parmEntries.append(self.input_panel.AddEntryField('Parm4', col=parm_col))
        self.input_panel.AddButton('Delete Step', command=self.OnDeleteStep, col=parm_col)
        #
        self.image_widget = self.output_panel.AddCanvas(OnClick=self.ZoomPopup)
        self.deposition = self.output_panel.AddLabel(col=2)
        self.thumbnail = self.app.thumbnailFrame.AddLabelImage(thumbnailof=self.image_widget, row=0, col=NEXT_COL)
        self.thumbnail.tkw.bind("<Button-1>", self.SelectTab)
        self.opencv_im = None			# captured image
        self.NewFilter()

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

    def ZoomPopup(self, event):
        print("ZoomPopup()")
        cv2.imwrite('zoom.jpeg', self.exec_im)
        top = self.app.tk.MakePopupWindow(self.cv_filter)
        top.AddLabel("Sum Thing")
        canvas = top.AddCanvas(width=800, height=400)
        canvas.UpdateImage(opencv_fn='zoom.jpeg')

    def UpdateAll(self):
        for this_step in self.steps:
            this_step.Update()

    def SaveParameters(self):
        for ix, this_entry in enumerate(self.parmEntries):
            if this_entry.parm_id is not None:
                # save prior value
                self.parm_values[this_entry.parm_id] = this_entry.Value()

    def NewFilter(self, *args):
        # TK callbacks seem to incude *args
        self.SaveParameters()
        new_filter = self.filter_selection.Value()
        #print("NewFilter()", new_filter,  self.cv_filter)
        if new_filter != self.cv_filter:
            self.cv_filter = new_filter
            self.cv_specs = ImageFilter.filters[self.cv_filter]
            self.parms_specs = self.cv_specs.parms
            for ix, this_entry in enumerate(self.parmEntries):
                if ix < len(self.parms_specs):
                    parm_label = self.parms_specs[ix][0]
                    parm_type = self.parms_specs[ix][1]
                    parm_default = self.parms_specs[ix][2]
                    if parm_label not in self.parm_values:
                        self.parm_values[parm_label] = parm_default
                    parm_value = self.parm_values[parm_label]
                    parm_id = parm_label
                else:
                    parm_label = "Parm" + str(ix+1)
                    parm_value = ""
                    parm_id = None
                this_entry.ReplaceValue(parm_value, Caption=parm_label)
                this_entry.parm_id = parm_label
        self.UpdateAll()

    def GetParm(self, d, parm_spec, exec_global_vars):
        # All parameters are returned as strings which are put in a string.format()
        # dictionary. Whenever appropriate, the incoming strings are evaluated
        # via int(), float(), etc as a means to validate data types. This is
        # both to help assure correct operation and to avoid code insertion attacks.
        #
        # Tkinter sometimes converts types so its not safe to make assumptions
        # about the class of raw_value
        #
        parm_name = parm_spec[0]
        parm_type = parm_spec[1]
        if len(parm_spec) >= 4:
            v1 = exec_global_vars[parm_spec[3]]
        else:
            v1 = None
        raw_value = self.parm_values[parm_name]
        if parm_type == 'i':
            # integer number
            if isinstance(raw_value, basestring):
                raw_value = raw_value.strip()
            d[parm_name] = str(int(raw_value))
            return
        if parm_type == 'f':
            # floating point number
            if isinstance(raw_value, basestring):
                raw_value = raw_value.strip()
            d[parm_name] = str(float(raw_value))
            return
        if parm_type == 'l':
            # this is a np slice s:e
            v = raw_value.split(':')
            s = v[0].strip()
            if s == '':
                s = 0
            elif s[0] == 'm':
                adj = int(s[1:])
                s = str(int(v1 / 2) + adj)
            else:
                s = int(s)
                if s < 0:
                    s = v1 + s
            if len(v) > 1:
                e = v[1].strip()
            else:
                e = ''
            if e == '':
                e = v1
            elif e[0] == 'm':
                adj = int(e[1:])
                e = str(int(v1 / 2) + adj)
            else:
                e = int(e)
                if e < 0:
                    e = v1 + e
            d[parm_name] = "%s:%s" % (s, e)
            return
        if parm_type == 'p':
            # this is a point (x,y)
            v = raw_value.split(',')
            x = int(v[0].strip())
            y = int(v[1].strip())
            d[parm_name] = "(%d,%d)" % (x, y)
            return
        if parm_type == 's':
            # this is a string
            if raw_value is None:
                raw_value = ''
            v = raw_value.strip()
            if '"' in v:
                v = ''
            if "'" in v:
                v = ''
            d[parm_name] = v
            return

    def Update(self):
        flags = self.cv_specs.flags
        code = self.cv_specs.code
        if code == '':
            code = None
        exec_global_vars = {}
        exec_global_vars['__builtins__'] = __builtins__
        exec_global_vars['cv2'] = cv2
        exec_global_vars['np'] = np
        exec_global_vars['OpticChiasm'] = OpticChiasm
        exec_global_vars['xstep'] = self
        #
        input_image = None
        if self.ix > 0:
            # input image is output image of previous step 
            input_image = self.steps[self.ix - 1].exec_im
        else:
            input_image = None
        if input_image is None:
            exec_global_vars['im'] = None
            exec_global_vars['h'] = 0
            exec_global_vars['w'] = 0
            exec_global_vars['c'] = 0
        else:
            exec_global_vars['im'] = input_image
            exec_global_vars['h'] = input_image.shape[0]
            exec_global_vars['w'] = input_image.shape[1]
            if len(input_image.shape) > 2:
                exec_global_vars['c'] = input_image.shape[2]
            else:
                exec_global_vars['c'] = 1
        exec_global_vars['contours'] = None
        w = exec_global_vars['w']
        h = exec_global_vars['h']
        h3 = h * 4
        sq = (w * 0.5) / 2
        pts_src = np.array([(sq, 0), (w-sq, 0), (w, h), (0, h)], dtype="float32")
        pts_dst = np.array([(0,0), (w, 0), (w, h3), (0, h3)], dtype="float32")
        exec_global_vars['transform'] = cv2.getPerspectiveTransform(pts_src, pts_dst)
        if ('incont' in flags) and (self.ix > 0):
            exec_global_vars['contours'] = self.steps[self.ix - 1].contours
            print("GET CONTOURS")
        code_substitutions = {}
        for this_parm in self.parms_specs:
            self.GetParm(code_substitutions, this_parm, exec_global_vars)
        trace = None
        self.exec_im = None
        self.exec_contours = None
        self.exec_lines = None
        deposition = ''
        self.deposition.ReplaceValue(deposition)
        if code is not None:
            exec_code_str = code.format(**code_substitutions)
            #print("EXEC", exec_code_str, exec_global_vars['w'], exec_global_vars['h'])
            try:
                exec(exec_code_str, exec_global_vars)
            except:
                print(trace)
                trace = traceback.format_exc()
        if 'outlines' in flags:
            # **** This should be moved to code of filter if needed at all
            print("CONTOURS")
            self.im = ProcessStep.annotation_base.im.copy()
            deposition += "Lines\n"
            map_lines = []
            h, w, c = self.im.shape
            m = int(w/2)
            if self.lines is not None:
                for x in range(0, len(self.lines)):
                    for x1,y1,x2,y2 in self.lines[x]:
                        cv2.line(self.im,(x1,y1),(x2,y2),(0,255,0),2)
                        deposition += "%d. (%d,%d) (%d,%d)\n" % (x, x1, y1, x2, y2)
                        mx1 = x1 - m
                        mx2 = x2 - m
                        my1 = h - y1
                        my2 = h - y2
                        mrise = my2 - my1
                        mrun = mx2 - mx1
                        mslope = mrise / mrun
                        mlen = math.sqrt((mrise ** 2) + (mrun ** 2))
                        p1dist = math.sqrt((mx1 ** 2) + (my1 ** 2))
                        p2dist = math.sqrt((mx2 ** 2) + (my2 ** 2))
                        mdist = min(p1dist, p2dist)
                        map_lines.append((mdist, mlen, mslope, (mx1, my1), (mx2, my2), (x1, y1), (x2, y2)))
            deposition += "** Lines\n"
            map_lines.sort()
            cum_slope = 0
            ct_slope = 0
            print("MAP", h, m, w)
            for this in map_lines[:5]:
                cv2.line(self.im,this[5],this[6],(0,0,255),3)
                print(this)
                ct_slope += 1
                cum_slope += this[2]
            if ct_slope > 0:
                avg_slope = cum_slope / ct_slope
            else:
                avg_slope = "NO :ONES"
            print("MAP", avg_slope)
            deposition += `map_lines`
            self.deposition.ReplaceValue(deposition[:20])
        if trace is not None:
            deposition = trace + "\n\n" + deposition
            self.deposition.ReplaceValue(deposition)
        self.image_widget.UpdateImage(opencv_im=self.exec_im)
        if 'isbase' in flags:
            ProcessStep.annotation_base = self
        return



class Darkroom(vnavs_mqtt.mqtt_node):
    __slots__ = ('camera_iso', 'camera_last_filename', 'delete_process_step_ix', 'last_pic_payload', 'camera_shutter_speed', 'file_client', 'image',
				'notebook', 'pic_continuous', 'pic_fn', 'pic_get', 'pic_needed', 'statusFrame', 'thumbnailFrame', 'tk')
    def __init__(self):
        super().__init__(Subscriptions=[vconst.cameraman_pic_ready_topic],
					SingleThreaded=True, BrokerType='F',
					AutomaticallyConnect=False, BlockIfNotConnected=False, SelectTimeoutSecs=0.1,
					Verbose=False)
        self.delete_process_step_ix = None
        self.file_client = vnavs_mqtt.FileClient(Verbose=False)
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
        self.notebook = self.tk.AddNotebook(row=3, OnTabSelected=self.TabSelected)
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

        self.source_widget = self.statusFrame.AddDropDown(s_items=['local', 'bot'], command=self.SelectSource, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Capture', command=self.CaptureImageFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Continuous', command=self.ContinuousImageFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Open File', command=self.OpenImageFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Open Process', command=self.OpenProcessFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Save Process', command=self.SaveProcessFile, row=SAME_ROW, col=NEXT_COL)

        ProcessStep.app = self
        ProcessStep('FileImage', opencv_fn=None)
        self.new_step = None
        plus = self.notebook.AddTab('+')
        self.notebook_add_id = self.notebook.tkw.tabs()[-1]
        #ProcessStep('ColorBalance')
        #ProcessStep('Crop')
        #ProcessStep('BW')
        #ProcessStep('Blur')
        #ProcessStep('CannyAuto')
        #ProcessStep('Contours')

    def OpenImageFile(self):
        fn = self.statusFrame.DoFileNameDialog()
        ProcessStep.steps[0].filter = 'FileImage'
        ProcessStep.steps[0].parm_values['opencv_fn'] = fn
        ProcessStep.steps[0].UpdateAll()

    def OpenProcessFile(self):
        fn = self.statusFrame.DoFileNameDialog()

    def SaveProcessFile(self):
        f = open('test.dkm', 'w')
        for this_step in ProcessStep.steps:
            f.write(u'/Step\n')
            f.write(u'cv_filter={}\n'.format(this_step.cv_filter))
            for this_key, this_value in this_step.parm_values.items():
                f.write(u'parm.{}={}\n'.format(this_key, this_value))
        f.close()

    def ContinuousImageFile(self):
        self.pic_continuous = True

    def SelectSource(self, *args):
        self.pic_source = self.source_widget.Value()
        if self.pic_source == 'local':
            self.local_cam = cameraman.macbook_camera()
        elif self.pic_source == 'bot':
            self.ConnectToMqttServer()

    def TabSelected(self, x):
        tabid = self.notebook.tkw.select()
        if tabid == self.notebook_add_id:
            # We want the new tab to be selected but TK ignores select() here,
            # because this is an on_select() callback. To get around this,
            # we set self.new_step and make the selection within update loop.
            self.new_step = ProcessStep(Where=tabid)

    def CaptureImageFile(self):
        self.pic_needed = True
        self.pic_continuous = False
        return

    def rmsg_cameraman_pic_ready(self, payload):
        # Do as little as possible here in mqtt thread.
        # Process image in tk thread.
        self.last_pic_payload = payload

    def DeleteProcessStep(self, ix):
        self.notebook.DeleteTab(ix)
        ProcessStep.steps.pop(ix)
        for adjust_ix, this_step in enumerate(ProcessStep.steps[ix:]):
            this_step.ix = ix + adjust_ix
            this_step.tab_title = "StepX %d" % (this_step.ix)
            self.notebook.tkw.tab(ix, text=this_step.tab_title)

    def DoLoop(self):
        if self.delete_process_step_ix is not None:
            self.DeleteProcessStep(self.delete_process_step_ix)
        self.delete_process_step_ix = None

        if self.new_step is not None:
            self.new_step.SelectTab(None)
            self.new_step = None
        new_image = None
        path = None
        if self.pic_continuous or self.pic_needed:
            if self.pic_source == 'local':
                self.pic_needed = False				# don't process others until requested
                new_image = self.local_cam.capture_opencv()
            elif self.pic_source == 'bot':
                if self.last_pic_payload is not None:
                    self.pic_needed = False			# if single frame mode, mark done
                    payload = self.last_pic_payload			# capture payload because self.last_pic_payload is updated asynchronously
                    self.pic_fn = payload['filename']
                    path = os.path.join(self.imageDir, self.pic_fn)
                    #print("ProcessImage()", self.pic_fn, path)
                    if self.pic_get:
                        if not self.file_client.GetFile(self.pic_fn, path=path):
                            print("Unable to fetch PIC", self.pic_fn)
                            return
                    new_image = cv2.imread(path)
            if new_image is not None:
                ProcessStep.steps[0].opencv_im = new_image
                ProcessStep.steps[0].parm_values['opencv_fn'] = path
                if path is None:
                    ProcessStep.steps[0].filter_selection.ReplaceValue('CapturedImage')
                else:
                    ProcessStep.steps[0].filter_selection.ReplaceValue('FileImage')
                ProcessStep.steps[0].NewFilter()
        self.tk.Update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

if __name__ == '__main__':
    m = Darkroom()
    m.Loop()
