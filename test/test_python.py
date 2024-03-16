import os
import cv2
import numpy as np
import sys

from vnavslib import vnavs_data

print(dir(vnavs_data))

# z = vnavs_data.MagicXX()

sys.exit(0)

fn = '/Users/almargolis/projects/vnavs/BotImages'
fn = '/Users/almargolis/BotImages'

print(fn)
if os.path.isdir(fn):
  print("isdir")
else:
  print("not isdir")

if os.path.isfile(fn):
  print("isfile")
else:
  print("not isfile")

sys.exit(0)

f = open("/users/almargolis/vnavs_temp/table_20180623071012.nav", 'r')
d = f.read()
l = d.split(chr(1))
print( "lines", len(l))
for ix in range(5):
    parts = l[ix].split(chr(0))
    print("---", parts[2])
f.close()

sys.exit(0)

points = np.array([[1,1], [2,2], [3,3]])
points = np.array([(1,1), (2,3), (3,4)])
width = 4
height = 4

[vx,vy,x,y] =  cv2.fitLine(points, cv2.DIST_L1, 0, 0.01, 0.01)
left_y = int((-x*vy/vx) + y)
right_y = int(((width-x)*vy/vx)+y)

if (left_y >= 0) and (left_y <= height) and (right_y >= 0) and (right_y <= height):
      vert_line = ((width-1,right_y), (0,left_y))
else:
      vert_line = None


#print "points", points 
#print vx, vy, x, y
#print left_y, right_y
#print "slope", float(vy / vx)
#print vert_line
