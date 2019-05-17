
from __future__ import absolute_import, division, print_function
from builtins import (bytes, str, open, super, range,
              zip, round, input, int, pow, object)

import cv2
import numpy as np
import OpticChiasm as oc
import cameraman

cam = cameraman.macbook_camera()
im_in = cam.capture_image()
im_base = im_in.copy()

#
# Step 1 - Gray
#
im_in = im_in.CopyAsGray()
#
# Step 2 - BlurGaussian
#
im_in = oc.Image(im=cv2.GaussianBlur(im_in.im, (3,3), 0.0), colorcode=im_in.colorcode)
#
# Step 3 - CannyAuto
#
im_in = oc.Image(im=oc.AutoCanny(im_in.ImAsGray(), 0.33), colorcode=oc.IM_GRAY)
#
# Step 4 - ContoursFind
#
contours_in, hierarchy_in = cv2.findContours(im_in.ImAsGray(Copy=True), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
#
# Step 5 - ContoursDraw
#


annotated = im_in.CopyAsBGR()
cv2.drawContours(annotated._im, contours_in, -1, (0, 0, 255), 3)
cv2.imshow("im_in", annotated.im)
cv2.waitKey(0)
cv2.destroyAllWindows()
