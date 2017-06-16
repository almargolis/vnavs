from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import json
import sys
import os
from PIL import ImageTk, Image

import threading
import time

import cv2
import numpy

import easytk
from easytk import SAME_ROW, NEXT_ROW, NEXT_COL, COL_SPAN_ALL
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
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=['cameraman/pic_ready',
						'engineer_1/gps',
						'engineer_1/imu',
						'helmsman/orders',
						'MissionControl/notice',
						'navigator/status'
						], 
			Readers=[
						'cameraman/pic_ready'
						],
						SingleThreaded=True, SelectTimeoutSecs=0.1,
						BrokerType='F',
						Verbose=Verbose)
        self.file_client = vnavs_mqtt.FileClient(Verbose=True)
        self.lastfn = ""

        self.tk = easytk.EasyTk(debug=True)
        self.tk.tkw.title("VNAVS Mission Control")
        self.statusFrame = self.tk.AddLabelFrame('Status', row=1)
        self.thumbnailFrame = self.tk.AddLabelFrame('Thumbnails', row=2)
        self.notebook = self.tk.AddNotebook(row=3)

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
        self.pic_last_time = time.time()
        self.pic_processed = False
        self.pic_requested = False
        self.pic_request_time = 0

        mainframe = self.notebook.AddTab('Mission')
        self.f1_helmsman_entry = mainframe.AddEntryField('Helmsman', width=75)
        self.f1_engineer_1_entry = mainframe.AddEntryField('Engineer_1', width=75)
        self.mission_name_entry = mainframe.AddEntryField('Mission', width=15, value='test')
        buttonframe = mainframe.AddFrame(colspan=COL_SPAN_ALL)
        buttonframe.AddButton('Start', command=self.StartNav, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Stop', command=self.StopNav, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Snap', command=self.SnapPic, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Clear Waypoints', command=self.ClearWaypoints, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Mark Waypoint', command=self.MarkWaypoint, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Save Waypoints', command=self.SaveWaypoints, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Map Waypoints', command=self.MapWaypoints, row=SAME_ROW, col=NEXT_COL)
        self.f1_fname = mainframe.AddLabel('fname')
        self.f1_img1 = mainframe.AddLabelImage()
        self.f1_helmsman_entry.Focus()

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

    def rmsg_wildcard(self, topic, payload):
        self.f1_helmsman_entry.UpdateEntryField(value=payload)

    def rmsg_cameraman_pic_ready(self, payload):
        self.rmsg_cameraman_last(payload)

    def rmsg_cameraman_last(self, payload):
        self.pic_fn = payload['filename']
        self.pic_processed = False
        print("PIC", self.pic_fn)

    def rmsg_navigator_status(self, payload):
        print("NAV STAT", payload)
        self.f1_helmsman_status.set(payload)
        if 'filename' in payload:
            self.pic_fn = payload['filename']
            self.pic_processed = False
            print("NAV FILE", self.pic_fn)

    def ClearWaypoints(self):
        payload = {}
        payload['request'] = 'ClearWaypoints'
        self.Publish('service', payload, source='navigator')

    def MarkWaypoint(self):
        payload = {}
        payload['request'] = 'MarkWaypoint'
        self.Publish('service', payload, source='navigator')

    def SaveWaypoints(self):
        payload = {}
        payload['request'] = 'SaveWaypoints'
        payload['missionName'] = self.mission_name.get()
        self.Publish('service', payload, source='navigator')

    def MapWaypoints(self):
        payload = {}
        payload['request'] = 'MakeWaypointMap'
        payload['missionName'] = self.mission_name.get()
        self.Publish('service', payload, source='navigator')

    def SnapPic(self):
        payload = {}
        payload['loopMode'] = 'run'
        payload['loopFormat'] = 'bgr'
        payload['loopPublish'] = 'stream'
        payload['captureMode'] = 'run'
        payload['captureFormat'] = 'jpeg'
        payload['capturePublish'] = 'file'
        self.Publish('orders', payload, source='cameraman')

    def StartNav(self):
        payload = {}
        payload['loopMode'] = 'run'
        payload['loopFormat'] = 'bgr'
        payload['loopPublish'] = 'stream'
        payload['captureMode'] = 'run'
        payload['captureFormat'] = 'jpeg'
        payload['capturePublish'] = 'file'
        self.Publish('orders', payload, source='cameraman')
        #
        payload = {}
        payload['mode'] = 'G'
        payload['missionName'] = self.mission_name.get()
        self.Publish('mode', payload, source='navigator')
        print("STARTNAV", payload)

    def StopNav(self):
        payload = {}
        payload['captureMode'] = 'none'
        self.Publish('orders', payload, source='cameraman')
        #
        time.sleep(1)
        payload = {}
        payload['speed'] = 0
        self.Publish('orders', payload, source='helmsman')
        #
        payload = {}
        payload['mode'] = 'M'
        payload['missionName'] = self.mission_name.get()
        self.Publish('mode', payload, source='navigator')

    def ProcessImage(self):
        if self.pic_fn is None:
            print("NO PIC AVAILABLE")
            return
        if True:
            start_time = time.time()
            if self.file_client.GetFile(self.pic_fn):
                print("GOT", self.pic_fn, time.time()-start_time)
                path = self.pic_fn
            else:
                print("NOT GOT", self.pic_fn)
                return
        else:
            # This is code to get file file system including AFP)
            path = os.path.join(self.imageDir, self.pic_fn)
        self.f1_img1.UpdateImage(fn=path)
        self.f1_fname.UpdateLabel(self.pic_fn)
        self.pic_fn = None
        self.pic_processed = True
        self.pic_requested = False
        self.pic_last_time = time.time()

    def DoLoop(self):
        #speed = int(self.f1_speed_control.get())
        #self.f1_speed_display.configure(text=str(speed))
        if (time.time() - self.pic_last_time) > 1.0:
            self.ProcessImage()
            #image_info = self.Get('pic_ready', source='cameraman')
            #if image_info is not None:
            #    if 'filename' in image_info:
            #        print("PICPIC", image_info)
            #        self.pic_fn = image_info['filename']
            #        self.ProcessImage()
        #if (self.pic_fn is None) or (self.pic_fn == '') or self.pic_processed:
        #    pass
        #else:
        #    self.ProcessImage()
        #if (not self.pic_requested) or ((time.time() - self.pic_request_time) > 1):
        #    print("ASK LAST")
        #    #self.mqttc.publish('cameraman/ask_last', '')
        #    self.pic_requested = True
        #    self.pic_request_time = time.time()
        self.tk.Update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

m = MissionControl()
m.Loop()
