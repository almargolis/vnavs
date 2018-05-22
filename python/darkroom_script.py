
from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
              zip, round, input, int, pow, object)

import cv2
import numpy as np
import OpticChiasm as oc
import cameraman

im_in = oc.ReadImage("/Users/almargolis/Projects/OaklandLines.jpg")
im_base = im_in.copy()

#
# Step 1 - CropPP
#
rect_in = im_in.RectFromSymbolicPP(('61','800'), ('380','1087'))
im_in = im_in.Crop(rect_in)
print(im_in.shape, rect_in)

annotated = im_base.copy()
annotated.DrawRectangle(rect_in, color=oc.DRAW_BGR_GREEN, thickness=2)
#
# Step 2 - ColorMaskSingle
#
hsvspec_in = oc.HsvSpec( hue=98, huerange=25, saturation=205, saturationrange=240, value=205, valuerange=209)
im_in = oc.Image(oc.ColorMaskOneHue(im_in.ImAsAny("HSV"), hsvspec_in),	colorcode=oc.IM_GRAY)
#
# Step 3 - ChaseLine
#
line_points = im_base.ChaseLine(hsvspec_in, rect_in)

annotated = im_base.copy()
annotated.DrawLinePoints(line_points, color=oc.DRAW_BGR_GREEN, thickness=2)

cv2.imshow("im_in", annotated.im)
cv2.waitKey(0)
cv2.destroyAllWindows()
