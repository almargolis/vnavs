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

BOT_1_MAP_TRANSPOSE = [

			[ -1.30565584e-01,  -1.56472861e+00,   4.58333935e+02],
			[ -2.57693172e-15,  -3.10871493e+00,   1.04702945e+03],
			[ -2.95275685e-18,  -3.83178162e-03,   1.00000000e+00]
		]

BOT_1_H = pts_dst = numpy.array(BOT_1_MAP_TRANSPOSE, dtype="float32")

class MissionControl(vnavs_mqtt.mqtt_node):
    def __init__(self):
        super().__init__(Subscriptions=['cameraman/last', 'cameraman/pic_ready', 
						'engineer_1/status', 'helmsman/orders'], 
						Blocking=True, BlockingTimeoutSecs=0.1,
						BrokerType='F')
        self.lastfn = ""
        self.tk_root = Tk()
        self.tk_root.title("VNAVS Mission Control")
        self.image = OpticChiasm.ImageAnalyzer()
        self.image.img_crop=(300,200)
        self.image.img_crop=(250,450)
        self.image.img_crop=(150,550)
        self.image.img_crop=None
        self.image.img_cropped_height = 100
        self.image.img_fpath = 'opencv_6'
        self.imageDir = self.config.get("Cameraman", "ImageDir")
        self.image.img_source_dir = '/volumes/pi/projects/vnavs/temp'
        self.image.img_fname_suffix = ''
        self.image.do_save_snaps = False
        self.pic_fn = None
        self.pic_processed = False
        self.pic_requested = False
        self.pic_request_time = 0

        mainframe = self.tk_root

        #
        this_row = 0
        self.f1_helmsman_status = StringVar()
        self.f1_helmsman_status.set('')
        ttk.Label(mainframe, text='Helmsman').grid(column=0, row=this_row, sticky=W)
        self.f1_helmsman_entry = ttk.Entry(mainframe, width=75, textvariable=self.f1_helmsman_status)
        self.f1_helmsman_entry.grid(column=1, row=this_row, sticky=(W, E))

        #
        this_row += 1
        self.f1_engineer_1_status = StringVar()
        self.f1_engineer_1_status.set('')
        ttk.Label(mainframe, text='Engineer_1').grid(column=0, row=this_row, sticky=W)
        self.f1_engineer_1_entry = ttk.Entry(mainframe, width=75, textvariable=self.f1_engineer_1_status)
        self.f1_engineer_1_entry.grid(column=1, row=this_row, sticky=(W, E))

        #
        this_row += 1
        f = ttk.Frame(mainframe)
        f.grid(row=this_row, column=0, columnspan=2)
        self.mission_name = StringVar()
        self.mission_name.set('test')
        self.mission_name_entry = ttk.Entry(mainframe, width=15, textvariable=self.mission_name)
        self.mission_name_entry.grid(row=0, column=0, sticky=(W, E))
        b = ttk.Button(f, text='Start', command=self.StartNav)
        b.grid(row=0, column=1)
        b = ttk.Button(f, text='Stop', command=self.StopNav)
        b.grid(row=0, column=2)
        b = ttk.Button(f, text='Snap', command=self.SnapPic)
        b.grid(row=0, column=3)
        b = ttk.Button(f, text='Clear Waypoints', command=self.ClearWaypoints)
        b.grid(row=0, column=4)
        b = ttk.Button(f, text='Mark Waypoint', command=self.MarkWaypoint)
        b.grid(row=0, column=5)
        b = ttk.Button(f, text='Save Waypoints', command=self.SaveWaypoints)
        b.grid(row=0, column=6)

        #
        this_row += 1
        ttk.Label(mainframe, text='Steering').grid(column=0, row=this_row, sticky=W)
        self.f1_steering_control = Scale(mainframe, from_=0, to=100, orient="horizontal")
        self.f1_steering_control.grid(column=1, row=this_row)
        self.f1_steering_display = ttk.Label(mainframe, text='0')
        self.f1_steering_display.grid(column=2, row=this_row, sticky=W)

        #
        this_row += 1
        self.f1_fname = StringVar()
        self.f1_fname.set('fname')
        self.f1_label1 = ttk.Label(mainframe, textvariable=self.f1_fname)
        self.f1_label1.grid(columnspan=2, row=this_row, sticky=W)

        #
        this_row += 1
        fn = "bgr.jpeg"
        #path = os.path.join(self.imageDir, fn)
        self.f1_img1 = ttk.Label(mainframe)
        path = fn
        #self.img1_pil = self.ImagePillow(path)
        self.img1_pil = None
        if self.img1_pil is None:
            self.img1_tk = None
        else:
            self.img1_tk = ImageTk.PhotoImage(self.img1_pil)
            self.f1_img1.configure(image = self.img1_tk)
        self.f1_img1.grid(column=0, columnspan=2, row=this_row, sticky=W)

        self.f1_helmsman_entry.focus()

    def ImageCv2(self, path):
        im = cv2.imread(path)
        if im is None:
            return None
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

    def rmsg_helmsman_orders(self, payload):
        self.f1_helmsman_status.set(payload)

    def rmsg_engineer_1_status(self, payload):
        self.f1_engineer_1_status.set(payload)

    def rmsg_cameraman_pic_ready(self, payload):
        self.rmsg_cameraman_last(payload)

    def rmsg_cameraman_last(self, payload):
        self.pic_fn = payload['filename']
        self.pic_processed = False
        print("PIC", self.pic_fn)

    def ClearWaypoints(self):
        payload = {}
        payload['request'] = 'C'
        (res, mid) = self.mqttc.publish('navigator/waypoint', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def MarkWaypoint(self):
        payload = {}
        payload['request'] = 'M'
        (res, mid) = self.mqttc.publish('navigator/waypoint', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def SaveWaypoints(self):
        payload = {}
        payload['request'] = 'S'
        payload['missionName'] = self.mission_name.get()
        (res, mid) = self.mqttc.publish('navigator/waypoint', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def SnapPic(self):
        payload = {}
        payload['loopMode'] = 'run'
        payload['loopFormat'] = 'bgr'
        payload['loopPublish'] = 'stream'
        payload['captureMode'] = 'run'
        payload['captureFormat'] = 'jpeg'
        payload['capturePublish'] = 'file'
        (res, mid) = self.mqttc.publish('cameraman/orders', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def StartNav(self):
        payload = {}
        payload['loopMode'] = 'run'
        payload['loopFormat'] = 'bgr'
        payload['loopPublish'] = 'stream'
        payload['captureMode'] = 'run'
        payload['captureFormat'] = 'jpeg'
        payload['capturePublish'] = 'file'
        (res, mid) = self.mqttc.publish('cameraman/orders', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")
        #
        payload = {}
        payload['mode'] = 'G'
        payload['missionName'] = self.mission_name.get()
        (res, mid) = self.mqttc.publish('navigator/mode', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def StopNav(self):
        payload = {}
        payload['captureMode'] = 'none'
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
        #
        payload = {}
        payload['mode'] = 'M'
        payload['missionName'] = self.mission_name.get()
        (res, mid) = self.mqttc.publish('navigator/mode', json.dumps(payload))
        if res != mqtt.MQTT_ERR_SUCCESS:
            print("MQTT Publish Error")

    def ProcessImage(self):
        self.f1_fname.set(self.pic_fn)
        path = os.path.join(self.imageDir, self.pic_fn)
        self.img1_pil = self.ImagePillow(path)
        if self.img1_pil is None:
            self.img1_tk = None
        else:
            try:
                self.img1_tk = ImageTk.PhotoImage(self.img1_pil)
            except IOError:
                # This exception had additional info of file truncated.
                # I am guessing that this is happening because messages are getting
                # sent faster than they get written to SD. 
                self.img1_tk = None
                self.img1_pil = None
        if self.img1_tk is not None:
            self.f1_img1.configure(image = self.img1_tk)
        self.pic_processed = True
        self.pic_requested = False

    def DoLoop(self):
        #speed = int(self.f1_speed_control.get())
        #self.f1_speed_display.configure(text=str(speed))
        if (self.pic_fn is None) or (self.pic_fn == '') or self.pic_processed:
            pass
        else:
            self.ProcessImage()
        #if (not self.pic_requested) or ((time.time() - self.pic_request_time) > 1):
        #    print("ASK LAST")
        #    #self.mqttc.publish('cameraman/ask_last', '')
        #    self.pic_requested = True
        #    self.pic_request_time = time.time()
        self.tk_root.update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

m = MissionControl()
m.Loop()
