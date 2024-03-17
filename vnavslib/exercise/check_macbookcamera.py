import cv2
import numpy as np
from vnavslib import opticchiasm as oc
from vnavslib import macbookcamera

cam = macbookcamera.MacbookCamera()
im_in = cam.capture_image()
im_base = im_in.copy()

#
# Step 1 - Gray
#
im_in = im_in.CopyAsGray()

cv2.imshow("im_in", im_in.im)
cv2.waitKey(0)
cv2.destroyAllWindows()
