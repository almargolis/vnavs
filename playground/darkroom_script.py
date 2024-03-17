from __future__ import absolute_import, division, print_function
from builtins import bytes, str, open, super, range, zip, round, input, int, pow, object

import cv2
import numpy as np
from vnavslib import opticchiasm as oc
from vnavsrun import cameraman

im_in = oc.Image("opencv_fn=/Users/almargolis/vnavs_temp/Idle_15.jpeg")
im_base = im_in.copy()

#
# Step 1 - ColorMaskSingle
#
hsvspec_in = oc.HsvSpec(
    hue=25, huerange=25, saturation=205, saturationrange=50, value=205, valuerange=180
)
im_in = oc.Image(
    oc.ColorMaskOneHue(im_in.ImAsAny("HSV"), hsvspec_in), colorcode=oc.IM_GRAY
)

cv2.imshow("im_in", im_in.im)
cv2.waitKey(0)
cv2.destroyAllWindows()
