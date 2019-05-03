
import dev_sense_hat
import datetime
import math
import os
from geopy.distance import great_circle
import pynmea2
import serial
import sys
import time


import vnavs_mqtt as vmqtt
import vnavs_const as vconst
import paho.mqtt.client as mqtt

SEND_ACCELEROMETER_PERIOD = 0.05
SEND_ACCELEROMETER_PERIOD = 0.1			# sense has is far noisier at high read rates
SEND_ACCELEROMETER_PERIOD = 0.3			# sense has is far noisier at high read rates
SEND_ACCELEROMETER_PERIOD = 0.05
METERS_PER_SECOND_PER_KNOT = 0.514444

GPS_BAUD_9600 = 9600
GPS_BAUD_38400 = 38400
GPS_BAUD_RATES = (GPS_BAUD_9600, GPS_BAUD_38400)

DDT_TIME = 'time'
DDT_INT = 'int'
DDT_FLOAT = 'float'
DDT_STR = 'str'

#
# VnavsData provides a mechanism for reliably processing data with a minimum of code.
#
# It provides a centralized data dictionary and editing tools to help avoid
# data interpretation errors when code is developed by multiple people over a
# period of time.
#
class VnavsAttribute(object):
    __slots__ = ('name', 'default_value', 'limit_value', 'max_value', 'min_value', 'type', 'uom', 'values')

    def __init__(self, name, type, uom=None, default_value=None, values=None,
					min_value=None, max_value=None, limit_value=None):
        self.name = name
        self.type = type			# int, float, str, time
        self.uom = uom				# units of measure
        self.default_value = default_value
        self.values = values
        self.min_value = min_value		# value >= min_value
        self.max_value = max_value		# value <= max_value
        self.limit_value = limit_value		# value < limit_value

class VnavsDataDict(object):
    __slots__ = ('attributes')

    def __init__(self):
        self.attributes = {}

    def items(self):
        return self.attributes.items()

    def AddAttribute(self, name, type, uom=None,
						default_value=None, values=None, min_value=None, max_value=None, limit_value=None):
        attribute = VnavsAttribute(name, type=type, uom=None, default_value=default_value, values=values,
						min_value=min_value, max_value=max_value, limit_value=limit_value)
        self.attributes[name] = attribute

    def Slots(self):
        return self.attributes.keys()

class VnavsDataRecord(object):
    __slots__ = ('_dict')
    _dict = None

    def __init__(self, payload=None):
        self.ClearData()			# call even if payload provided to init all
        if payload is not None:
              self.LoadPayload(payload)

    def ClearData(self):
        for key, attribute_def in self._dict.items():
            setattr(self, key, attribute_def.default_value)

    def CreatePayload(self):
        payload = {}
        for attrname, datadef in self._dict.items():
            value = getattr(self, attrname)
            if datadef.type == DDT_TIME:
                if isinstance(value, datetime.datetime):
                    value = value.strftime("%Y%m%d%H%M%S")
            payload[attrname] = value
        return payload

    def LoadPayload(self, payload):
        for this in self.__slots__:
            setattr(self, this, payload[this])

GPS_SPEED = 'gps_speed'
GPS_HEADING = 'gps_heading'
GPS_QUALITY = 'gps_quality'
GPS_LATITUDE = 'gps_latitude'
GPS_LONGITUDE = 'gps_longitude'
GPS_TIMESTAMP = 'gps_timestamp'
GPS_MODE = 'gps_mode'
GPS_DIFFERENTIAL = 'gps_differential'

GpsDataDict = VnavsDataDict()
GpsDataDict.AddAttribute(GPS_MODE, DDT_INT, default_value = 1,
				values={1: 'no fix', 2: '2D < 4 satelites', 3: '3D >= 4 satelites'})
GpsDataDict.AddAttribute(GPS_QUALITY, DDT_STR, default_value='F',
				values={'A': "Best Accuracy", 'B': "Reasonable Accuracy", 'F': 'Not Reliable'})
GpsDataDict.AddAttribute(GPS_LONGITUDE, DDT_FLOAT, default_value = 0,
				min_value=0.0, limit_value=360.0)
GpsDataDict.AddAttribute(GPS_LATITUDE, DDT_FLOAT, default_value = 0,
				min_value=0.0, limit_value=360.0)
GpsDataDict.AddAttribute(GPS_QUALITY, DDT_STR, default_value='F',
				values={'A': "Best Accuracy", 'B': "Reasonable Accuracy", 'F': 'Not Reliable'})
GpsDataDict.AddAttribute(GPS_SPEED, DDT_FLOAT, default_value=0, uom='m/s')
GpsDataDict.AddAttribute(GPS_DIFFERENTIAL, DDT_STR,
				values={'A': "Autonomous", 'D': "Differential GPS"})
GpsDataDict.AddAttribute(GPS_TIMESTAMP, DDT_TIME)

class GpsDataRecord(VnavsDataRecord):
    __slots__ = GpsDataDict.Slots()
    _dict = GpsDataDict

    def Position(self):
        return Position(self.gps_latitude, self.gps_longitude)

IMU_PITCH = 'imu_pitch'
IMU_ROLL = 'imu_roll'
IMU_YAW = 'imu_yaw'
IMU_TIMESTAMP = 'imu_timestamp'

ImuDataDict = VnavsDataDict()
ImuDataDict.AddAttribute(IMU_PITCH, DDT_FLOAT, uom='degrees', default_value = 0,
				min_value=0.0, limit_value=360.0)
ImuDataDict.AddAttribute(IMU_ROLL, DDT_FLOAT, uom='degrees', default_value = 0,
				min_value=0.0, limit_value=360.0)
ImuDataDict.AddAttribute(IMU_YAW, DDT_FLOAT, uom='degrees', default_value = 0,
				min_value=0.0, limit_value=360.0)
ImuDataDict.AddAttribute(IMU_TIMESTAMP, DDT_TIME)

class ImuDataRecord(VnavsDataRecord):
    __slots__ = ImuDataDict.Slots()
    _dict = ImuDataDict

def PositionStringToPosition(position):
    parts = position.split(',')
    Position(float(parts[0]), float(parts[1]))
    return Position

class Position(object):
    __slots__ = ('heading', 'latitude', 'longitude', 'speed')

    def __init__(self, latitude, longitude, heading=None, speed=None):
        self.latitude = latitude		# float, decimal latitude
        self.longitude = longitude		# float, decimal longitude
        self.heading = heading			# float, 0 <= heading < -360, 0 = N, 90 = E (right)
						#			180 = S, 270 = W (left)
        self.speed = speed			# float, m/s

    def __repr__(self):
        if self.heading is None:
            note = ''
        else:
            note = '-> ' + `self.heading`
        if self.speed is not None:
            if note != '':
                note += ' '
            note += '@ ' + `self.speed`
        return '({}, {}, {})'.format(self.latitude, self.longitude, note)

    def DistanceToWaypoint(self, waypoint):
        # Adapted from https://stackoverflow.com/questions/4913349/haversine-formula-in-python-bearing-and-distance-between-two-gps-points
        #
        # calculate haversine(pointA, pointB):
        #
        # convert decimal degrees to radians
        position_latitude_radians, position_longitude_radians, waypoint_latitude_radians, waypoint_longitude_radians = map(
							math.radians, [self.latitude, self.longitude, waypoint.latitude, waypoint.longitude])
        longitude_difference_radians = waypoint_longitude_radians - position_longitude_radians
        latitude_difference_radians = waypoint_latitude_radians - position_latitude_radians
        a = math.sin(latitude_difference_radians/2)**2 \
						+ (math.cos(position_latitude_radians) * math.cos(waypoint_latitude_radians) * math.sin(longitude_difference_radians/2)**2)
        c = 2 * math.asin(math.sqrt(a))
        r = 6371 * 1000				# Radius of earth in meters. Use 3956 for miles
        distance_to_waypoint = c * r

        # calculate heading / bearing

        x = math.sin(longitude_difference_radians) * math.cos(waypoint_latitude_radians)
        y = math.cos(position_latitude_radians) * math.sin(waypoint_latitude_radians) - (math.sin(position_latitude_radians) * math.cos(waypoint_latitude_radians) * math.cos(longitude_difference_radians))

        initial_bearing = math.atan2(x, y)

        # Now we have the initial bearing but math.atan2 return values
        # from -180 to + 180 which is not what we want for a compass bearing
        # The solution is to normalize the initial bearing as shown below
        initial_bearing = math.degrees(initial_bearing)
        heading_to_waypoint = (initial_bearing + 360) % 360

        #print("Position.DistanceToWaypoint()", `self`, `waypoint`, heading_to_waypoint, distance_to_waypoint)

        o = object()
        setattr(o, 'heading_to_waypoint', heading_to_waypoint)			# compass degrees
        setattr(o, 'distance_to_waypoint',  distance_to_waypoint)		# meters - haversine / great circle distance
        return o

class GpsDevice(object):
    def __init__(self):
        self.gps_buffer = ''			# read buffer
        self.next_eol_ix = -1			# index of first <cr><lf>
        self.gps_inited = False
        self.data = GpsDataRecord()
        self.last_sentence_str = None
        self.OpenPort()

    def OpenPort(self, baudrate=GPS_BAUD_9600):
        self.gps_port= serial.Serial(
					port = '/dev/ttyAMA0',
					baudrate = baudrate,
					parity = serial.PARITY_NONE,
					stopbits = serial.STOPBITS_ONE,
					bytesize = serial.EIGHTBITS,
					timeout=SEND_ACCELEROMETER_PERIOD / 10
					)

    def PositionObject(self):
        position = Position(self.data.gps_latitude, self.data.gps_longitude)
        return position

    def PositionString(self):
        position = "{},{}".format(self.data.gps_latitude, self.data.gps_longitude)
        return position

    def Read(self):
        #print("GpsDevice.Read()", self.gps_port.in_waiting)
        if self.next_eol_ix >= 0:
            pass				# process buffered sentence, don't read, risking timeout period
        else:
            self.gps_buffer += self.gps_port.read(size=1024)
            self.next_eol_ix = self.gps_buffer.find('\r\n')
        if self.next_eol_ix < 0:
            last_sentence_str = None
        else:
            self.last_sentence_str = self.gps_buffer[:self.next_eol_ix+2]
            self.gps_buffer = self.gps_buffer[self.next_eol_ix+2:]
            self.next_eol_ix = self.gps_buffer.find('\r\n')
        return self.last_sentence_str

    def DetectBaudrate(self):
        print(GPS_BAUD_RATES)
        for this_baud in GPS_BAUD_RATES:
        #for this_baud in self.gps_port.BAUDRATES:
            print("Trying ", this_baud)
            if self.gps_port.in_waiting >= 1:
                # we have data, so it must be OK now
                print("Data ready", self.gps_port.in_waiting)
                return self.gps_port.baudrate
            self.gps_port.baudrate = this_baud
            time.sleep(2)
            if self.gps_port.in_waiting >= 1:
                # we have data, so it must be OK now
                print("Data ready", self.gps_port.in_waiting)
                return self.gps_port.baudrate

    def IncreaseUpdateRate(self):
        msg_str = "$PMTK251,38400*27" + '\r\n'
        print("SendGpsCommand", `msg_str`)
        self.gps_port.write(msg_str.encode())				# convert to bytes and write
        self.gps_port.baudrate = GPS_BAUD_38400
        #
        msg_str = "$PMTK220,1000*1F" + '\r\n'				# 1 Hz
        msg_str = "$PMTK220,200*2C" + '\r\n'				# 5 Hz
        msg_str = "$PMTK220,100*2F" + '\r\n'				# 10 Hz
        print("SendGpsCommand", `msg_str`)
        self.gps_port.write(msg_str.encode())				# convert to bytes and write

    def SendGpsCommand(self, talker, msgtype, parms):
        ### BROKEN ###
        msg_object = pynmea2.GGA(talker, msgtype, parms)		# this add leading $ and trailing checksum
        msg_str = str(msg_object) + '\c\n'
        msg_str = "$PMTK220,200*2C" + '\r\n'
        print("SendGpsCommand", `msg_str`)
        self.gps_port.write(msg_str.encode())				# convert to bytes and write

    def UpdateGsaSentence(self, parsed_sentence):
        # This might help determine if readings are meaningful
        # https://en.wikipedia.org/wiki/Dilution_of_precision_(navigation)
        # wikipedia numbers seem off. Indoors getting garbage with numbers just over 1.5
        # need to consider mode (prefer D), number ot satelites and dilution.
        # Outdoors, maybe only when moving, some of the dilution numbers dropped below 1.
        cksum_mark = self.last_sentence_str.rfind('*')
        gps_data = self.last_sentence_str[:cksum_mark].split(',')
        mode1 = gps_data[1]		# A(utomatic) or M(anual 2D/3D - s/b A
        mode2 = gps_data[2]		# 1=no fix, 2=2D < 4 satelites, 3=3D >= 4 satelites
        satCt = 0
        for ix in range(3,15):
            if gps_data[ix] != '':
                satCt += 1
        # DOP: Dilution of Precision < 1.0 is ideal but hard to get
        try:
            posDOP = float(gps_data[15])		# position (overall ?)
            horzDOP = float(gps_data[16])		# horizontal
            vertDOP = float(gps_data[17])		# vertical
        except ValueError:
            mode2 = '1'
        if mode2 == '3':
            if (posDOP < 1.0) or (horzDOP < 1.0) or (vertDOP < 1.0):
                self.data.gps_quality = 'A'
            else:
                self.data.gps_quality = 'B'
        elif mode2 == '2':
            self.data.gps_quality = 'C'
        else:
            self.data.gps_quality = 'F'
        self.data.gps_mode = mode2

    def UpdateRmcSentence(self, parsed_sentence):
        speedRaw = parsed_sentence.data[6].strip()
        if speedRaw == '':
            return False		# on my sparkfun sensor, rest is also bad
        self.data.gps_longitude = parsed_sentence.longitude
        self.data.gps_latitude = parsed_sentence.latitude
        try:
            self.data.gps_timestamp = parsed_sentence.datetime
            #self.data.gps_timestamp = 0
        except:
            # this sometimes fails. Maybe just indoors.
            self.data.gps_timestamp = None
        self.data.gps_status = parsed_sentence.data[1]	# A=valid, V=invalid
        speedRaw = parsed_sentence.data[6].strip()
        try:
            speedKnots = float(speedRaw)
            self.data.gps_speed = speedKnots * METERS_PER_SECOND_PER_KNOT
        except ValueError:
            print("Invalid RMC speed", `speedRaw`)
        heading_raw = parsed_sentence.data[7].strip()
        if heading_raw == '':
            pass				# None? only saw it at startup now
        else:
            try:
                self.data.gps_heading = float(heading_raw)	# degrees clockwise from North
            except ValueError:
                print("Invalid RMC heading", `heading_raw`)
        self.gps_differential = parsed_sentence.data[11]	# A=autonomous, D=differeential GPS
        """
        print("RMC %s %s %s %4.7f %s %s %4.7f Hdg %4.2f Quality %s" % (
					self.gps_status, parsed_sentence.data[2], parsed_sentence.data[3], self.latitude,
					parsed_sentence.data[4], parsed_sentence.data[5], self.longitude,
					self.heading, self.gps_quality))
        """
        print("RMC ------")
        return True

    def UpdateGpsInfo(self):
        # Reads one GPS sentence if available and updates position information
        gps_sentence = self.Read()
        if gps_sentence is None:
            return False
        parsed_sentence = None
        try:
            #print("DoLoop()", `gps_sentence`)
            parsed_sentence = pynmea2.parse(gps_sentence)
        except pynmea2.ParseError:
            print("PARSE ERROR")
            parsed_sentence = None
        if parsed_sentence is None:
            return False

        try:
            if parsed_sentence.sentence_type == 'GSA':
                pass
        except AttributeError:
            # This happened after configuring GPS due to returned '$PMTK001,220,2*31\r\n' message.
            # I'm guessing due to the NEMA module not knowing about configuration
            parsed_sentence = None
        if parsed_sentence is None:
            return False

        if parsed_sentence.sentence_type == 'GSA':
            self.UpdateGsaSentence(parsed_sentence)
        elif parsed_sentence.sentence_type == 'RMC':
            rmc = self.UpdateRmcSentence(parsed_sentence)
            return rmc			# True if we have new position info

        return False

class engineer_1(vmqtt.mqtt_node):
    def __init__(self, Verbose=False):
        super().__init__(Subscriptions=[], SingleThreaded=False, BrokerType='F', Streamer=False, Verbose=Verbose)
        self.heading = 0
        self.goal_longitude = None
        self.goal_latitude = None
        self.gps_device = GpsDevice()
        # self.gps_device.IncreaseUpdateRate()
        self.imu_data = ImuDataRecord()
        self.accellerometer = dev_sense_hat.accelerometer()
        self.last_acceleromter_timestamp = time.time()

    def DoLoop(self):
        # executed repetitively by mqtt_node.Loop() which handles exceptions and proper shutdown.
        #

        have_new_gps_data = self.gps_device.UpdateGpsInfo()
        if have_new_gps_data:
            payload = self.gps_device.data.CreatePayload()
            print("Engineeer_1.DoLoop() GPS Payload", payload)
            self.Publish(vconst.engineer_1_gps_topic, payload)
            self.stats.Count('GpsMsg')

        if ((time.time() - self.last_acceleromter_timestamp) > SEND_ACCELEROMETER_PERIOD):
            self.orientation = self.accelerometer.get_orientation_degrees()
            self.imu_data.imu_yaw = self.orientation['yaw']
            self.imu_data.imu_pitch = self.orientation['pitch']
            self.imu_data.imu_roll = self.orientation['roll']
            self.imu_data.imu_timestamp = time.time()
            payload = self.imu_data.CreatePayload()
            self.Publish(vconst.engineer_1_imu_topic, payload)
            self.last_acceleromter_timestamp = time.time()
            self.stats.Count('ImuMsg')
            #print("ACCC %+8.4f %+8.4f GPS: %+8.4f" % (self.acc_speed_forward, self.acc_speed_sideways, self.gps_speed))
            self.stats.Print('MSGS')

def TestImu():
    sense = SenseHat()
    p = sense.get_orientation_degrees()
    while True:
        o = sense.get_orientation_degrees()
        print("IMU P: {:+09.4f}  R: {:+09.4f}  Y: {:+09.4f} {:+09.4f}".format(o['pitch'], o['roll'], o['yaw'], p['yaw']-o['yaw']))
        p = o
        time.sleep(0.1)

def TestSensors():
    sense = SenseHat()
    v = {}
    for s in 'gma':
        for a in 'xyz':
            v[s+a] = [None, None]
    t = time.time()
    prev_time = t
    speed = 0
    max_speed = 0
    #
    while True:
        n = {}
        n['g'] = sense.get_gyroscope_raw()
        n['m'] = sense.get_compass_raw()
        n['a'] = sense.get_accelerometer_raw()
        #
        now = time.time()
        acc_interval = now - prev_time
        prev_time = now
        speed += (n['a']['x'] + 0.062) * acc_interval * 32.0
        if speed > max_speed:
            max_speed = speed
        #
        for s in 'gma':
            d = n[s]
            for a in 'xyz':
                if v[s+a][0] is None:
                    v[s+a][0] = d[a]
                    v[s+a][1] = d[a]
                if d[a] < v[s+a][0]:
                    v[s+a][0] = d[a]
                if d[a] > v[s+a][1]:
                    v[s+a][1] = d[a]
        if (time.time() - t > 5):
            break
    for s in 'gma':
        for a in 'xyz':
            print("%s %s %+8.4f %+8.4f" % (s, a, v[s+a][0], v[s+a][1]))
    print("SPEED", speed, max_speed)

def TestGps():
    gps_device = GpsDevice()
    #gps_device.DetectBaudrate()
    #return
    #gps_device.IncreaseUpdateRate()
    while True:
        have_new_position_data = gps_device.UpdateGpsInfo()
        if gps_device.last_sentence_str is not None:
            print("GPS", gps_device.gps_port.baudrate)
            print("GPS", `gps_device.last_sentence_str`)

def RunNode():
    h = engineer_1()
    h.Loop()
    h.Disconnect()

if __name__ == '__main__':
    if sys.argv[1] == 'node':
        RunNode()
    elif sys.argv[1] == 'testimu':
        TestImu()
    elif sys.argv[1] == 'testsen':
        TestSensors()
    elif sys.argv[1] == 'gps':
        TestGps()
