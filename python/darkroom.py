from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)
from tkinter import *		# python 3
from tkinter import ttk	# python 3
import tkFileDialog
#from Tkinter import *		# python 2.7
#import ttk			# python 2.7

import json
import sys
import os
from PIL import ImageTk, Image

import threading
import time

import cv2
import numpy

import OpticChiasm
import vnavs_mqtt

bot_path = "/Volumes/pi/projects/vnavs"

BOT_1_MAP_TRANSPOSE = [

			[ -1.30565584e-01,  -1.56472861e+00,   4.58333935e+02],
			[ -2.57693172e-15,  -3.10871493e+00,   1.04702945e+03],
			[ -2.95275685e-18,  -3.83178162e-03,   1.00000000e+00]
		]

BOT_1_H = pts_dst = numpy.array(BOT_1_MAP_TRANSPOSE, dtype="float32")

class TkWidgetDef(object):
    root = None
    defaultDir = '.'

    def __init__(self, wname, tkw, Data=None):
        self.wname = wname		# reference name for this widget
        self.tkw = tkw			# tk widget
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
        tk_label = ttk.Label(self.tkw, text=caption).grid(column=col, row=row, sticky=W)
        tk_entry = ttk.Entry(self.tkw, width=Width, textvariable=tk_data)
        tk_entry.grid(column=col+1, row=row, sticky=(W, E))
        frame = TkWidgetDef(refname, tk_entry, Data=tk_data)
        self.RememberPosition(frame, row, col, 2)
        self.children.append(frame)
        return frame

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
            return self.tkd.get()
        if isinstance(self.tkw, Listbox):
            # ix is a tuple like (2,). I assume the 2nd element would be the end of
            # the range. Or maybe it a list of items for multi-selection.
            # This works for now.
            ix = self.tkw.curselection()
            return self.tkw.get(ix)
         
    def UpdateImage(self, fn=None, opencv=None, opencvfn=None):
        img_pil = None
        img_tk = None
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

    def AddLabelFrame(self, caption):
        self.last_row += 1
        refname = caption.lower().replace(' ', '_')
        frame = TkWidgetDef(refname, ttk.Labelframe(self.tkw, text=caption))
        frame.tkw.pack(expand="yes")
        self.children.append(frame)
        return frame

    def AddNotebook(self):
	frame = TkWidgetDef('', ttk.Notebook(self.tkw))
        frame.tkw.pack(expand="yes")
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

FILTERS = [
		'None',
		'BaseImage',
		'Crop',
		'BW',
                'Blur',
		'Canny',
		'Contours',
		'Map',
		'FL'
		'Crayola',
]

class ProcessStep(object):
    app = None
    steps = []
    annotation_base = None
    def __init__(self, filter, Parms=[], **kwargs):
        self.ix = len(self.steps)
        self.steps.append(self)
        self.filter = filter
        self.parms = kwargs
        self.tab = self.app.notebook.AddTab("Step %d" % self.ix)
        #self.option_panel = self.tab.AddLabelFrame('Options')
        self.filter_selection = self.tab.AddListbox('Filters', FILTERS, Selection=self.filter, Command=self.NewFilter, rowspan=4)
        while len(Parms) < 4:
            Parms.append('')
        self.parm1 = self.tab.AddEntryField('Parm1', Value=Parms[0], row=self.filter_selection.row, col=-3) 
        self.parm2 = self.tab.AddEntryField('Parm2', Value=Parms[1]) 
        self.parm3 = self.tab.AddEntryField('Parm3', Value=Parms[2]) 
        self.parm4 = self.tab.AddEntryField('Parm4', Value=Parms[3]) 
        self.image = self.tab.AddImage(row=-3, colspan=4)
        self.thumbnail = self.app.thumbnailFrame.AddImage(thumbnailof=self.image, row=0, col=-3)
        self.Update()

    def UpdateAll(self):
        for this_step in self.steps:
            this_step.Update()

    def NewFilter(self, *args):
        # TK callbacks seem to incude *args
        new_filter = self.filter_selection.CurrentValue()
        if new_filter != self.filter:
            self.filter = new_filter
        self.UpdateAll()

    def Update(self):
        if self.filter == 'BaseImage':
            self.image.UpdateImage(opencvfn=self.parms['opencvfn'])
            ProcessStep.annotation_base = self
            return
        im = self.steps[self.ix - 1].image.opencv_im
        if len(im.shape) > 2:
            h, w, c = im.shape
        else:
            h, w = im.shape
            c = 1
        parm1 = self.parm1.CurrentValue()
        parm2 = self.parm2.CurrentValue()
        try:
            spec1 = int(parm1)
        except ValueError:
            spec1 = 0
        try:
            spec1f = float(parm1)
        except ValueError:
            spec1f = 0.0
        try:
            spec2 = int(parm2)
        except ValueError:
            spec2 = 0
        if self.filter == 'Crop':
            x1 = 0
            x2 = w
            y1 = 0
            y2 = h
            if spec1 < 0:
                m = int(w / 2)
                x1 = m + spec1
                x2 = m - spec1
                if x1 < 0:
                    x1 = 0
                if x2 > w:
                    x2 = w
            if spec2 < 0:
                y1 = h + spec2
                if y1 < 0:
                    y1 = 0
            self.image.UpdateImage(opencv=im.copy()[y1:y2, x1:x2])
            ProcessStep.annotation_base = self
            return
        if self.filter == 'Blur':
            if spec1 < 1:
                spec1 = 1
            self.image.UpdateImage(opencv=cv2.blur(im, (spec1, spec1)))
            return
        if self.filter == 'BW':
            self.image.UpdateImage(opencv=cv2.cvtColor(im, cv2.COLOR_BGR2GRAY))
            return
        if self.filter == 'Canny':
            self.image.UpdateImage(opencv=OpticChiasm.auto_canny(im, spec1f))
            return
        if self.filter == 'Contours':
            (imgxx, opencv_contours, hierarchy) = cv2.findContours(im, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            im2 = ProcessStep.annotation_base.image.opencv_im.copy()
            cv2.drawContours(im2, opencv_contours, -1, (0, 0, 255), 1)
            self.image.UpdateImage(opencv=im2)
            return
        if self.filter == 'Crayola':
            self.image.UpdateImage(opencv=OpticChiasm.CrayolaFilter2(im))
            return
        if self.filter == "Map":
            self.image.UpdateImage(opencv=cv2.warpPerspective(im, BOT_1_H, (w, h)))
            return
        if self.filter == 'FL':
            self.image.UpdateImage(opencv=self.app.image.FindLines(image=im))
            return
        # This should be filter "None"
        self.image.UpdateImage(opencv=im.copy())
        return

            
        
class Darkroom(vnavs_mqtt.mqtt_node):
    def __init__(self):
        super().__init__(Subscriptions=['helmsman/pic_ready'], Blocking=True, BlockingTimeoutSecs=0.1)
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
	self.statusFrame = self.tk.AddLabelFrame('Status')
	self.thumbnailFrame = self.tk.AddLabelFrame('Thumbnails')
        self.notebook = self.tk.AddNotebook()
        self.camera_iso = self.statusFrame.AddEntryField('ISO', Value=800) 
        self.camera_shutter_speed = self.statusFrame.AddEntryField('Shutter Speed', Value=10000, row=-1, col=-3) 
        self.camera_snap = False
        self.statusFrame.AddButton('Capture', command=self.CaptureImageFile, row=-1, col=-3)
        self.statusFrame.AddButton('Open File', command=self.ChooseImageFile, row=-1, col=-3)

        ProcessStep.app = self
        ProcessStep('BaseImage', opencvfn='python/samples/opencv_4_s.jpg')
        ProcessStep('Crop', Parms=[-50, -100])
        ProcessStep('BW')
        ProcessStep('Blur', Parms=[3])
        ProcessStep('Canny', Parms=[0.33])
        ProcessStep('Contours')
        
        # self.f1_run_name_entry.focus()

    def ChooseImageFile(self):
        self.camera_snap = False
        fn = self.statusFrame.DoFileNameDialog()
        ProcessStep.steps[0].parms['opencvfn'] = fn
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
        settings_j = json.dumps(settings)
        print("SNAP", settings_j)
        self.mqttc.publish('helmsman/take_pic', settings_j)

    def rmsg_helmsman_pic_ready(self, msg):
        if not self.tk_is_initialized:
            return
        if not self.camera_snap:
            return
        fn = os.path.join(bot_path, msg)
        print("PIC", msg, fn)
        ProcessStep.steps[0].parms['opencvfn'] = fn
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
