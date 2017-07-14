from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import json
import math
import os
import sys
import traceback
from PIL import ImageTk, Image

import threading
import time

import cv2
import numpy as np

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


TEST_FILTER = 'bw'
TEST_FILTER = 'crayola'

# Filter functions should modify only:
#	ProcessStep.annotation_base
#	xstep.im
# GetParm() must filter parameters to avoid code injection attacks
FILTERS = [
		{'Name': 'None',		'Parms': [],
						'Code': None,
						'Flags': []
						},
		{'Name': 'CapturedImage',	'Parms': [],
						'Code': "im.copy()",
						'Flags': ['inex', 'outim', 'isbase']
						},
		{'Name': 'ColorMask',		'Parms': [('threshold', 'i', '50'), ('wthreshold', 'i', '50'), ('colors', 's', 'OpticChiasm.HSV_MASK_WHITE, OpticChiasm.HSV_MASK_RED')],
						'Code': "OpticChiasm.ColorMask(im, colors=[{colors}], threshold={threshold})",
						'Flags': ['inprev', 'outim']
						},
		{'Name': 'FileImage',		'Parms': [('opencvfn', 's', '')],
						'Code': "cv2.imread('{opencvfn}')",
						'Flags': ['outim', 'isbase']
						},
		{'Name': 'Crop',		'Parms': [('x', 'l', 'm-50:m+50', 'w'), ('y', 'l', '-100:', 'h')],
						'Code': "im.copy()[{y}, {x}]",
						'Flags': ['inprev', 'outim', 'isbase']
						},
		{'Name': 'BW',			'Parms': [],
						'Code': 'cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)',
						'Flags': ['inprev', 'outim']
						},
                {'Name': 'Blur',		'Parms': [('ksize', 'p', '3,3')],
						'Code': 'cv2.blur(im, {ksize})',
						'Flags': ['inprev', 'outim']
						},
		{'Name': 'CannyAuto',		'Parms': [('sigma', 'f', '0.33')],
						'Code': 'OpticChiasm.auto_canny(im, {sigma})',
						'Flags': ['inprev', 'outim']
						},
                {'Name': 'ColorBalance',	'Parms': [('pct', 'i', '20')],
						'Code': 'OpticChiasm.simplest_cb(im, {pct})',
						'Flags': ['inprev', 'outim']
						},
		{'Name': 'Contours',		'Parms': [],
						'Code': 'cv2.findContours(im, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)',
						'Flags': ['inprev', 'outcont']
						},
		{'Name': 'HoughLinesP',		'Parms': [('MinLineLength', 'i', '30'), ('MaxLineGap', 'i', 10)],
						'Code':  'cv2.HoughLinesP(im, 1, np.pi/180, 15, minLineLength={MinLineLength}, maxLineGap={MaxLineGap})',
                                                'Flags': ['inprev', 'outlines']
						},
		{'Name': 'Map',			'Parms': [],
						'Code':             'cv2.warpPerspective(im, transform, (int(w*3), int(h*4)))',
						'Flags': ['inprev', 'outim']
						},
		{'Name': 'FL',			'Parms': []
						},
		{'Name': 'Crayola',		'Parms': []
						}
]

class ProcessStep(object):
    app = None
    filter_labels = []
    filter_specs = {}
    for this in FILTERS:
        this_label = this['Name']
        filter_labels.append(this_label)
        filter_specs[this_label] = this
    steps = []
    annotation_base = None
    def __init__(self, cv_filter, **kwargs):
        self.ix = len(self.steps)
        self.im = None
        self.steps.append(self)
        self.cv_filter = ''			# this gets set by NewFilter()
        self.parm_values = kwargs
        self.tabTitle = "Step %d" % (self.ix)
        self.tab = self.app.notebook.AddTab(self.tabTitle)
        self.input_panel = self.tab.AddLabelFrame('Input')
        self.output_panel = self.tab.AddLabelFrame('Output')
        #
        self.filter_selection = self.input_panel.AddListbox('Filters', self.filter_labels, Selection=cv_filter, command=self.NewFilter, rowspan=4)
        self.parmEntries = []
        self.parmEntries.append(self.input_panel.AddEntryField('Parm1', row=self.filter_selection.row, col=NEXT_COL))
        parm_col = self.parmEntries[0].col
        self.parmEntries.append(self.input_panel.AddEntryField('Parm2', col=parm_col))
        self.parmEntries.append(self.input_panel.AddEntryField('Parm3', col=parm_col))
        self.parmEntries.append(self.input_panel.AddEntryField('Parm4', col=parm_col))
        #
        self.image = self.output_panel.AddCanvas()
        self.deposition = self.output_panel.AddLabel(col=2)
        self.thumbnail = self.app.thumbnailFrame.AddLabelImage(thumbnailof=self.image, row=0, col=NEXT_COL)
        self.thumbnail.tkw.bind("<Button-1>", self.SelectTab)
        self.opencv = None			# captured image
        self.colorspace = None
        self.NewFilter()

    def SelectTab(self, event):
        self.app.notebook.tkw.select(self.tab.tkw)

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
        print("NewFilter()", new_filter,  self.cv_filter)
        if new_filter != self.cv_filter:
            self.cv_filter = new_filter
            self.cv_specs = self.filter_specs[self.cv_filter]
            self.parms_specs = self.cv_specs['Parms']
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

    def GetParm(self, d, parm_spec, exec_g):
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
            v1 = exec_g[parm_spec[3]]
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
                e = str(int(s))
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
        flags = self.cv_specs['Flags']
        code = self.cv_specs['Code']
        exec_g = {}
        exec_g['__builtins__'] = __builtins__
        exec_g['cv2'] = cv2
        exec_g['np'] = np
        exec_g['OpticChiasm'] = OpticChiasm
        exec_g['xstep'] = self
        if 'inprev' in flags:
            if self.ix > 0:
                im = self.steps[self.ix - 1].im
            else:
                im = None
        elif 'inex' in flags:
            im = self.opencv
        else:
            im = None
        if im is None:
            exec_g['im'] = None
            exec_g['h'] = 0
            exec_g['w'] = 0
            exec_g['c'] = 0
        else:
            exec_g['im'] = im
            exec_g['h'] = im.shape[0]
            exec_g['w'] = im.shape[1]
            if len(im.shape) > 2:
                exec_g['c'] = im.shape[2]
            else:
                exec_g['c'] = 1
        exec_g['contours'] = None
        w = exec_g['w']
        h = exec_g['h']
        h3 = h * 4
        sq = (w * 0.5) / 2
        pts_src = np.array([(sq, 0), (w-sq, 0), (w, h), (0, h)], dtype="float32")
        pts_dst = np.array([(0,0), (w, 0), (w, h3), (0, h3)], dtype="float32")
        exec_g['transform'] = cv2.getPerspectiveTransform(pts_src, pts_dst)
        if ('incont' in flags) and (self.ix > 0):
            exec_g['contours'] = self.steps[self.ix - 1].contours
            print("GET CONTOURS")
        p = {}
        for this_parm in self.parms_specs:
            self.GetParm(p, this_parm, exec_g)
        trace = None
        self.im = None
        self.contours = None
        self.lines = None
        deposition = ''
        if code is not None:
            if 'outim' in flags:
                e = 'xstep.im = '
            elif 'outcont' in flags:
                e = '(imgxx, xstep.contours, hierarchy) = '
            elif 'outlines' in flags:
                e = 'xstep.lines = '
            else:
                e = ''
            e += self.cv_specs['Code'].format(**p)
            print("EXEC", e, exec_g['w'], exec_g['h'])
            try:
                exec(e, exec_g)
            except:
                print(trace)
                trace = traceback.format_exc()
        if 'outcont' in flags:
            print("SAVE CONTOURS")
            if ProcessStep.annotation_base.im is None:
                self.im = None
            else:
                self.im = ProcessStep.annotation_base.im.copy()
                cv2.drawContours(self.im, self.contours, -1, (0, 0, 255), 1)
        if 'outlines' in flags:
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
        self.image.UpdateImage(opencv=self.im)
        if 'isbase' in flags:
            ProcessStep.annotation_base = self
        return
        if self.cv_filter == 'Crayola':
            self.image.UpdateUpdateImage(opencv=OpticChiasm.CrayolaFilter2(im))
            return
        if self.cv_filter == 'FL':
            self.image.UpdateImage(opencv=self.app.image.FindLines(image=im))
            return
        # This should be filter "None"
        if im is None:
            self.image.UpdateImage()
        else:
            self.image.UpdateImage(opencv=im.copy())
        return



class Darkroom(vnavs_mqtt.mqtt_node):
    __slots__ = ('camera_iso', 'camera_last_filename', 'last_pic_payload', 'camera_shutter_speed', 'file_client', 'image',
				'notebook', 'pic_continuous', 'pic_fn', 'pic_get', 'pic_needed', 'statusFrame', 'thumbnailFrame', 'tk')
    def __init__(self):
        super().__init__(Subscriptions=[vconst.cameraman_pic_ready_topic],
					SingleThreaded=True, BrokerType='F',
					AutomaticallyConnect=False, BlockIfNotConnected=False, SelectTimeoutSecs=0.1,
					Verbose=True)
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
        self.notebook = self.tk.AddNotebook(row=3)
        self.camera_iso = self.statusFrame.AddEntryField('ISO', value=800)
        self.camera_shutter_speed = self.statusFrame.AddEntryField('Shutter Speed', value=10000, row=SAME_ROW, col=NEXT_COL)
        self.camera_last_filename = ''
        self.last_pic_payload = None
        self.pic_needed = False
        self.pic_continuous = True
        self.pic_get = True
        self.pic_fn = None
        if vnavs_mqtt.ARG_IMAGE_GET in self.args:
            self.pic_get = self.args[vnavs_mqtt.ARG_IMAGE_GET]

        self.statusFrame.AddDropDown(s_items=['local', 'bot'], command=self.SelectSource, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Capture', command=self.CaptureImageFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Continuous', command=self.ContinuousImageFile, row=SAME_ROW, col=NEXT_COL)
        self.statusFrame.AddButton('Open File', command=self.ChooseImageFile, row=SAME_ROW, col=NEXT_COL)

        ProcessStep.app = self
        ProcessStep('FileImage', opencvfn=None)
        ProcessStep('ColorBalance')
        ProcessStep('Crop')
        ProcessStep('BW')
        ProcessStep('Blur')
        ProcessStep('CannyAuto')
        ProcessStep('Contours')

    def ChooseImageFile(self):
        fn = self.statusFrame.DoFileNameDialog()
        ProcessStep.steps[0].filter = 'FileImage'
        ProcessStep.steps[0].parm_values['opencvfn'] = fn
        ProcessStep.steps[0].UpdateAll()

    def ContinuousImageFile(self):
        self.pic_continuous = True

    def SelectSource(self, *args):
        print("** SELECT SOURCE **")
        self.ConnectToMqttServer()

    def CaptureImageFile(self):
        self.pic_needed = True
        self.pic_continuous = False
        return
        payload = {}
        try:
            payload['iso'] = int(self.camera_iso.Value())
        except TypeError:
            self.camera_iso.set(100)
        try:
            payload['shutterSpeed'] = int(self.camera_shutter_speed.Value())
        except TypeError:
            self.camera_shutter_speed.set(0)
        payload['loop_mode'] = 'run'
        payload['loop_format'] = 'bgr'
        payload['loop_publish'] = 'stream'
        payload['capture_mode'] = 'single'
        payload['capture_format'] = 'jpeg'
        payload['capture_publish'] = 'file'
        print("SNAP", payload)
        self.Publish(vconst.cameraman_orders_topic, payload)

    def rmsg_cameraman_pic_ready(self, payload):
        # Do as little as possible here in mqtt thread.
        # Process image in tk thread.
        self.last_pic_payload = payload

    def DoLoop(self):
        if (self.pic_continuous or self.pic_needed) and (self.last_pic_payload is not None):
            if self.pic_needed:					# self.pic_needed is freeze frame mode
                self.pic_needed = False				# don't process others until requested
            payload = self.last_pic_payload			# capture payload because self.last_pic_payload is updated asynchronously
            self.pic_fn = payload['filename']
            print("PIC", self.pic_fn)
            path = os.path.join(self.imageDir, self.pic_fn)
            print("ProcessImage()", self.pic_fn, path)
            if self.pic_get:
                if not self.file_client.GetFile(self.pic_fn, path=path):
                    print("Unable to fetch PIC", self.pic_fn)
                    return
            im = cv2.imread(path)
            if im is not None:
                ProcessStep.steps[0].parm_values['opencvfn'] = path
                ProcessStep.steps[0].filter = 'FileImage'
                ProcessStep.steps[0].UpdateAll()
        self.tk.Update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

if __name__ == '__main__':
    m = Darkroom()
    m.Loop()
