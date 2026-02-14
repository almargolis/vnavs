import cv2
import numpy as np
from cvpipeline import opticchiasm as oc
from cvpipeline import macbookcamera

cam = macbookcamera.MacbookCamera()
im_in = cam.capture_image()
im_base = im_in.copy()

#
# Step 1 - Gray
#
im_in = im_in.copy_as_gray()

cv2.imshow("im_in", im_in.im)
cv2.waitKey(0)
cv2.destroyAllWindows()
