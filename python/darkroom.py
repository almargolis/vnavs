from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)
from tkinter import *		# python 3
from tkinter import ttk	# python 3
import tkFileDialog
#from Tkinter import *		# python 2.7
#import ttk			# python 2.7

import base64
import json
import math
import os
import pickle
import sys
import traceback
from PIL import ImageTk, Image

import threading
import time

import cv2
import numpy as np

import OpticChiasm
import vnavs_mqtt

bot_path = "/Volumes/pi/projects/vnavs"

BOT_1_MAP_TRANSPOSE = [

			[ -1.30565584e-01,  -1.56472861e+00,   4.58333935e+02],
			[ -2.57693172e-15,  -3.10871493e+00,   1.04702945e+03],
			[ -2.95275685e-18,  -3.83178162e-03,   1.00000000e+00]
		]

BOT_1_H = np.array(BOT_1_MAP_TRANSPOSE, dtype="float32")

class TkWidgetDef(object):
    root = None
    defaultDir = '.'

    def __init__(self, wname, tkw, Data=None, tkw_label=None, parm_id=None):
        self.wname = wname		# reference name for this widget
        self.tkw = tkw			# tk widget
        self.tkw_label = tkw_label	# tk widget of associated label
        self.tkd = Data			# the tk data (usually StringVar) for this widget
        self.opencv_im = None
        self.row = None			# row where positioned
        self.col = None			# col where positioned (left side)
        self.right_col = None		# furthest right colum used
        self.last_row = 0		# not necesarilly, highest used. for sequential positioning
        self.last_col = 0		# not necesarilly highest used. for sequential positioning
        self.row_ct = 0			# height of this TkWidgetDef object (# of rows)
        self.col_ct = 0			# width of this TkWidgetDef object (# of columns)
        self.thumbnail = None		# update this thumbnail if image is changed
        self.thumbnailwidth = 0		# width of thumbnail
        self.children = []
        self.parm_id = parm_id		# associated application field, not directly used for TK stuff
        if self.root is None:
            self.root = self

        self.file_opt = options = {}
        options['defaultextension'] = '.txt'
        #specifying file types on OSX seems limit what can be selected
        # osx doesn't have an option to select the file categories
        #options['filetypes'] = [('all files', '.*'), ('text files', '.txt')]
        options['initialdir'] = 'C:\\'
        options['initialfile'] = 'myfile.txt'
        options['title'] = 'This is a title'

    def DoFileNameDialog(self):
        self.file_opt['parent'] = self.tkw
        return tkFileDialog.askopenfilename(**self.file_opt)

    def DoFileOpenDialog(self):
        return tkFileDialog.askopenfile(mode='r', **self.file_opt)

    def AddButton(self, caption, command, row=-2, col=-2):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Button(self.tkw, text=caption, command=command))
        frame.tkw.grid(row=row, column=col)
        self.RememberPosition(frame, row, col, 1)
        self.children.append(frame)
        return frame

    def AddEntryField(self, caption, Width=10, Value='', row=-2, col=-2):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')

        tk_data = StringVar()
        tk_data.set(Value)
        tk_label = ttk.Label(self.tkw, text=caption)
        tk_label.grid(column=col, row=row, sticky=W)
        tk_entry = ttk.Entry(self.tkw, width=Width, textvariable=tk_data)
        tk_entry.grid(column=col+1, row=row, sticky=(W, E))
        frame = TkWidgetDef(refname, tk_entry, tkw_label=tk_label, Data=tk_data)
        self.RememberPosition(frame, row, col, 2)
        self.children.append(frame)
        return frame

    def UpdateEntryField(self, Value='', Caption=None):
        self.tkd.set(Value)
        if Caption is not None:
            self.tkw_label.config(text=Caption)

    def AddLabel(self, text='', Width=10, Value='', row=-2, col=-2):
        refname = 'X'
        row, col = self.Position(row=row, col=col)
        tk_label = ttk.Label(self.tkw, text=text)
        tk_label.grid(column=col, row=row, sticky=W)
        frame = TkWidgetDef(refname, tk_label)
        self.RememberPosition(frame, row, col, 1)
        self.children.append(frame)
        return frame

    def UpdateLabel(self, text):
        self.tkw.config(text=text)

    def AddListbox(self, caption, s_items, Selection=None, row=-2, col=-2, height=5, rowspan=0, Command=None):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')

        tk_data = StringVar()
        tk_data.set('')
        tk_label = ttk.Label(self.tkw, text=caption).grid(column=0, row=self.last_row, sticky=W)
        scrollbar = ttk.Scrollbar(self.tkw, orient=VERTICAL)
        tk_entry = Listbox(self.tkw, yscrollcommand=scrollbar.set, exportselection=0)
        tk_entry.config(height=height)
        #tk_entry = Listbox(self.tkw, exportselection=0)
        scrollbar.config(command=tk_entry.yview)
        for this_item in s_items:
            tk_entry.insert(END, this_item)
        if Command is not None:
            tk_entry.bind("<Double-Button-1>", Command)
        if Selection is None:
            active_index = 0
        else:
            try:
                active_index = s_items.index(Selection)
            except ValueError:
                active_index = 0
        tk_entry.selection_set(active_index)
        parms = {'column': 1, 'row': self.last_row, 'sticky': (W, E) }
        if rowspan > 0:
            parms['rowspan'] = rowspan
        tk_entry.grid(**parms)
        #tk_entry.grid(column=1, row=self.last_row, rowspan=height, sticky=(W, E))
        if self.col_ct < 2:
            self.col_ct = 2
        frame = TkWidgetDef(refname, tk_entry, Data=tk_data)
        self.RememberPosition(frame, row, col, 2)
        self.children.append(frame)
        return frame

    def CurrentValue(self):
        if isinstance(self.tkw, ttk.Entry):
            v = self.tkd.get()
            print("CurrentValue", v)
            return v
        if isinstance(self.tkw, Listbox):
            # ix is a tuple like (2,). I assume the 2nd element would be the end of
            # the range. Or maybe it a list of items for multi-selection.
            # This works for now.
            ix = self.tkw.curselection()
            return self.tkw.get(ix)
         
    def UpdateImage(self, fn=None, opencv=None, opencvfn=None, text=None):
        img_pil = None
        img_tk = None
        if text is not None:
            # This is intended to replace an image with an error message.
            # should also do something about thumbnail but ignoring for now.
            self.tkw.configure(image=None, text=text)
            return
        if fn is not None:
            path = os.path.join(self.defaultDir, fn)
            try:
                img_pil = Image.open(path)
            except IOError:
                img_pil = None
            self.opencv_im = None
        elif opencv is not None:
            img_pil = Image.fromarray(opencv)
            self.opencv_im = opencv
        elif opencvfn is not None:
            opencv = cv2.imread(opencvfn)
            self.opencv_im = opencv
            img_pil = Image.fromarray(opencv)
        #
        if img_pil is not None:
            img_tk = ImageTk.PhotoImage(img_pil)
        if img_tk is not None:
            self.tkw.configure(image=img_tk)
            self.tkd = img_tk
        if self.thumbnail:
            self.thumbnail.UpdateImage(opencv=self.MakeThumbnail(self.opencv_im, self.thumbnailwidth))

    def MakeThumbnail(self, im, width):
        if im is None:
            return None
        if len(im.shape) > 2:
            ih, iw, ic = im.shape
        else:
            ih, iw = im.shape
            ic = 1
        tw = width
        th = int((tw / iw) * ih)
        t = cv2.resize(im, (tw, th), interpolation=cv2.INTER_LINEAR)
        return t

    def Position(self, row=-2, col=-2):
        if row == -1:
            # same row as the previous item
            row = self.last_row
        elif row == -2:
            # next sequential row
            self.last_row += 1
            row = self.last_row
        elif row == -3:
            # row below everything else
            row = self.row_ct + 1
        if col == -2:
            # use current column -- consisten with row -2 for most common sequential position
            col = self.last_col
        elif col == -3:
            # use next column to right of everything else
            col = self.col_ct + 1
        return (row, col)

    def RememberPosition(self, entry, row, col, col_ct):
        entry.row = row
        entry.col = col
        entry.col_ct = col_ct
        entry.right_col = col + col_ct - 1
        self.last_row = row
        self.last_col = col
        if row > self.row_ct:
            self.row_ct = row
        if entry.right_col > self.col_ct:
            self.col_ct = entry.right_col

    def AddImage(self, fn=None, opencv=None, opencvfn=None, 
				thumbnailof=None, thumbnailwidth=100,
				row=-2, col=-2, colspan=1):
        row, col = self.Position(row=row, col=col)
        frame = TkWidgetDef('', ttk.Label(self.tkw))
        if thumbnailof is None:
            frame.UpdateImage(fn=fn, opencv=opencv, opencvfn=opencvfn)
        else:
            # after this, the thumbnail will be automatically updated whenever the base image is updated
            frame.UpdateImage(opencv=self.MakeThumbnail(thumbnailof.opencv_im, thumbnailwidth))
            thumbnailof.thumbnail = frame
            thumbnailof.thumbnailwidth = thumbnailwidth
      
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=W)
        self.RememberPosition(frame, row, col, colspan)
        self.children.append(frame)
        return frame

    def AddLabelFrame(self, caption, row=-2, col=-2, colspan=1):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Labelframe(self.tkw, text=caption))
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=W)
        self.RememberPosition(frame, row, col, colspan)
        #frame.tkw.pack(expand="yes")
        self.children.append(frame)
        return frame

    def AddNotebook(self, row=-2, col=-2, colspan=1):
        row, col = self.Position(row=row, col=col)
	frame = TkWidgetDef('', ttk.Notebook(self.tkw))
        #frame.tkw.pack(expand="yes")
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=W)
        self.RememberPosition(frame, row, col, colspan)
        self.children.append(frame)
        return frame

    def AddTab(self, caption):
        # Add a tab to notebook
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Frame(self.tkw))
        self.tkw.add(frame.tkw, text=caption)
        self.children.append(frame)
        return frame

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
        self.steps.append(self)
        self.cv_filter = ''			# this gets set by NewFilter()
        self.parm_values = kwargs
        self.tab = self.app.notebook.AddTab("Step %d" % self.ix)
        self.input_panel = self.tab.AddLabelFrame('Input')
        self.output_panel = self.tab.AddLabelFrame('Output')
        #
        self.filter_selection = self.input_panel.AddListbox('Filters', self.filter_labels, Selection=cv_filter, Command=self.NewFilter, rowspan=4)
        self.parmEntries = []
        self.parmEntries.append(self.input_panel.AddEntryField('Parm1', row=self.filter_selection.row, col=-3)) 
        self.parmEntries.append(self.input_panel.AddEntryField('Parm2')) 
        self.parmEntries.append(self.input_panel.AddEntryField('Parm3')) 
        self.parmEntries.append(self.input_panel.AddEntryField('Parm4'))
        #
        self.image = self.output_panel.AddImage()
        self.deposition = self.output_panel.AddLabel(col=2)
        self.thumbnail = self.app.thumbnailFrame.AddImage(thumbnailof=self.image, row=0, col=-3)
        self.opencv = None			# captured image
        self.colorspace = None
        self.NewFilter()

    def UpdateAll(self):
        for this_step in self.steps:
            this_step.Update()

    def SaveParameters(self):
        for ix, this_entry in enumerate(self.parmEntries):
            if this_entry.parm_id is not None:
                # save prior value
                self.parm_values[this_entry.parm_id] = this_entry.CurrentValue()

    def NewFilter(self, *args):
        # TK callbacks seem to incude *args
        self.SaveParameters()
        new_filter = self.filter_selection.CurrentValue()
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
                this_entry.UpdateEntryField(parm_value, Caption=parm_label)
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
            e = v[1].strip()
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
            self.im = None
            self.contours = None
            self.lines = None
            print("EXEC", e, exec_g['w'], exec_g['h'])
            try:
                exec(e, exec_g)
            except:
                trace = traceback.format_exc()
        if 'outcont' in flags:
            print("SAVE CONTOURS")
            self.im = ProcessStep.annotation_base.im.copy()
            cv2.drawContours(self.im, self.contours, -1, (0, 0, 255), 1)
        if 'outlines' in flags:
            print("CONTOURS")
            self.im = ProcessStep.annotation_base.im.copy()
            deposition = "Lines\n"
            if self.lines is not None:
                map_lines = []
                h, w, c = self.im.shape
                m = int(w/2)
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
                        map_lines.append((mdist, mlen, mslope, (mx1, my1), (mx2, my2)))
            deposition += "** Lines\n"
            map_lines.sort()
            deposition += `map_lines`
            self.deposition.UpdateLabel(deposition)
        if trace is None:
            self.image.UpdateImage(opencv=self.im)
        else:
            self.image.UpdateImage(text=trace)
        if 'isbase' in flags:
            ProcessStep.annotation_base = self
        return
        if self.cv_filter == 'Crayola':
            self.image.UpdateImage(opencv=OpticChiasm.CrayolaFilter2(im))
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
    def __init__(self):
        super().__init__(Subscriptions=['cameraman/pic_ready'], Blocking=True, BlockingTimeoutSecs=0.1)
        self.tk_is_initialized = False
        self.lastfn = ""
        self.Connect()			# This starts the mqtt client in another thread
        self.image = OpticChiasm.ImageAnalyzer()
        self.image.img_crop=(300,200)
        self.image.img_crop=(250,450)
        self.image.img_crop=(150,550)
        self.image.img_crop=None
        self.image.img_cropped_height = 100
        self.image.img_fpath = 'opencv_6'
        self.image.img_source_dir = '/volumes/pi/projects/vnavs/temp'
        self.image.img_fname_suffix = ''
        self.image.do_save_snaps = False

        self.tk = TkWidgetDef('root', Tk())
        self.tk.tkw.title("VNAVS OpenCV Visualizer")
	self.statusFrame = self.tk.AddLabelFrame('Status', row=1)
	self.thumbnailFrame = self.tk.AddLabelFrame('Thumbnails', row=2)
        self.notebook = self.tk.AddNotebook(row=3)
        self.camera_iso = self.statusFrame.AddEntryField('ISO', Value=800) 
        self.camera_shutter_speed = self.statusFrame.AddEntryField('Shutter Speed', Value=10000, row=-1, col=-3) 
        self.camera_snap = False
        self.statusFrame.AddButton('Capture', command=self.CaptureImageFile, row=-1, col=-3)
        self.statusFrame.AddButton('Open File', command=self.ChooseImageFile, row=-1, col=-3)

        ProcessStep.app = self
        ProcessStep('FileImage', opencvfn='python/samples/opencv_4_s.jpg')
        ProcessStep('ColorBalance')
        ProcessStep('Crop')
        ProcessStep('BW')
        ProcessStep('Blur')
        ProcessStep('CannyAuto')
        ProcessStep('Contours')
        #ProcessStep('HoughLinesP')
        
        # self.f1_run_name_entry.focus()

    def ChooseImageFile(self):
        self.camera_snap = False
        fn = self.statusFrame.DoFileNameDialog()
        ProcessStep.steps[0].filter = 'FileImage'
        ProcessStep.steps[0].parm_values['opencvfn'] = fn
        ProcessStep.steps[0].UpdateAll()

    def CaptureImageFile(self):
        self.camera_snap = True
        settings = {}
        try:
            settings['iso'] = int(self.camera_iso.CurrentValue())
        except TypeError:
            pass
        try:
            settings['shutter_speed'] = int(self.camera_shutter_speed.CurrentValue())
        except TypeError:
            pass
        settings['mode'] = 's'
        settings['publish'] = 'm'
        settings['format'] = 'b'
        settings_j = json.dumps(settings)
        print("SNAP", settings_j)
        self.mqttc.publish('camerman/take_pic', settings_j)

    def rmsg_cameraman_pic_ready(self, msg):
        if not self.tk_is_initialized:
            return
        if not self.camera_snap:
            return
        payload = json.loads(msg)
        fn = payload['filename']
        buflen = int(payload['buflen'])
        #im = base64.b64decode(payload['imageBGR64'])
        #im = payload['imageBGR64']
        buffer = payload['imageBGRpk']
        bgr = pickle.loads(buffer)
        opencv = bgr[...,::-1]
        print("IMAGE", fn, buflen, len(buffer), opencv.shape)
        #fn = os.path.join(bot_path, msg)
        #print("PIC", msg, fn)
        #ProcessStep.steps[0].parms['opencvfn'] = fn
        #opencv =  np.fromstring(im, dtype=np.uint8)
        cv2.imwrite('bgr.jpeg', opencv)
        print("IMWRITE")
        ProcessStep.steps[0].filter = 'CapturedImage'
        ProcessStep.steps[0].colorspace = 'BGR'
        ProcessStep.steps[0].opencv = opencv
        ProcessStep.steps[0].UpdateAll()

    def mainloop(self):
        self.tk_is_initialized = True
        while True:
          # rmsg_helmsman_pic_ready is called asyncronously via mqtt
          self.CheckMqtt()						# this has a short timeout
          self.tk.tkw.update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

m = Darkroom()
m.mainloop()
