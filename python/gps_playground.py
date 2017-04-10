import serial
import pynmea2
from geopy.geocoders import Nominatim
from geopy.distance import great_circle

def PrintMovement(p1, p):
    # p.data[5] is method, p.data[6] is number of satelites used
    p2 = (p.latitude, p.longitude)
    print(great_circle(p1, p2).meters, p.data[5], p.data[6])

def PrintPathHome(p1, p):
    # should be reworked using GeographicLib
    curLat = p.latitude
    curLong = p.longitude
    hypotenuse = great_circle((curLat, curLong), p1).meters
    deltaY = great_circle((curLat, curLong), (p1[0], curLong)).meters
    deltaX = great_circle((curLat, curLong), (curLat, p1[1])).meters
    if deltaX != 0:
        slope = deltaY / deltaX
    else:
        slope = 999
    print("Path", round(deltaX, 2), round(deltaY, 2), round(slope, 2), round(hypotenuse, 2), p.data[1])

def FindAddress(latitude, longitude):
    geolocator = Nominatim()
    location = geolocator.reverse((latitude, longitude))
    print(location.address)
    print((location.latitude, location.longitude))
    print(location.raw)

def set_up_gps():
     ser = serial.Serial(
        port = '/dev/ttyAMA0',
        baudrate = 9600,
        parity = serial.PARITY_NONE,
        stopbits = serial.STOPBITS_ONE,
        bytesize = serial.EIGHTBITS,
        timeout=1
        )
     counter=0
     return ser

def ListParsedFields(p):
  for ix, fld in enumerate(p.fields):
      print ix, fld[0], " -- ", fld[1], " -- ", p.data[ix]
  try:
      print "Longitude", p.longitude
      print "Latitude", p.latitude
  except:
      print "No LAT/LONG"
  try:
      print "Date", p.datetime
  except:
      print "No DATE"


s = set_up_gps()
p1 = None
loop_ct = 0
loop_limit = 100
loop_limit = None
while True:
    loop_ct += 1
    if loop_limit is not None:
       if loop_ct > loop_limit:
           break
    g = s.readline()
    #print g
    try:
        p = pynmea2.parse(g)
        #if p.sentence_type in ['RMC', 'GGA']:
        if p.sentence_type in ['RMC']:
            #FindAddress(p.latitude, p.longitude)
            if p1 is None:
               p1 = (p.latitude, p.longitude)
            #PrintMovement(p1, p)
            PrintPathHome(p1, p)
            p1 = (p.latitude, p.longitude)
        #ListParsedFields(p)
    except pynmea2.ParseError:
        print "PARSE ERROR"
        continue
    #print "ZZZZZZZZZZZZZZZ"

print "ZZZZZZZZZZZZZZZ"
print dir(p)
print p.talker
print p.talker_re
print p.sentence_type
