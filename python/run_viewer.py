from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)
from Tkinter import *		# python 2.7
from tkinter import ttk	# python 3
from tkinter import Canvas
import tkFileDialog
#from Tkinter import *		# python 2.7
#import ttk			# python 2.7

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

import darkroom
import OpticChiasm
import vnavs_mqtt

        
class RunViewer(vnavs_mqtt.mqtt_node):
    def __init__(self):
        super().__init__(Subscriptions=[], Blocking=True, BlockingTimeoutSecs=0.1)
        self.imageDir = self.config.get("Cameraman", "ImageDir")

        self.tk = darkroom.TkWidgetDef('root', Tk())
        self.tk.tkw.title("VNAVS Run Viewer")
	self.statusFrame = self.tk.AddLabelFrame('Status', row=1)
	self.thumbnailFrame = self.tk.AddLabelFrame('Thumbnails', row=2)
        self.notebook = self.tk.AddNotebook(row=3)
        self.camera_iso = self.statusFrame.AddEntryField('ISO', Value=800) 
        self.camera_shutter_speed = self.statusFrame.AddEntryField('Shutter Speed', Value=10000, row=-1, col=-3) 
        self.camera_snap = False
        self.camera_last_filename = ''
        self.camera_last_processed = True
        self.statusFrame.AddButton('Next', command=self.NextImageFile, row=darkroom.SAME_ROW, col=darkroom.NEXT_COL)
        self.statusFrame.AddButton('Prev', command=self.PrevImageFile, row=darkroom.SAME_ROW, col=darkroom.NEXT_COL)

        self.tab1 = self.notebook.AddTab('Tab1')
        self.im1_info = self.tab1.AddLabel("", row=darkroom.NEXT_ROW)
        self.im1 = self.tab1.AddCanvas(row=darkroom.NEXT_ROW, col=0, width=400, height=200)
        self.im2 = self.tab1.AddCanvas(row=darkroom.SAME_ROW, col=darkroom.NEXT_COL, width=400, height=200)

        self.path = '/Users/almargolis/projects/diy_20170401'
        files = os.listdir(self.path)
        self.files = []
        for this in files:
            if this[-7:] == '-B.jpeg':
                continue
            self.files.append(this)
        self.files.sort()
        self.file_ix = 0
        
    def NextImageFile(self):
        if self.file_ix < len(self.files):
            self.ShowImage(self.file_ix)
            self.file_ix += 1

    def PrevImageFile(self):
        if (self.file_ix > 0) and (self.file_ix < len(self.files)):
            self.ShowImage(self.file_ix)
            self.file_ix -= 1

    def ShowImage(self, ix):
        fn = self.files[ix]
        fp = os.path.join(self.path, fn)
        self.im1.UpdateImage(fp=fp)
        imHeight = self.im1.tkd.height()
        imWidth = self.im1.tkd.width()
        self.im1_info.UpdateLabel("%s -- %d x %d" % (fn, imWidth, imHeight))
        if fp[-7:] == '-A.jpeg':
            fp = fp[:-7] + '-B.jpeg'
            self.im2.UpdateImage(fp=fp)
            

    def rmsg_archiver_pic_ready(self, payload):
        return # -- there are too many of these to process
        if not self.camera_snap:
            return
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

    def DoLoop(self):
        # rmsg_helmsman_pic_ready is called asyncronously via mqtt
        self.tk.tkw.update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

if __name__ == '__main__':
    m = RunViewer()
    m.Loop()
