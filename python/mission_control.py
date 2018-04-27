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
import engineer_1
import OpticChiasm
import vnavs_mqtt
import vnavs_const as vconst
import paho.mqtt.client as mqtt

BOT_1_MAP_TRANSPOSE = [

			[ -1.30565584e-01,  -1.56472861e+00,   4.58333935e+02],
			[ -2.57693172e-15,  -3.10871493e+00,   1.04702945e+03],
			[ -2.95275685e-18,  -3.83178162e-03,   1.00000000e+00]
		]

BOT_1_H = pts_dst = numpy.array(BOT_1_MAP_TRANSPOSE, dtype="float32")

class MissionControl(vnavs_mqtt.mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=[
                        vconst.cameraman_pic_ready_topic,
						vconst.engineer_1_gps_topic,
						vconst.engineer_1_imu_topic,
						vconst.helmsman_orders_topic,
						'MissionControl/notice',      # this doesn't work - fix wildcard too - crash - ack, etc
						vconst.navigator_service_ack_topic
						],
						SingleThreaded=True, SelectTimeoutSecs=0.1,
						BrokerType='F',
						Verbose=Verbose)
        self.scriptsDir = self.config.get("MissionControl", "Scripts")
        self.file_client = vnavs_mqtt.FileClient(Verbose=False)

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
        self.image.img_source_dir = '/volumes/pi/projects/vnavs/temp'
        self.image.img_fname_suffix = ''
        self.image.do_save_snaps = False
        self.pic_fn = None
        self.pic_last_time = time.time()
        self.pic_processed = False
        self.pic_requested = False
        self.pic_request_time = 0
        self.pic_get = True
        if vnavs_mqtt.ARG_IMAGE_GET in self.args:
            self.pic_get = self.args[vnavs_mqtt.ARG_IMAGE_GET]

        mission_tab = self.notebook.AddTab('Mission')
        self.f1_helmsman_entry = mission_tab.AddEntryField('Helmsman', width=75)
        self.f1_engineer_1_entry = mission_tab.AddEntryField('Engineer_1', width=75)
        self.mission_name_entry = mission_tab.AddEntryField('Mission', width=15, value='test')
        buttonframe = mission_tab.AddFrame(colspan=COL_SPAN_ALL)
        buttonframe.AddButton('Start', command=self.StartMission, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Cancel', command=self.CancelMission, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Snap', command=self.SnapPic, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Clear Waypoints', command=self.ClearWaypoints, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Mark Waypoint', command=self.MarkWaypoint, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Save Waypoints', command=self.SaveWaypoints, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Map Waypoints', command=self.MapWaypoints, row=SAME_ROW, col=NEXT_COL)
        self.f1_fname = mission_tab.AddLabel('fname')
        self.f1_img1 = mission_tab.AddLabelImage()

        self.message_tab = self.notebook.AddTab('Message')
        self.mt_file_name = self.message_tab.AddEntryField('Script File', width=25)
        self.message_tab.AddButton('Open', command=self.OpenScriptFile, row=SAME_ROW, col=NEXT_COL)
        self.mt_script = self.message_tab.AddScrolledEntryField('Script', width=25, height=5, row=NEXT_ROW, col=NEXT_COL)
        self.message_tab.AddButton('Send Message', command=self.SendMessage, row=NEXT_ROW, col=NEXT_COL)

        self.alert_tab = self.notebook.AddTab('Alerts')
        self.alert_text = self.alert_tab.AddScrolledEntryField('Script', width=25, height=5, row=NEXT_ROW, col=NEXT_COL)

        self.f1_helmsman_entry.Focus()

    def OpenScriptFile(self):
        fn = self.message_tab.DoFileNameDialog(Dir=self.scriptsDir)
        self.mt_file_name.ReplaceValue(fn)
        s_f = open(fn, "r")
        s = s_f.read()
        s_f.close()
        self.mt_script.ReplaceValue(s)

    def SendMessage(self):
        s = self.mt_script.Value()
        lines = s.split('\n')
        contents = {}
        for this in lines:
            if this == '':
                continue
            if this[0] == '[':
                sec = this[1:-1]
                sec_data = {}
                contents[sec] = sec_data
            else:
                pos = this.find('=')
                fname = this[:pos]
                data = this[pos+1:]
                sec_data[fname] = data
        print(contents)
        topic = contents['Head']['Topic']
        self.Publish(topic, contents['Payload'])

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
        self.f1_engineer_1_entry.ReplaceValue(payload)
        if topic[-5:] == 'abend':
          t = payload['traceback']
          self.alert_text.ReplaceValue(t)

    def rmsg_cameraman_pic_ready(self, payload):
        if 'annotated' in payload:
            self.pic_fn = payload['annotated']
        else:
            self.pic_fn = payload['filename']
        self.pic_processed = False

    def filter_payload(self, payload):
        new_payload = {}
        for (k, v) in payload.items():
            if k[0] == '_':
                continue
            new_payload[k] = v
        return new_payload

    def rmsg_helmsman_orders(self, payload):
        self.f1_helmsman_entry.ReplaceValue(self.filter_payload(payload))

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
        self.Publish(vconst.navigator_service_topic, payload)

    def MarkWaypoint(self):
        payload = {}
        payload['request'] = 'MarkWaypoint'
        self.Publish(vconst.navigator_service_topic, payload)

    def SaveWaypoints(self):
        payload = {}
        payload['request'] = 'SaveWaypoints'
        payload['missionName'] = self.mission_name.get()
        self.Publish(vconst.navigator_service_topic, payload)

    def MapWaypoints(self):
        payload = {}
        payload['request'] = 'MakeWaypointMap'
        payload['missionName'] = self.mission_name.get()
        self.Publish(vconst.navigator_service_topic, payload)

    def SnapPic(self):
        payload = {}
        payload['loop_mode'] = 'run'
        payload['loop_format'] = 'bgr'
        payload['loop_publish'] = 'stream'
        payload['capture_mode'] = 'run'
        payload['capture_format'] = 'jpeg'
        payload['capture_publish'] = 'file'
        self.Publish(vconst.cameraman_orders_topic, payload)

    def StartMission(self):
        mission_name = self.mission_name_entry.Value()
        fp = mission_name + '.mis'
        f = open(fp, 'r')
        mission_script = f.read()
        f.close()
        payload = {}
        payload['mission_name'] = mission_name
        payload['mission_script'] = mission_script
        self.Publish(vconst.mission_begin_topic, payload)
        print("STARTNAV", payload)

    def CancelMission(self):
        payload = {}
        payload['mission_name'] = self.mission_name_entry.Value()
        self.Publish(vconst.mission_cancel_topic, payload)
        #
        payload = {}
        payload['speed'] = 0
        self.Publish(vconst.helmsman_orders_topic, payload)

    def ProcessImage(self):
        if self.pic_fn is None:
            print("NO PIC AVAILABLE")
            return
        path = os.path.join(self.imageDir, self.pic_fn)
        print("ProcessImage()", self.pic_fn, path)
        if self.pic_get:
            if not self.file_client.GetFile(self.pic_fn, path=path):
                print("Unable to fetch PIC", self.pic_fn)
                return
        self.f1_img1.UpdateImage(opencv_fn=path)
        self.f1_fname.ReplaceValue(self.pic_fn)
        self.pic_fn = None
        self.pic_processed = True
        self.pic_requested = False
        self.pic_last_time = time.time()

    def DoLoop(self):
        #speed = int(self.f1_speed_control.get())
        #self.f1_speed_display.configure(text=str(speed))
        if (time.time() - self.pic_last_time) > 1.0:
            self.ProcessImage()
        self.tk.Update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

def RunGps():
    gps_device = engineer_1.GpsDevice()
    #gps_device.DetectBaudrate()
    #return
    #gps_device.IncreaseUpdateRate()
    start_position = None
    while start_position is None:
        have_new_position_data = gps_device.UpdateGpsInfo()
        if have_new_position_data:
            start_position = (gps_device.latitude, gps_device.longitude)
            print("Start", start_position)

    while True:
        have_new_position_data = gps_device.UpdateGpsInfo()
        if have_new_position_data:
            new_position = (gps_device.latitude, gps_device.longitude)
            d = navigation.DistanceToWaypoint(start_position, new_position)
            print("Distance", d.distance_to_waypoint, "Heading:", d.heading_to_waypoint)

if __name__ == '__main__':
    if sys.argv[1] == 'gui':
        vnavs_mqtt.LaunchNode(MissionControl)
    elif sys.argv[1] == 'gps':
        RunGps()
