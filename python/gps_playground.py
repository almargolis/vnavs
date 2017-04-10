import serial
import pynmea2

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

s = set_up_gps()
for x in range(10):
  print "XXX"
  print "XXX"
  print "XXX"
  g = s.readline()
  print g
  try:
      p = pynmea2.parse(g)
  except pynmea2.ParseError:
      print "PARSE ERROR"
      continue
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

print "ZZZZZZZZZZZZZZZ"
print dir(p)
print p.talker
print p.talker_re
print p.sentence_type
