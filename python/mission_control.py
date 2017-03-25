from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)
from tkinter import *		# python 3
from tkinter import ttk	# python 3

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
import paho.mqtt.client as mqtt

bot_path = "/Volumes/pi-1/projects/vnavs"

BOT_1_MAP_TRANSPOSE = [

			[ -1.30565584e-01,  -1.56472861e+00,   4.58333935e+02],
			[ -2.57693172e-15,  -3.10871493e+00,   1.04702945e+03],
			[ -2.95275685e-18,  -3.83178162e-03,   1.00000000e+00]
		]

BOT_1_H = pts_dst = numpy.array(BOT_1_MAP_TRANSPOSE, dtype="float32")

class MissionControl(vnavs_mqtt.mqtt_node):
    def __init__(self):
        super().__init__(Subscriptions=['cameraman/last', 'cameraman/pic_ready', 'helmsman/orders'], Blocking=True, BlockingTimeoutSecs=0.1)
        self.tk_is_initialized = False
        self.lastfn = ""
        self.Connect()			# This starts the mqtt client in another thread
        self.tk_root = Tk()
        self.tk_root.title("VNAVS Mission Control")
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
        self.pic_fn = None
        self.pic_processed = False
        self.pic_requested = False
        self.pic_request_time = 0

        mainframe = self.tk_root

        # row 0
        this_row = 0
        self.f1_run_name = StringVar()
        self.f1_run_name.set('')
        ttk.Label(mainframe, text='Run Name').grid(column=0, row=this_row, sticky=W)
        self.f1_run_name_entry = ttk.Entry(mainframe, width=7, textvariable=self.f1_run_name)
        self.f1_run_name_entry.grid(column=1, row=this_row, sticky=(W, E))

        # row 1
        this_row = 1
        f = ttk.Frame(mainframe)
        f.grid(row=this_row, column=0, columnspan=4)
        b = ttk.Button(f, text='Start', command=self.StartNav)
        b.grid(row=this_row, column=0)
        b = ttk.Button(f, text='Stop', command=self.StopNav)
        b.grid(row=this_row, column=1)
        b = ttk.Button(f, text='Snap', command=self.SnapPic)
        b.grid(row=this_row, column=2)
        #ttk.Label(mainframe, text='Speed').grid(column=0, row=this_row, sticky=W)
        #self.f1_speed_control = Scale(mainframe, from_=-100, to=100, orient="horizontal")
        #self.f1_speed_control.grid(column=1, row=this_row)
        #self.f1_speed_display = ttk.Label(mainframe, text='0')
        #self.f1_speed_display.grid(column=2, row=this_row, sticky=W)

        # row 2
        this_row = 2
        ttk.Label(mainframe, text='Steering').grid(column=0, row=this_row, sticky=W)
        self.f1_steering_control = Scale(mainframe, from_=0, to=100, orient="horizontal")
        self.f1_steering_control.grid(column=1, row=this_row)
        self.f1_steering_display = ttk.Label(mainframe, text='0')
        self.f1_steering_display.grid(column=2, row=this_row, sticky=W)

        # row 3
        this_row = 3
        self.f1_fname = StringVar()
        self.f1_fname.set('fname')
        self.f1_label1 = ttk.Label(mainframe, textvariable=self.f1_fname)
        self.f1_label1.grid(columnspan=2, row=this_row, sticky=W)

        # row 4
        fn = "bgr.jpeg"
        #path = os.path.join(bot_path, fn)
        path = fn
        self.img1_pil = self.ImagePillow(path)
        self.img1_tk = ImageTk.PhotoImage(self.img1_pil)
        self.f1_img1 = ttk.Label(mainframe, image = self.img1_tk)
        self.f1_img1.grid(column=0, columnspan=2, row=4, sticky=W)

        # row 5
        self.img2_pil = self.ImageCv2(path)
        self.img2_tk = ImageTk.PhotoImage(self.img2_pil)
        self.f1_img2 = ttk.Label(mainframe, image = self.img2_tk)
        self.f1_img2.grid(column=3, columnspan=1, row=4, sticky=W)
        #for child in mainframe.winfo_children():
        #    child.grid_configure(padx=5, pady=5)

        self.f1_run_name_entry.focus()

    def ImageCv2(self, path):
        im = cv2.imread(path)
        h, w, c = im.shape
        mapped_width = w
        mapped_height = h
        #mapped_im = cv2.warpPerspective(im, BOT_1_H, (mapped_width, mapped_height))
        mapped_im = self.image.FindLines(image=im)
        return Image.fromarray(mapped_im)

    def ImagePillow(self, path):
        try:
            im = Image.open(path)
        except IOError:
            print("ImagePillow() ERROR", path)
            im = None
        return im

    def rmsg_helmsman_orders(self, msg):
        self.f1_run_name.set(msg)

    def rmsg_cameraman_pic_ready(self, msg):
        self.rmsg_cameraman_last(msg)

    def rmsg_cameraman_last(self, msg):
        if not self.tk_is_initialized:
            return
        payload = json.loads(msg)
        new_fn = payload['filename']
        if new_fn == self.pic_fn:
            return
        #time.sleep(0.5)
        self.pic_fn = new_fn
        self.pic_processed = False
        print("PIC", self.pic_fn)

    def SnapPic(self):
        payload = {}
        payload['mode'] = 's'
        payload['publish'] = 'f'
        payload['capture'] = 's'
        payload['format'] = 'j'
        (res, mid) = self.mqttc.publish('cameraman/orders', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def StartNav(self):
        payload = {}
        payload['mode'] = 'r'
        payload['publish'] = 'm'
        payload['capture'] = 'r'
        payload['format'] = 'b'
        (res, mid) = self.mqttc.publish('cameraman/orders', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def StopNav(self):
        payload = {}
        payload['mode'] = 'p'
        payload['publish'] = 'm'
        payload['capture'] = 'n'
        payload['format'] = 'b'
        (res, mid) = self.mqttc.publish('cameraman/orders', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")
        #
        time.sleep(1)
        payload = {}
        payload['speed'] = 0
        (res, mid) = self.mqttc.publish('helmsman/orders', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def ProcessImage(self):
        self.f1_fname.set(self.pic_fn)
        path = os.path.join(bot_path, self.pic_fn)
        self.img1_pil = self.ImagePillow(path)
        #self.img2_pil = self.ImageCv2(path)
        if self.img1_pil is not None:
            self.img1_tk = ImageTk.PhotoImage(self.img1_pil)
        self.img2_tk = ImageTk.PhotoImage(self.img2_pil)
        self.f1_img1.configure(image = self.img1_tk)
        self.f1_img2.configure(image = self.img2_tk)
        self.pic_processed = True
        self.pic_requested = False

    def mainloop(self):
        self.tk_is_initialized = True
        while True:
          # rmsg_helmsman_pic_ready is called asyncronously via mqtt
          self.CheckMqtt()						# this has a short timeout
          #speed = int(self.f1_speed_control.get())
          #self.f1_speed_display.configure(text=str(speed))
          if (self.pic_fn is None) or (self.pic_fn == '') or self.pic_processed:
              pass
          else:
              self.ProcessImage()
          if (not self.pic_requested) or ((time.time() - self.pic_request_time) > 1):
              print("ASK LAST")
              #self.mqttc.publish('cameraman/ask_last', '')
              self.pic_requested = True
              self.pic_request_time = time.time()
          self.tk_root.update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

m = MissionControl()
m.mainloop()
