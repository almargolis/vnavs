from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)
from Tkinter import *		# python 2.7
from tkinter import ttk	# python 3
from tkinter import Canvas
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

BOT_1_MAP_TRANSPOSE = [

			[ -1.30565584e-01,  -1.56472861e+00,   4.58333935e+02],
			[ -2.57693172e-15,  -3.10871493e+00,   1.04702945e+03],
			[ -2.95275685e-18,  -3.83178162e-03,   1.00000000e+00]
		]

BOT_1_H = np.array(BOT_1_MAP_TRANSPOSE, dtype="float32")

SAME_ROW = -1
NEXT_ROW = -2
NEXT_COL = -3

class TkWidgetDef(object):
    root = None

    def __init__(self, wname, tkw, Data=None, tkw_label=None, parm_id=None):
        self.wname = wname		# reference name for this widget
        self.tkw = tkw			# tk widget
        self.tkw_label = tkw_label	# tk widget of associated label
        self.tkd = Data			# the tk data (usually StringVar) for this widget
        self.hbar = None
        self.vbar = None
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
        self.canvasWidth = 400
        self.canvasHeight = 200
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
        tk_entry.see(active_index)
        parms = {'column': 1, 'row': self.last_row, 'sticky': (W, E) }
        if rowspan > 0:
            parms['rowspan'] = rowspan
        tk_entry.grid(**parms)
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

    def RememberPosition(self, new_TkWidgetDef, row, col, colspan=1, rowspan=1):
        new_TkWidgetDef.row = row
        new_TkWidgetDef.col = col
        new_TkWidgetDef.col_ct = colspan
        new_TkWidgetDef.row_ct = rowspan
        new_TkWidgetDef.right_col = col + colspan - 1
        self.last_row = row
        self.last_col = col
        if row > self.row_ct:
            self.row_ct = row
        if new_TkWidgetDef.right_col > self.col_ct:
            self.col_ct = new_TkWidgetDef.right_col

    def AddCanvas(self, fp=None, opencv=None, opencvfn=None, 
				thumbnailof=None, thumbnailwidth=100,
				width=400, height=200,
				row=-2, col=-2, colspan=1, rowspan=1):
        row, col = self.Position(row=row, col=col)
        canvas = Canvas(self.tkw, width=width, height=height)
        frame = TkWidgetDef('', canvas)

        # The scrollbars are TK properties of the same frame as as the canvas.
        # We save the widget definitions with the canvas.
        frame.scrollableImage = None
        frame.canvasWidth = width
        frame.canvasHeight = height
        frame.hbar=ttk.Scrollbar(self.tkw, orient=HORIZONTAL)
        frame.hbar.grid(row=row+1, column=col, sticky=E+W)
        frame.vbar=ttk.Scrollbar(self.tkw, orient=VERTICAL)
        frame.vbar.grid(row=row, column=col+1, sticky=N+S)
        frame.tkw.config(width=frame.canvasWidth, height=frame.canvasHeight)
        self.AttachScrollbars()

        if thumbnailof is None:
            frame.UpdateImage(fp=fp, opencv=opencv, opencvfn=opencvfn)
        else:
            # after this, the thumbnail will be automatically updated whenever the base image is updated
            frame.UpdateImage(opencv=self.MakeThumbnail(thumbnailof.opencv_im, thumbnailwidth))
            thumbnailof.thumbnail = frame
            thumbnailof.thumbnailwidth = thumbnailwidth
      
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=W)
        # colspan and rowspan need to be expanded to allow for scrollbars ???
        self.RememberPosition(frame, row, col, colspan=colspan+1, rowspan=rowspan+1)
        self.children.append(frame)
        return frame

    def AttachScrollbars(self):
        if self.hbar is not None:
            self.hbar.config(command=self.tkw.xview)
            self.tkw.config(xscrollcommand=self.hbar.set)
        if self.vbar is not None:
            self.vbar.config(command=self.tkw.yview)
            self.tkw.config(yscrollcommand=self.vbar.set)

    def AddLabelImage(self, fn=None, opencv=None, opencvfn=None, 
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

    def UpdateImage(self, fp=None, opencv=None, opencvfn=None):
        # Replaces image in Canvas and Label widgets
        img_pil = None
        img_tk = None
        if fp is not None:
            try:
                img_pil = Image.open(fp)
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
            imWidth = img_pil.width
            if self.canvasWidth < imWidth:
                imHeight = img_pil.height
                height = int((self.canvasWidth / imWidth) * imHeight)
                img_pil = img_pil.resize((self.canvasWidth, height))
                print("RESIZE", self.canvasWidth, height)
            img_tk = ImageTk.PhotoImage(img_pil)
        self.tkd = img_tk
        if img_tk is not None:
            if isinstance(self.tkw, ttk.Label):
                self.tkw.configure(image=img_tk)
            elif isinstance(self.tkw, Canvas):
                if self.scrollableImage is None:
                    self.scrollableImage = self.tkw.create_image(0, 0, image=img_tk, anchor='nw')
                else:
                    self.tkw.itemconfig(self.scrollableImage, image=img_tk)
                width, height = img_pil.size
                self.tkw.config(scrollregion=(0, 0, width, height))
                pctWidth = self.canvasWidth / width
                if pctWidth > 1.0:
                    pctWidth = 1.0
                self.hbar.set(0.0, pctWidth)
                pctHeight = self.canvasHeight / height
                if pctHeight > 1.0:
                    pctHeight = 1.0
                self.vbar.set(0.0, pctHeight)
            else:
                raise TypeError("Unsupported image widget: " + self.tkw.__class__.__name__)
        self.AttachScrollbars()
        if self.thumbnail:
            self.thumbnail.UpdateImage(opencv=self.MakeThumbnail(self.opencv_im, self.thumbnailwidth))

    def AddLabelFrame(self, caption, row=-2, col=-2, colspan=1):
        row, col = self.Position(row=row, col=col)
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Labelframe(self.tkw, text=caption))
        frame.tkw.grid(column=col, columnspan=colspan, row=row, sticky=W)
        self.RememberPosition(frame, row, col, colspan)
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
        self.filter_selection = self.input_panel.AddListbox('Filters', self.filter_labels, Selection=cv_filter, Command=self.NewFilter, rowspan=4)
        self.parmEntries = []
        self.parmEntries.append(self.input_panel.AddEntryField('Parm1', row=self.filter_selection.row, col=-3)) 
        self.parmEntries.append(self.input_panel.AddEntryField('Parm2')) 
        self.parmEntries.append(self.input_panel.AddEntryField('Parm3')) 
        self.parmEntries.append(self.input_panel.AddEntryField('Parm4'))
        #
        self.image = self.output_panel.AddCanvas()
        self.deposition = self.output_panel.AddLabel(col=2)
        self.thumbnail = self.app.thumbnailFrame.AddLabelImage(thumbnailof=self.image, row=0, col=-3)
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
            self.deposition.UpdateLabel(deposition)
        if trace is not None:
            deposition = trace + "\n\n" + deposition
            self.deposition.UpdateLabel(deposition)
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
    def __init__(self):
        super().__init__(Subscriptions=['archiver/pic_ready', 'cameraman/last', 'cameraman/pic_ready'],
					Blocking=True, BrokerType='F', BlockingTimeoutSecs=0.1,
					Verbose=True)
        self.tk_is_initialized = False
        self.imageDir = self.config.get("Cameraman", "ImageDir")
        self.lastfn = ""
        self.image = OpticChiasm.ImageAnalyzer()
        self.image.img_crop=(300,200)
        self.image.img_crop=(250,450)
        self.image.img_crop=(150,550)
        self.image.img_crop=None
        self.image.img_cropped_height = 100
        self.image.img_fpath = 'opencv_6'
        self.image.img_source_dir = '/volumes/pi/projects/vnavs/temp'
        self.image.img_fname_suffix = ''

        self.tk = TkWidgetDef('root', Tk())
        self.tk.tkw.title("VNAVS OpenCV Visualizer")
	self.statusFrame = self.tk.AddLabelFrame('Status', row=1)
	self.thumbnailFrame = self.tk.AddLabelFrame('Thumbnails', row=2)
        self.notebook = self.tk.AddNotebook(row=3)
        self.camera_iso = self.statusFrame.AddEntryField('ISO', Value=800) 
        self.camera_shutter_speed = self.statusFrame.AddEntryField('Shutter Speed', Value=10000, row=-1, col=-3) 
        self.camera_snap = False
        self.camera_last_filename = ''
        self.camera_last_processed = True
        self.statusFrame.AddButton('Capture', command=self.CaptureImageFile, row=-1, col=-3)
        self.statusFrame.AddButton('Open File', command=self.ChooseImageFile, row=-1, col=-3)

        ProcessStep.app = self
        #ProcessStep('None')
        ProcessStep('FileImage', opencvfn=None)
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
            self.camera_iso.set(100)
        try:
            settings['shutterSpeed'] = int(self.camera_shutter_speed.CurrentValue())
        except TypeError:
            self.camera_shutter_speed.set(0)
        settings['loopMode'] = 'run'
        settings['loopFormat'] = 'bgr'
        settings['loopPublish'] = 'stream'
        settings['captureMode'] = 'single'
        settings['captureFormat'] = 'jpeg'
        settings['capturePublish'] = 'file'
        settings_j = json.dumps(settings)
        print("SNAP", settings_j)
        self.mqttc.publish('cameraman/orders', settings_j)
        time.sleep(1)
        self.mqttc.publish('cameraman/ask_last', '')

    def rmsg_archiver_pic_ready(self, msg):
        return # -- there are too many of these to process
        if not self.camera_snap:
            return
        payload = json.loads(msg)
        fn = payload['filename']
        fnp = os.path.join('temp', fn)
        ifile = open(fnp, "rb")
        buflen = int(payload['buflen'])
        buffer = ifile.read()
        bgr = pickle.loads(buffer)
        opencv = bgr[...,::-1]
        print("IMAGE", fn, buflen, len(buffer), opencv.shape)
        cv2.imwrite('bgr.jpeg', opencv)
        print("IMWRITE")
        ProcessStep.steps[0].filter = 'CapturedImage'
        ProcessStep.steps[0].colorspace = 'BGR'
        ProcessStep.steps[0].opencv = opencv
        ProcessStep.steps[0].UpdateAll()

    def rmsg_cameraman_last(self, msg):
        # Do as little as possible here in mqtt thread.
        # Process image in tk thread.
        print("LAST", msg)
        if not self.camera_snap:
            return
        payload = json.loads(msg)
        self.camera_last_filename  = payload['filename']
        self.camera_last_processed = False
        print("LAST", ProcessStep.steps[0].parm_values)

    def rmsg_cameraman_pic_ready(self, msg):
        return # -- there are too many of these to process
        if not self.camera_snap:
            return
        payload = json.loads(msg)
        fn = payload['filename']
        format = payload['format']
        buffer = None
        buffer_len = 0
        bgr = None
        opencv = None
        opencv_shape = None
        if 'buflen' in payload:
            buflen = int(payload['buflen'])
        else:
            buflen = 0
        #im = base64.b64decode(payload['imageBGR64'])
        #im = payload['imageBGR64']
        if 'imageBGRpk' in payload:
            buffer = payload['imageBGRpk']
            buffer_len = len(buffer)
            bgr = pickle.loads(buffer)
            opencv = bgr[...,::-1]
        publish = payload['publish']
        if publish == 'f':
            fn = os.path.join(self.imageDir, fn)
            opencv = cv2.imread(fn)
        if opencv is not None:
            opencv_shape = opencv.shape
        print("IMAGE", fn, buflen, buffer_len, opencv_shape)
        #print("PIC", msg, fn)
        #ProcessStep.steps[0].parms['opencvfn'] = fn
        #opencv =  np.fromstring(im, dtype=np.uint8)
        cv2.imwrite('bgr.jpeg', opencv)
        print("IMWRITE")
        ProcessStep.steps[0].filter = 'CapturedImage'
        ProcessStep.steps[0].colorspace = 'BGR'
        ProcessStep.steps[0].opencv = opencv
        ProcessStep.steps[0].UpdateAll()

    def DoLoop(self):
        if not self.camera_last_processed:
            # There is a potential race condition with self.camera_last_processed being
            # assigned from both mqtt and tk threads. That could be confusing or make the
            # program fee unresponsive but shouldn't cause real harm.
            # THIS ASSUMES capture to step zero, we should seatch for actual step.
            fpath = os.path.join(self.imageDir, self.camera_last_filename)
            ProcessStep.steps[0].parm_values['opencvfn'] = fpath
            ProcessStep.steps[0].filter = 'FileImage'
            ProcessStep.steps[0].UpdateAll()
            self.camera_last_processed = True
        self.tk.tkw.update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

if __name__ == '__main__':
    m = Darkroom()
    m.Loop()
