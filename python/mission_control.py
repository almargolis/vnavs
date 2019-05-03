from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
                      zip, round, input, int, pow, object)

import json
import sys
import os

if sys.argv[1] == 'gui':
    from PIL import ImageTk, Image
    import easytk
    from easytk import SAME_ROW, SAME_COL, NEXT_ROW, NEXT_COL, COL_SPAN_ALL
else:
    ImageTk = None
    Image = None
    easytk = None

import threading
import time

try:
    import numpy
    import cv2
    import OpticChiasm
except ImportError:
    cv2 = None
    numpy = None
    OpticChiasm = None

import engineer_1
import helmsman
import navigator
import vnavs_mqtt as vmqtt
import vnavs_const as vconst
import vnavs_comms as vcomms
import paho.mqtt.client as mqtt

if sys.version_info[0] < 3:
    FileExistsError = OSError

BOT_1_MAP_TRANSPOSE = [

			[ -1.30565584e-01,  -1.56472861e+00,   4.58333935e+02],
			[ -2.57693172e-15,  -3.10871493e+00,   1.04702945e+03],
			[ -2.95275685e-18,  -3.83178162e-03,   1.00000000e+00]
		]

# BOT_1_H = pts_dst = numpy.array(BOT_1_MAP_TRANSPOSE, dtype="float32")

DISPLAY_MODE_LIVE = 'Live'			# working with live information from bot
DISPLAY_MODE_DOWNLOAD = 'Download'		# in process of downloading mission, play as it comes
DISPLAY_MODE_STEP = 'Step'			# manually step through mission
DISPLAY_MODE_REPLAY = 'Replay'			# replay mission, as real-time as possible
DISPLAY_MODES = [DISPLAY_MODE_LIVE, DISPLAY_MODE_DOWNLOAD, DISPLAY_MODE_STEP, DISPLAY_MODE_REPLAY]

TRANSFER_TYPE_NONE = 'N'			# No transfer in progress
TRANSFER_TYPE_IMAGE = 'i'			# Transfering image, display when done
TRANSFER_TYPE_LOG = 'l'				# Transfering mission log, start image download when done

class MissionControl(vmqtt.mqtt_node):
    def __init__(self, Verbose=False):
        #Verbose = True
        super().__init__(Subscriptions=[
                            vmqtt.Subscription(vconst.cameraman_pic_ready_topic, handler=self.DoCameramanPicReady, LatestOnly=True),
                            vmqtt.Subscription(vconst.engineer_1_gps_topic, handler=self.DoEngineer1Gps, LatestOnly=True),
                            vmqtt.Subscription(vconst.engineer_1_imu_topic, handler=self.DoEngineer1Imu, LatestOnly=True),
                            vmqtt.Subscription(vconst.helmsman_orders_topic, handler=self.DoHelmsmanOrders, LatestOnly=True),
                            vmqtt.Subscription(vconst.mission_mark_topic, handler=self.DoMissionMark, LatestOnly=True),
                            vmqtt.Subscription(vconst.mission_init_topic, handler=self.DoMissionInit, LatestOnly=True),
                            vmqtt.Subscription(vconst.mission_loaded_topic, 
							handler=self.DoMissionStatus, handler_needs_topic=True, LatestOnly=True),
                            vmqtt.Subscription(vconst.mission_stage_started_topic, 
							handler=self.DoMissionStatus, handler_needs_topic=True, LatestOnly=True),
                            vmqtt.Subscription(vconst.mission_stage_completed_topic, 
							handler=self.DoMissionStatus, handler_needs_topic=True, LatestOnly=True),
                            vmqtt.Subscription(vconst.navigator_plot_topic, handler=self.DoNavigatorPlot, LatestOnly=True),
                            vmqtt.Subscription(vconst.process_result_topic, handler=self.DoProcessResult, LatestOnly=True)
						],
						BlockIfNotConnected=False, SingleThreaded=True, SelectTimeoutSecs=0.1,
						BrokerType='F',
						Verbose=Verbose)

        self.downloadDir = self.config.get("FileClient", "DownloadDir")
        self.downloadDir = os.path.expanduser(self.downloadDir)               # this expands tilde in path

        self.scriptsDir = self.config.get("MissionControl", "Scripts")
        # The default BuifferLen is 4096 which I settled on at some time in the past while working on FastMqtt.
        # That involved some testing, but not rigorously. I just figured out it was taking 2 seconds to 
        # transfer a 130K image from the bot to mission control. I then changed the buffer on the client end
        # to 150K and transfer time was reduced to acceptably quickly. Image seems real time.
        # The file server is still 4096, so the problem was all in IOS or Mission Control (TK??).
        # If its ever an issue, maybe something between 4096 and 150K would work as well. I just tried
        # this one value and moved on since there doesn't seem to be any downside. 
        self.file_client = vmqtt.FileClient(BufferLen=150000, Verbose=False)

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
        self.speed = 0

        mission_tab = self.notebook.AddTab('Mission')

        nother_frame =_frame = mission_tab.AddFrame(colspan=COL_SPAN_ALL)
        self.mission_stage_entry = nother_frame.AddDropdown(caption='Mode', s_items=DISPLAY_MODES, Selection=DISPLAY_MODE_LIVE,
									row=SAME_ROW, col=NEXT_COL)
        self.mission_id_entry = nother_frame.AddEntryField('Mission ID', width=15, value='')
        self.local_mission_entry = nother_frame.AddDropdown(caption='Local Missions', row=SAME_ROW, col=NEXT_COL)
        nother_frame.AddButton('Replay', command=self.OnReplayLocal, row=SAME_ROW, col=NEXT_COL)
        nother_frame.AddButton('>', command=self.OnReplayLocalFrame, width=1, row=SAME_ROW, col=NEXT_COL)
        nother_frame.AddButton('<', command=self.OnReplayLocalBack, width=1, row=SAME_ROW, col=NEXT_COL)
        self.bot_mission_entry = nother_frame.AddDropdown(caption='Bot Missions', row=SAME_ROW, col=NEXT_COL)
        nother_frame.AddButton('Download', command=self.OnReplayDownload, row=SAME_ROW, col=NEXT_COL)

        mission_frame = mission_tab.AddFrame(colspan=COL_SPAN_ALL)
        self.mission_name_entry = mission_frame.AddEntryField('Mission', width=15, value='table')
        mission_frame.AddButton('Load', command=self.OnMissionLoad, row=SAME_ROW, col=NEXT_COL)
        self.mission_stage_entry = mission_frame.AddDropdown(caption='Stage', row=SAME_ROW, col=NEXT_COL)
        mission_frame.AddButton('Execute', command=self.OnStageExecute, row=SAME_ROW, col=NEXT_COL)
        self.mission_status = mission_frame.AddLabel('Ready', row=SAME_ROW, col=NEXT_COL)

        buttonframe = mission_tab.AddFrame(colspan=COL_SPAN_ALL)
        buttonframe.AddButton('Cancel', command=self.OnCancelMission, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('+', command=self.OnSpeedPlus, width=1, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('-', command=self.OnSpeedMinus, width=1, row=SAME_ROW, col=NEXT_COL)
        buttonframe.AddButton('Stop', command=self.OnSpeedStop, row=SAME_ROW, col=NEXT_COL)
        #buttonframe.AddButton('Clear Waypoints', command=self.ClearWaypoints, row=SAME_ROW, col=NEXT_COL)
        #buttonframe.AddButton('Mark Waypoint', command=self.MarkWaypoint, row=SAME_ROW, col=NEXT_COL)
        #buttonframe.AddButton('Save Waypoints', command=self.SaveWaypoints, row=SAME_ROW, col=NEXT_COL)
        #buttonframe.AddButton('Map Waypoints', command=self.MapWaypoints, row=SAME_ROW, col=NEXT_COL)
        mission_frame = mission_tab.AddFrame(colspan=COL_SPAN_ALL)
        mission_image_frame = mission_frame.AddFrame()
        mission_info_frame = mission_frame.AddFrame(row=SAME_ROW, col=NEXT_COL)
        #
        image_info_frame = mission_image_frame.AddFrame()
        self.f1_fname = image_info_frame.AddLabel('fname')
        self.f1_fps = image_info_frame.AddLabel('fps', row=SAME_ROW, col=NEXT_COL)
        self.f1_img1 = mission_image_frame.AddLabelImage()
        #
        self.gps_position = mission_info_frame.AddLabelInfo('GPS Position:')
        self.gps_speed = mission_info_frame.AddLabelInfo('GPS Speed:')
        self.imu_heading = mission_info_frame.AddLabelInfo('IMU Heading:')
        self.waypoint_position = mission_info_frame.AddLabelInfo('Waypoint Position:')
        self.waypoint_heading = mission_info_frame.AddLabelInfo('Waypoint Heading:')
        self.waypoint_distance = mission_info_frame.AddLabelInfo('Waypoint Distance:')
        self.helmsman_speed = mission_info_frame.AddLabelInfo('Helmsman Speed:')
        self.helmsman_steer = mission_info_frame.AddLabelInfo('Helmsman Steering:')
        self.helmsman_p_error = mission_info_frame.AddLabelInfo('Helmsman P_Error:')
        self.helmsman_i_accumulator = mission_info_frame.AddLabelInfo('Helmsman I_Accumulator:')
        self.helmsman_derivative = mission_info_frame.AddLabelInfo('Helmsman Derivative:')

        self.message_tab = self.notebook.AddTab('Message')
        self.mt_file_name = self.message_tab.AddEntryField('Script File', width=25)
        self.message_tab.AddButton('Open', command=self.OpenScriptFile, row=SAME_ROW, col=NEXT_COL)
        self.mt_script = self.message_tab.AddScrolledEntryField('Script', width=25, height=5, row=NEXT_ROW, col=NEXT_COL)
        self.message_tab.AddButton('Send Message', command=self.SendMessage, row=NEXT_ROW, col=NEXT_COL)

        self.alert_tab = self.notebook.AddTab('Alerts')
        #self.alert_text = self.alert_tab.AddScrolledEntryField('Script', width=25, height=5, row=NEXT_ROW, col=NEXT_COL)
        self.alert_text = self.alert_tab.AddTable('Script', width=400, height=200, row=NEXT_ROW, col=NEXT_COL)

        self.pic_fn = None
        self.pic_path = None
        self.pic_payload = None
        self.pic_next_payload = None
        self.line_rect = None

        self.display_mode = DISPLAY_MODE_LIVE
        self.transfer_type = TRANSFER_TYPE_NONE
        self.mission = None
        self.mission_id = None

        self.replay_mission_id = None
        self.replay_log_fn = None
        self.replay_log_path = None
        self.replay_mission_dir = None
        self.replay_log_fn = None
        self.replay_log_transfer_wanted = False
        self.replay_log_lines = None
        self.replay_log_payloads = None
        self.replay_frames = -1				# ct of frames to replay, -1 is continuous
        self.UpdateLocalMissionList()

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

    def filter_payload(self, payload):
        new_payload = {}
        for (k, v) in payload.items():
            if k[0] == '_':
                continue
            new_payload[k] = v
        return new_payload

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

    def OnMissionLoad(self):
        # This loads mission here and sends it to navigator.
        # This is an error checking step. It does not execute mission.
        # This needs to be enhanced to do and display mission syntax checking.
        mission_name = self.mission_name_entry.Value()
        fp = mission_name + '.mis'
        f = open(fp, 'r')
        mission_script = f.read()
        f.close()
        self.mission = navigator.Mission(name=mission_name, script=mission_script.split('\n'))
        if len(self.mission.stages_list) > 0:
            self.mission.stages_list.sort()
            self.mission_stage_entry.ReplaceChoices(self.mission.stages_list)
            self.mission_stage_entry.ReplaceValue(self.mission.stages_list[0])
        else:
            self.mission_stage_entry.ReplaceChoices(['None'])
        payload = {}
        payload['mission_name'] = mission_name
        payload['mission_script'] = mission_script
        self.Publish(vconst.mission_load_topic, payload)
        print("STARTNAV", payload)

    def OnReplayLocal(self):
        self.replay_mission_id = self.local_mission_entry.Value()
        self.ConfigureReplay(Mkdir=False)
        self.OpenReplayLog()
        self.display_mode = DISPLAY_MODE_REPLAY
        self.replay_frames = -1

    def OnReplayLocalBack(self):
        # Most of the time, when we get here we have been in single step
        # mode, with self.replay_log_ix pointing to data following the
        # frame currently being displayed. Since data can arrive
        # sporadically, its hard to know what data to display.
        # for the best odds of displaying correct data without too much
        # complexity, we will step back to all data following the image
        # before the one we want to see.
        # So we step back two images (the one currently shown and the one
        # we want to see, plus the data just before the image we want to see.
        image_skip_ct = 3  
        while self.replay_log_ix > 0:
            self.replay_log_ix -= 1
            payload = self.replay_log_payloads[self.replay_log_ix]
            topic = payload['_topic']
            if topic == vconst.cameraman_pic_ready_topic:
                image_skip_ct -= 1
                if image_skip_ct <= 0:
                    # at image before the one we want, point to the next data record and get out
                    self.replay_log_ix += 1
                    break
        self.replay_frames = 1

    def OnReplayLocalFrame(self):
        self.replay_frames = 1

    def OnReplayDownload(self):
        self.replay_log_transfer_wanted = True
        log_file_name = self.bot_mission_entry.Value()
        dot = log_file_name.rfind('.')
        self.replay_mission_id = log_file_name[:dot]
        print("OnReplayDownload()", self.replay_mission_id)

    def OnSpeedStop(self):
        self.speed = 0
        payload = {}
        payload[helmsman.HELMSMAN_SPEED] = self.speed
        self.Publish(vconst.helmsman_orders_topic, payload)

    def OnSpeedPlus(self):
        self.speed += 1
        payload = {}
        payload[helmsman.HELMSMAN_SPEED] = self.speed
        self.Publish(vconst.helmsman_orders_topic, payload)

    def OnSpeedMinus(self):
        self.speed -= 1
        if self.speed < 0:
            self.speed = 0
        payload = {}
        payload[helmsman.HELMSMAN_SPEED] = self.speed
        self.Publish(vconst.helmsman_orders_topic, payload)

    def OnStageExecute(self):
        this_stage = self.mission_stage_entry.Value()
        payload = {}
        payload['mission_name'] = self.mission.mission_name
        payload['mission_stage'] = this_stage
        self.Publish(vconst.mission_sync_event_topic, payload)
        next_stage_ix = self.mission.stages_list.index(this_stage) + 1
        if next_stage_ix < len(self.mission.stages_list):
            self.mission_stage_entry.ReplaceValue(self.mission.stages_list[next_stage_ix])

    def OnCancelMission(self):
        print("OnCancelMission()")
        self.Publish(vconst.process_log_list_topic, {})
        payload = {}
        payload['mission_name'] = self.mission_name_entry.Value()
        self.Publish(vconst.mission_cancel_topic, payload)
        #
        payload = {}
        payload[helmsman.HELMSMAN_SPEED] = 0
        self.Publish(vconst.helmsman_orders_topic, payload)


    #
    # Message Handlers
    #

    def DoCameramanPicReady(self, payload, Replay=False):
        if (self.display_mode != DISPLAY_MODE_LIVE) and (not Replay):
            return
        self.pic_next_payload = payload			# always remember latest available image

    def DoEngineer1Gps(self, payload, Replay=False):
        if (self.display_mode != DISPLAY_MODE_LIVE) and (not Replay):
            return
        self.gps_speed.ReplaceValue(payload[engineer_1.GPS_SPEED])
        latitude = None
        longitude = None
        if engineer_1.GPS_LATITUDE in payload:
            latitude = payload[engineer_1.GPS_LATITUDE]
        if engineer_1.GPS_LONGITUDE in payload:
            longitude = payload[engineer_1.GPS_LONGITUDE]
        if (latitude is not None) and (longitude is not None):
            position = "{},{}".format(latitude, longitude)
            self.gps_position.ReplaceValue(position)

    def DoEngineer1Imu(self, payload, Replay=False):
        if (self.display_mode != DISPLAY_MODE_LIVE) and (not Replay):
            return
        self.imu_heading.ReplaceValue(payload[engineer_1.IMU_YAW])

    def DoMissionInit(self, payload, Replay=False):
        print("mission/init", Replay, payload)
        if (self.display_mode != DISPLAY_MODE_LIVE) and (not Replay):
            return
        self.mission_id = payload['mission_id']
        self.mission_id_entry.ReplaceValue(self.mission_id)
        print("DoMissionInit()", self.mission_id, payload)

    def DoMissionMark(self, payload, Replay=False):
        print("mission/mark", Replay, payload)
        if (self.display_mode != DISPLAY_MODE_LIVE) and (not Replay):
            return
        self.line_rect = OpticChiasm.RectFromPayload(payload)
        print("DoMissionMark()", self.line_rect, payload)

    def DoMissionStatus(self, topic, payload, Replay=False):
        print("DoMissionStatus()", Replay, payload)
        if (self.display_mode != DISPLAY_MODE_LIVE) and (not Replay):
            return
        if not 'mission_id' in payload:
            payload['mission_id'] = 'XXX'	# normal for mission/loaded, else an error
        if not 'mission_stage' in payload:
            payload['mission_stage'] = 'XXX'	# normal for mission/loaded, else an error
        status = "{mission_id} {mission_stage} {_topic}".format(**payload)
        self.mission_status.ReplaceValue(status)

    def DoNavigatorPlot(self, payload, Replay=False):
        if (self.display_mode != DISPLAY_MODE_LIVE) and (not Replay):
            return
        self.waypoint_heading.ReplaceValue(payload[navigator.NAVIGATOR_WAYPOINT_HEADING])
        self.waypoint_distance.ReplaceValue(payload[navigator.NAVIGATOR_WAYPOINT_DISTANCE])
        latitude = None
        longitude = None
        if navigator.NAVIGATOR_WAYPOINT_LATITUDE in payload:
            latitude = payload[navigator.NAVIGATOR_WAYPOINT_LATITUDE]
        if navigator.NAVIGATOR_WAYPOINT_LONGITUDE in payload:
            longitude = payload[navigator.NAVIGATOR_WAYPOINT_LONGITUDE]
        if (latitude is not None) and (longitude is not None):
            position = "{},{}".format(latitude, longitude)
            self.waypoint_position.ReplaceValue(position)

    def DoProcessResult(self, payload, Replay=False):
        if (self.display_mode != DISPLAY_MODE_LIVE) and (not Replay):
            return
        log_list = payload['log_list']
        log_list.sort()
        self.bot_mission_entry.ReplaceChoices(log_list)

    def DoHelmsmanOrders(self, payload, Replay=False):
        if (self.display_mode != DISPLAY_MODE_LIVE) and (not Replay):
            return
        if helmsman.HELMSMAN_SPEED in payload:
            speed = payload[helmsman.HELMSMAN_SPEED]
            self.helmsman_speed.ReplaceValue(speed)
        if helmsman.HELMSMAN_HEADING in payload:
            steer = payload[helmsman.HELMSMAN_HEADING]
            self.helmsman_steer.ReplaceValue(steer)
        if helmsman.HELMSMAN_P_ERROR in payload:
            p_error = payload[helmsman.HELMSMAN_P_ERROR]
            self.helmsman_p_error.ReplaceValue(p_error)
        if helmsman.HELMSMAN_I_ACCUMULATOR in payload:
            i_accumulator = payload[helmsman.HELMSMAN_I_ACCUMULATOR]
            self.helmsman_i_accumulator.ReplaceValue(i_accumulator)
        if helmsman.HELMSMAN_DERIVATIVE in payload:
            derivative = payload[helmsman.HELMSMAN_DERIVATIVE]
            self.helmsman_derivative.ReplaceValue(derivative)

    #
    # DoLoop() and closely related
    #

    def ProcessImage(self):
        im = OpticChiasm.Image(opencv_fn=self.pic_path)
        if 'center_line' in self.pic_payload:
            line_at = self.pic_payload['center_line']
            list_of_OpenCvRect = OpticChiasm.ListOfOpenCvRectFromListofDicts(line_at)
            #print("ProcessImage() center_line ", list_of_OpenCvRect)
            im.DrawLinePoints(list_of_OpenCvRect)
        if self.line_rect is not None:
            cv2.line(im._im, self.line_rect.p1, self.line_rect.p2, OpticChiasm.DRAW_BGR_BLACK, 5)
            ctr = self.line_rect.center
            fwd = (ctr[0], ctr[1]-10)
            cv2.line(im._im, ctr, fwd, OpticChiasm.DRAW_BGR_WHITE, 5)
        self.f1_img1.UpdateImage(source_im=im.im)
        self.f1_fname.ReplaceValue(self.pic_fn)
        self.f1_fps.ReplaceValue('{} fps'.format(self.pic_payload['capture_fps']))

    def ConfigureImageLocation(self, payload, image_dir, TransferNeeded=True):
        if TransferNeeded:
            self.transfer_type = TRANSFER_TYPE_IMAGE
        self.pic_fn = payload['filename']
        self.pic_path = os.path.join(image_dir, self.pic_fn)
        self.pic_payload = payload
        print("ConfigureImageLocation()", self.pic_fn, self.pic_path, TransferNeeded)

    def UpdateLocalMissionList(self):
        mission_id_list = []
        dlist = os.listdir(self.downloadDir)
        for this in dlist:
            # look for download subdirectories with corresponding log file
            dpath = os.path.join(self.downloadDir, this)
            if os.path.isdir(dpath):
                log_path = os.path.join(dpath, this+vcomms.FMQTT_LOG_EXTENSION)
                if os.path.isfile(log_path):
                    mission_id_list.append(this)
        mission_id_list.sort()
        self.local_mission_entry.ReplaceChoices(mission_id_list)

    def ConfigureReplay(self, Mkdir=True):
        self.replay_log_fn = self.replay_mission_id + '.nav'
        self.replay_mission_dir = os.path.join(self.downloadDir, self.replay_mission_id)
        if Mkdir:
            try:
                os.mkdir(self.replay_mission_dir)
            except FileExistsError:
                pass
        self.replay_log_path = os.path.join(self.replay_mission_dir, self.replay_log_fn)

    def OpenReplayLog(self):
        f = open(self.replay_log_path, 'r')
        d = f.read()
        f.close()
        self.replay_log_lines = d.split(chr(1))
        self.replay_log_payloads = []
        for this in self.replay_log_lines:
            if this != '':
                parts = this.split(chr(0))
                payload = json.loads(parts[2])
                self.replay_log_payloads.append(payload)
        self.replay_log_ix = 0
        self.mission_status.ReplaceValue("{} {} {} LOADED".format(self.replay_log_fn, len(d), len(self.replay_log_lines)))
        
    def DoLoop(self):
        #print("DoLoop()")
        if self.transfer_type != TRANSFER_TYPE_NONE:
            # Checking the transfer reports completion and does some transfering if not complete
            if self.file_client.CheckTransfer():
                # Transfer is complete
                #print("DoLoop() Transfer Complete", self.transfer_type)
                if self.transfer_type == TRANSFER_TYPE_LOG:
                    self.OpenReplayLog()
                    self.display_mode = DISPLAY_MODE_DOWNLOAD
                else:				# TRANSFER_TYPE_IMAGE
                    self.ProcessImage()
                self.transfer_type = TRANSFER_TYPE_NONE
        self.HandleAllSynchronousPayloads()
        if self.transfer_type == TRANSFER_TYPE_NONE:
            # No transfer in progress, see if one is ready to start
            if self.replay_log_transfer_wanted:
                self.transfer_type = TRANSFER_TYPE_LOG
                self.replay_log_transfer_wanted = False
                self.ConfigureReplay()
                transfer_fn = self.replay_log_fn
                transfer_path = self.replay_log_path
            elif self.display_mode in [DISPLAY_MODE_DOWNLOAD, DISPLAY_MODE_REPLAY]:
                while self.replay_log_ix < len(self.replay_log_payloads):
                    payload = self.replay_log_payloads[self.replay_log_ix]
                    topic = payload['_topic']
                    if self.replay_frames == 0:
                        # In single frame mode, don't advance past next image till clicked again.
                        # But we do display non-images up to next frame so we see navigation
                        # decisions. There probably needs to be a few modes of single frame.
                        # Maybe a separate tab that shows all messages individually.
                        if topic == vconst.cameraman_pic_ready_topic:
                            break
                    self.replay_log_ix += 1
                    if topic == vconst.cameraman_pic_ready_topic:
                        if self.display_mode ==DISPLAY_MODE_DOWNLOAD:
                            self.ConfigureImageLocation(payload, self.replay_mission_dir)
                        else:
                            self.ConfigureImageLocation(payload, self.replay_mission_dir, TransferNeeded=False)
                            self.ProcessImage()
                        if self.replay_frames > 0:
                            self.replay_frames -= 1
                        break
                    elif topic in self.subscriptions:
                        sub = self.subscriptions[topic]
                        if sub.handler_needs_topic:
                            sub.handler_method(topic, payload, Replay=True)
                        else:
                            sub.handler_method(payload, Replay=True)
                        break 
            elif self.pic_next_payload is not None:
                self.ConfigureImageLocation(self.pic_next_payload, self.downloadDir)
                self.pic_next_payload = None
            if self.transfer_type != TRANSFER_TYPE_NONE:
                if self.transfer_type == TRANSFER_TYPE_IMAGE:
                    transfer_fn = self.pic_fn
                    transfer_path = self.pic_path
                self.file_client.StartTransfer(self.transfer_type, transfer_fn, path=transfer_path)
                print("DoLoop() Start Transfer", self.transfer_type, transfer_fn)
        self.tk.Update()
        # when tk is destroyed by close window, self.Disconnect()	# stop mqtt client loop

def RunGps(waypoint):
    gps_device = engineer_1.GpsDevice()
    #gps_device.DetectBaudrate()
    #return
    #gps_device.IncreaseUpdateRate()
    start_position = None
    if waypoint is not None:
        print("RunGps() requesting waypoint", waypoint)
        payload = {}
        payload['key'] = waypoint
        value_payload = vmqtt.Publish(vconst.data_get_topic, payload, ResponseTopic='data/value')
        value = value_payload['value']
        start_position = engineer_1.PositionStringToPosition(value)
    while start_position is None:
        have_new_position_data = gps_device.UpdateGpsInfo()
        if have_new_position_data:
            start_position = gps_device.PositionObject()
    print("Start", start_position)

    while True:
        have_new_position_data = gps_device.UpdateGpsInfo()
        if have_new_position_data:
            new_position = gps_device.PositionObject()
            d = start_position.DistanceToWaypoint(new_position)
            print("Distance:", d.distance_to_waypoint, "Heading:", d.heading_to_waypoint,
			"Speed:", gps_device.data.gps_speed, "Quality:", gps_device.data.gps_quality)

def LocateGps():
    stop_time = None
    location_name = None
    if len(sys.argv) > 2:
        stop_time = time.time() + (int(sys.argv[2]) * 60)			# survey for this many minutes
    if len(sys.argv) > 3:
        location_name = sys.argv[3]
    data = navigator.PersistentData()
    survey_map = navigator.MissionMap()
    survey_map.InitSurvey()
    gps_samples = []
    previous_position = None
    previous_center_position = None
    distance_from_previous_center = 0.0
    distance_from_last_position = 0.0
    gps_device = engineer_1.GpsDevice()
    while True:
        if (stop_time is not None) and (stop_time <= time.time()):
            break
        have_new_position_data = gps_device.UpdateGpsInfo()
        if have_new_position_data:
            new_position = gps_device.PositionObject()
            gps_samples.append(new_position)
            survey_map.AppendSurveyPosition(new_position)
            center_position = engineer_1.find_center_of_gps_samples(gps_samples)
            if previous_center_position is not None:
                dw = center_position.DistanceToWaypoint(previous_center_position)
                distance_from_previous_center = dw.distance_to_waypoint
            if previous_position is not None:
                dw = new_position.DistanceToWaypoint(previous_position)
                distance_from_last_position = dw.distance_to_waypoint
            previous_center_position = center_position
            previous_position = new_position
            print("CENTER:", center_position.DMS(), distance_from_previous_center, survey_map.survey_hypotenuse,
			"LOCATION:", distance_from_last_position, new_position.DMS())
    if location_name is not None:
        data.Put(location_name, c)

def DistanceGps():
    data = navigator.PersistentData()
    goal_name = sys.argv[2]
    if len(sys.argv) > 3:
        start_name = sys.argv[3]
    else:
        start_name = None
    goal_location = data.Get(goal_name)
    goal_position = engineer_1.Position(latitude=goal_location['latitude'], longitude=goal_location['longitude'])
    gps_device = engineer_1.GpsDevice()
    if start_name is not None:
        start_location = data.Get(start_name)
        start_position = engineer_1.Position(latitude=start_location['latitude'], longitude=start_location['longitude'])
        gps_device.StartRelativeGpsPositioning(start_position)
    while True:
        have_new_position_data = gps_device.UpdateGpsInfo()
        if have_new_position_data:
            new_position = gps_device.PositionObject()
            dw = new_position.DistanceToWaypoint(goal_position)
            print(dw.distance_to_waypoint)

def SaveGps(waypoint):
    gps_device = engineer_1.GpsDevice()
    gps_readings = []
    while len(gps_readings) < 1:
        have_new_position_data = gps_device.UpdateGpsInfo()
        if have_new_position_data:
            this_position = gps_device.PositionString()
            gps_readings.append(this_position)
            payload = {}
            payload['key'] = waypoint
            payload['value'] = this_position
            vmqtt.Publish(vconst.data_save_topic, payload)

if __name__ == '__main__':
    if sys.argv[1] == 'gui':
        vmqtt.LaunchNode(MissionControl)
    elif sys.argv[1] == 'gps':
        if len(sys.argv) > 2:
            waypoint = sys.argv[2]
        else:
            waypoint = None
        RunGps(waypoint)
    elif sys.argv[1] == 'loc':
        LocateGps()
    elif sys.argv[1] == 'dist':
        DistanceGps()
    elif sys.argv[1] == 'save':
        waypoint = sys.argv[2]
        SaveGps(waypoint)
