import os, cv2, numpy as np
import math
import time
#from scipy import weave
from operator import itemgetter
import sys
import re

# OpenCv uses a range of 0 to 179 instead of 0 to 360.
# old, non-working values were yellow=30, orange=12, blue=120, red=178
HSV_RATIO = 179.0 / 360.0
HSV_WHITE = -1
HSV_YELLOW = int(70.0 * HSV_RATIO)
HSV_ORANGE = int(60.0 * HSV_RATIO)
HSV_BLUE = int(240.0 * HSV_RATIO)
HSV_RED = int(350.0 * HSV_RATIO)

IM_BGR = 'BGR'
IM_RGB = 'RGB'
IM_GRAY = 'GRAY'
IM_HSV = 'HSV'
COLORCODES = [IM_BGR, IM_GRAY, IM_RGB, IM_HSV]

DRAW_BGR_RED = (0, 0, 255)
DRAW_BGR_MAGENTA = (255, 0, 255)
DRAW_BGR_BLUE = (255, 0, 0)
DRAW_BGR_GREEN = (0, 255, 0)
DRAW_BGR_YELLOW = (0, 255, 255)
DRAW_BGR_CYAN = (255, 255, 0)
DRAW_BGR_BLACK = (0, 0, 0)
DRAW_BGR_WHITE = (255, 255, 255)
DRAW_COLORS = (DRAW_BGR_GREEN, DRAW_BGR_RED, DRAW_BGR_BLUE, DRAW_BGR_YELLOW, DRAW_BGR_MAGENTA, DRAW_BGR_CYAN)

RACE_BLUR = False
RACE_CANNY = False
RACE_CANNY = True
RACE_CROP_X = None
RACE_CROP_Y = 200
RACE_CROP_Y = None
RACE_WTHRESHOLD = 20
RACE_THRESHOLD = 130
RACE_THRESHOLD = 50
RACE_THRESHOLD = 150

class Image(object):
    """
	Image is a wrapper around OpenCv images. Its main unique value is adding colorcode as a property
	of the image, avoiding a variety of bugs. It also provides convenience functions to deal with
        OpenCv and numpy operations that I find non-intuitive.
    """
    __slots__ = (
	'colorcode', 'colordepth', 'height', '_im', 'width' 
    )

    def __init__(self, im=None, colorcode=None, opencv_fn=None):
        if opencv_fn is not None:
            im = cv2.imread(opencv_fn)
            colorcode = IM_BGR
        self.ReplaceImage(im, colorcode)

    def copy(self):
        return Image(im=self._im.copy(), colorcode=self.colorcode)

    def CopyAsBGR(self):
        if self.colorcode == IM_BGR:
            return self.copy()
        transform = getattr(cv2, 'COLOR_{}2{}'.format(self.colorcode, IM_BGR))
        return Image(im=cv2.cvtColor(self._im, transform), colorcode=IM_BGR)

    def CopyAsGray(self):
        if self.colorcode == IM_GRAY:
            return self.copy()
        transform = getattr(cv2, 'COLOR_{}2{}'.format(self.colorcode, IM_GRAY))
        return Image(im=cv2.cvtColor(self._im, transform), colorcode=IM_GRAY)

    @property
    def im(self):			# im is a property to discourage skipping ReplaceImage()
        return self._im

    def ImAsRGB(self):
        if self.colorcode == IM_RGB:
            return self._im
        transform = getattr(cv2, 'COLOR_{}2{}'.format(self.colorcode, IM_RGB))
        return cv2.cvtColor(self._im, transform)

    def ImAsHSV(self):
        if self.colorcode == IM_HSV:
            return self._im
        transform = getattr(cv2, 'COLOR_{}2{}'.format(self.colorcode, IM_HSV))
        return cv2.cvtColor(self._im, transform)

    def ImAsGray(self):
        if self.colorcode == IM_GRAY:
            return self._im
        transform = getattr(cv2, 'COLOR_{}2{}'.format(self.colorcode, IM_GRAY))
        return cv2.cvtColor(self._im, transform)

    def ReplaceImage(self, im, colorcode):
        assert colorcode in COLORCODES
        self._im = im
        self.colorcode = colorcode
        self.width = 0
        self.height = 0
        self.colordepth = 0
        if self._im is not None:
            shape = self._im.shape
            self.height = shape[0]
            self.width = shape[1]
            if len(shape) > 2:
                self.colordepth = shape[2]
            else:
                self.colordepth = 1

    def Write(self, fn):
        cv2.imwrite(fn, self._im)
    

# automatically set threshold using technique from
# http://www.pyimagesearch.com/2015/04/06/zero-parameter-automatic-canny-edge-detection-with-python-and-opencv/
# just saw URL, and have seen it before, so that's re-assuring that I like it
def auto_canny(grayscale_im, auto_canny_sigma):
    grayscale_im_median = np.median(grayscale_im)
    lower_canny_thresh = int(max(0, (1 - auto_canny_sigma) * grayscale_im_median ))
    upper_canny_thresh = int(max(255, (1 + auto_canny_sigma) * grayscale_im_median ))
    lower_canny_thresh = 100
    upper_canny_thresh = 130
    return cv2.Canny(grayscale_im, lower_canny_thresh, upper_canny_thresh)

#
# BGR / RGB Conversions
# thanks to https://www.scivision.co/numpy-image-bgr-to-rgb/
#
def BGR2RGB(bgr):
    # OpenCV image to Matplotlib or Pillow Image.fromarray()
    return bgr[...,::-1]

def RGB2BGR(rgb):
    # image to OpenCV
    return rgb[...,::-1]

def BGR2GRAY(bgr):
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

def apply_mask(channel, mask, fill_value):
    masked = np.ma.array(channel, mask=mask, fill_value=fill_value)
    return masked.filled()

def apply_threshold(channel, low_value, high_value):
    low_mask = channel < low_value
    channel = apply_mask(channel, low_mask, low_value)

    high_mask = channel > high_value
    channel = apply_mask(channel, high_mask, high_value)

    return channel

def Histogram_CB(img):
    channels = cv2.split(img)
    out_channels = []
    for channel in channels:
        out_channels.append(cv2.equalizeHist(channel))
    return cv2.merge(out_channels)

def simplest_cb(img, percentile):
    # Separately for each channel,
    # If the intensity is in the bottom X percentile, increase to the highest value in
    # that percentile group. This eliminates low values in this channel.
    # If the intensity is in the top X percentile, reduce to the lowest value in
    # that percentile group. This eliminates high values in this channel.
    #
    # The percentile parameter is the integer percentage that you want included
    # in this compression. The upper and lower percentiles are each 1/2 of this number.
    #assert img.shape[2] == 3
    #
    # from https://gist.github.com/DavidYKay/9dad6c4ab0d8d7dbf3dc
    # possibly from this Stanford C++ code: https://web.stanford.edu/~sujason/ColorBalancing/simplestcb.html
    assert percentile > 0 and percentile < 100

    half_percentile = percentile / 200.0

    channels = cv2.split(img)

    out_channels = []
    for channel in channels:
        # channels should be BGR
        assert len(channel.shape) == 2
        # find the low and high precentile values (based on the input percentileile)
        height, width = channel.shape
        vec_size = width * height
        flat = channel.reshape(vec_size)

        assert len(flat.shape) == 1

        flat = np.sort(flat)		# sort this channel (R, G or B) by intensity

        n_cols = flat.shape[0]
        # I added the int(). Floor retuns a float. Flat doesn't want a float. This probably was written
        # for python 3 which does some of these conversions differently.
        low_val  = flat[int(math.floor(n_cols * half_percentile))]
        high_val = flat[int(math.ceil( n_cols * (1.0 - half_percentile)))]

        #print "Lowval: ", low_val
        #print "Highval: ", high_val

        # saturate below the low percentileile and above the high percentileile
        thresholded = apply_threshold(channel, low_val, high_val)
        # scale the channel
        normalized = cv2.normalize(thresholded, thresholded.copy(), 0, 255, cv2.NORM_MINMAX)
        out_channels.append(normalized)

    return cv2.merge(out_channels)

def NextColorIx(c):
    c += 1
    if c >= len(DRAW_COLORS):
        c = 0
    return c

def ContoursToLineVectors(img, contours, hierarchy, MinimumArea=1, MaximumLines=3):
    # This only looks at top level of hierarchy.
    if hierarchy is None:
        return None
    print("VECTOR vvvvvvv")
    h_ix = 0
    areas = []
    while h_ix >= 0:
        h = hierarchy[0, h_ix]
        cnt = contours[h_ix]
        area = cv2.contourArea(cnt)
        if area >= MinimumArea:
            areas.append((area, h_ix))
        h_ix = h[0]
    areas.sort(reverse=True)			# sort from largest to smallest)
    for this in areas[:MaximumLines]:
        h_ix = this[1]
        cnt = contours[h_ix]
        rect = cv2.minAreaRect(cnt)
        box = cv2.boxPoints(rect).tolist()
        box.sort(key=itemgetter(1))		# sort by descending y-coordinate
        if box[0][0] <= box[1][0]:
            upper_left = box[0]
            upper_right = box[1]
        else:
            upper_left = box[1]
            upper_right = box[0]
        if box[2][0] <= box[1][0]:
            lower_left = box[2]
            lower_right = box[3]
        else:
            lower_left = box[3]
            lower_right = box[2]
        xu = int((upper_left[0] + upper_right[0]) / 2)
        if upper_left[1] > upper_right[1]:
            yu = int(upper_left[1])
        else:
            yu = int(upper_right[1])
        xl = int((lower_left[0] + lower_right[0]) / 2)
        if lower_left[1] > lower_right[1]:
            yl = int(lower_left[1])
        else:
            yl = int(lower_right[1])
        cv2.line(img, (xu, yu), (xl, yl), DRAW_BGR_BLACK, 5) 
        box = np.int0(box)
        cv2.drawContours(img, [box], 0, DRAW_BGR_WHITE, 2)
        print("RRR", rect)
    print("^^^^^^^^^")
        
def CrayolaContours(img, contours, hierarchy, MaxLevel=-1):
    def ColorBranch(ix, c, this_level, max_level):
        h = hierarchy[0, ix]
        c = NextColorIx(c)
        color = DRAW_COLORS[c]
        next_ix = h[0]
        child_ix = h[2]
        cnt = contours[ix]
        cv2.drawContours(img, [cnt], 0, color, -1)
        if (MaxLevel < 0) or (this_level < max_level):
            while child_ix >= 0:
                child_ix = ColorBranch(child_ix, c, this_level+1, max_level)
                c = NextColorIx(c)
        return next_ix
    if hierarchy is None:
        return img
    h_ix = 0
    h_color = -1
    while h_ix >= 0:
        h_ix = ColorBranch(h_ix, h_color, 1, MaxLevel)
        h_color = NextColorIx(h_color)
    return img

class ColorBalance(object):
    def __init__(self, low_vals=None, high_vals=None):
        self.low_vals = low_vals
        self.high_vals = high_vals

    def apply_mask(self, channel, mask, fill_value):
        masked = np.ma.array(channel, mask=mask, fill_value=fill_value)
        return masked.filled()

    def apply_threshold(self, channel, low_value, high_value):
        low_mask = channel < low_value
        channel = self.apply_mask(channel, low_mask, low_value)
        high_mask = channel > high_value
        channel = self.apply_mask(channel, high_mask, high_value)
        return channel

    def analyze(self, img, percentile):
        assert percentile > 0 and percentile < 100
        half_percentile = percentile / 200.0
        channels = cv2.split(img)
        self.low_vals = []
        self.high_vals = []
        for channel in channels:
            # channels should be BGR
            assert len(channel.shape) == 2
            # find the low and high precentile values (based on the input percentileile)
            height, width = channel.shape
            vec_size = width * height
            flat = channel.reshape(vec_size)
            assert len(flat.shape) == 1
            flat = np.sort(flat)		# sort this channel (R, G or B) by intensity
            n_cols = flat.shape[0]
            # I added the int(). Floor retuns a float. Flat doesn't want a float. This probably was written
            # for python 3 which does some of these conversions differently.
            self.low_vals.append(flat[int(math.floor(n_cols * half_percentile))])
            self.high_vals.append(flat[int(math.ceil( n_cols * (1.0 - half_percentile)))])
        return self.balance(channels=channels)

    def balance(self, img=None, channels=None):
        if channels is None:
            channels = cv2.split(img)
        out_channels = []
        for ix, channel in enumerate(channels):
            low_val = self.low_vals[ix]
            high_val = self.high_vals[ix]
            # saturate below the low percentileile and above the high percentileile
            thresholded = self.apply_threshold(channel, low_val, high_val)
            # scale the channel
            normalized = cv2.normalize(thresholded, thresholded.copy(), 0, 255, cv2.NORM_MINMAX)
            out_channels.append(normalized)
        return cv2.merge(out_channels)

def ColorKey(img):
    channels = cv2.split(img)
    print("CK channels:", len(channels))
    threshold = 200

    out_channels = []
    for channel in channels:
        # This really only works for one channel
        mask = channel <= threshold
        thresholded = apply_mask(channel, mask, 0)
        mask = channel > threshold
        thresholded = apply_mask(thresholded, mask, 255)
        # scale the channel
        #normalized = cv2.normalize(thresholded, thresholded.copy(), 0, 255, cv2.NORM_MINMAX)
        normalized = thresholded
        out_channels.append(normalized)

    return cv2.merge(out_channels)

def _thinningIteration(im, iter):
	I, M = im, np.zeros(im.shape, np.uint8)
	expr = """
	for (int i = 1; i < NI[0]-1; i++) {
		for (int j = 1; j < NI[1]-1; j++) {
			int p2 = I2(i-1, j);
			int p3 = I2(i-1, j+1);
			int p4 = I2(i, j+1);
			int p5 = I2(i+1, j+1);
			int p6 = I2(i+1, j);
			int p7 = I2(i+1, j-1);
			int p8 = I2(i, j-1);
			int p9 = I2(i-1, j-1);
			int A  = (p2 == 0 && p3 == 1) + (p3 == 0 && p4 == 1) +
			         (p4 == 0 && p5 == 1) + (p5 == 0 && p6 == 1) +
			         (p6 == 0 && p7 == 1) + (p7 == 0 && p8 == 1) +
			         (p8 == 0 && p9 == 1) + (p9 == 0 && p2 == 1);
			int B  = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9;
			int m1 = iter == 0 ? (p2 * p4 * p6) : (p2 * p4 * p8);
			int m2 = iter == 0 ? (p4 * p6 * p8) : (p2 * p6 * p8);
			if (A == 1 && B >= 2 && B <= 6 && m1 == 0 && m2 == 0) {
				M2(i,j) = 1;
			}
		}
	}
	"""

	weave.inline(expr, ["I", "iter", "M"])
	return (I & ~M)

def ColorMaskWhite(hsvChannels, threshold=50):
    minValue = 255 - threshold
    maxSaturation = threshold
    ret, saturationMask = cv2.threshold(hsvChannels[1], maxSaturation, 255, cv2.THRESH_BINARY_INV)
    ret, valueMask = cv2.threshold(hsvChannels[2], minValue, 255, cv2.THRESH_BINARY)
    filterMask = cv2.bitwise_and(saturationMask, valueMask)
    return filterMask

def ColorMaskOneColor(hsvChannels, hueValue, huerange=25, threshold=50):
    # In literature, hue space goes from 0 to 360 degrees, but OpenCV rescales the range to 0 up to 179,
    # because 360 does not fit in a single byte. There is another mode where 0..360 is rescaled to 0..255 but this isn't as common.
    # Red color, value 0,  is one of the special case where our selection range wraps 0/179.
    assert (hueValue >= 0) and (hueValue <= 179)

    minSaturation = threshold
    minValue = threshold

    hueArray = hsvChannels[0]

    # is the color within the lower hue range?
    hueMask = cv2.inRange(hueArray, hueValue - huerange, hueValue + huerange)

    # If the color is near the limits of the 0 to 179 hue value range, check the overflow range.
    hueWrapMask = None
    if (hueValue - huerange) < 0:
        hueWrapLowerValue = 179 - (hueValue - huerange)
        hueWrapMask = cv2.inRange(hueArray, hueWrapLowerValue, 179)
    elif (hueValue + huerange) > 179:
        hueWrapUpperValue = (hueValue + huerange) - 179
        hueWrapMask = cv2.inRange(hueArray, 0, hueWrapUpperValue)
    if hueWrapMask is not None:
        hueMask = cv2.bitwise_or(hueMask, hueWrapMask)

    # Now we have to filter pixels where saturation and value do not fit the limits:
    ret, saturationMask = cv2.threshold(hsvChannels[1], minSaturation, 255, cv2.THRESH_BINARY)
    ret, valueMask = cv2.threshold(hsvChannels[2], minValue, 255, cv2.THRESH_BINARY)

    print("HUE SHAPE", hueMask.shape, hueMask.dtype)
    print("SAT SHAPE", saturationMask.shape, saturationMask.dtype)
    print("VAL SHAPE", valueMask.shape, valueMask.dtype)
    filterMask = cv2.bitwise_and(saturationMask, valueMask)
    print("FIL SHAPE", filterMask.shape)
    hueMask = cv2.bitwise_and(hueMask, filterMask)
    print("FINAL SHAPE", hueMask.shape)
    return hueMask

def ColorMask(hsvImage, colors=[0], huerange=25, threshold=50, wthreshold=50):
    # adapted from http://stackoverflow.com/questions/35866411/opencv-how-to-detect-lines-of-a-specific-colour
    # convert to HSV color space
    hsvChannels = cv2.split(hsvImage)

    result = None
    for this_hue in colors:
        if this_hue < 0:
            this_result = ColorMaskWhite(hsvChannels, threshold=wthreshold)
        else:
            this_result = ColorMaskOneColor(hsvChannels, this_hue, huerange=huerange, threshold=threshold)
        if result is None:
            result = this_result
        else:
            result = cv2.bitwise_or(result, this_result)
    return result

def ROI(img, x1, y1, x2, y2):
    # extract a region of interest, accepting "normal order" coordinates
    # (x1, y1) is the upper/left corner, (x2, y2) is the lower/right corner
    # origin is upper/left of image
    roi = img[y1:y2, x1:x2 ]
    return roi

def thinning(src):
	dst = src.copy() / 255
	prev = np.zeros(src.shape[:2], np.uint8)
	diff = None

	while True:
		dst = _thinningIteration(dst, 0)
		dst = _thinningIteration(dst, 1)
		diff = np.absolute(dst - prev)
		prev = dst.copy()
		if np.sum(diff) == 0:
			break

	return dst * 255

def thinning_example(src):
        # This is just kept for doccumented example from thinning code
        # https://github.com/bsdnoobz/zhang-suen-thinning/blob/master/thinning.py
	#src = cv2.imread("kanji.png")
	#if src == None:
	#	sys.exit()
        bw = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
        _, bw2 = cv2.threshold(bw, 10, 255, cv2.THRESH_BINARY)
        bw2 = thinning(bw2)
        return bw2
        cv2.imshow("src", bw)
        cv2.imshow("thinning", bw2)
        cv2.waitKey()

def HoughLines(img, gray):
  contoured_image = img.copy()
  #edges = cv2.Canny(gray.copy() ,100,200,apertureSize = 3)	# app size is 3, 5 or 7
  edges = auto_canny(gray.copy(), 0.33)

  minLineLength = 30
  maxLineGap = 5
  maxLineGap = 1
  maxLineGap = 30
  rho = 30
  rho = 90
  rho = 1
  theta = np.pi / 180
  threshold = 1
  threshold = 15
  #lines = cv2.HoughLinesP(edges, rho, theta, threshold, minLineLength,maxLineGap)
  lines = cv2.HoughLinesP(edges, 1, np.pi/180, 15, minLineLength=50, maxLineGap=10)
  if lines is None:
      print("NO LINES")
  if lines is not None:
    print("lineCt:", len(lines))
    for x in range(0, len(lines)):
      for x1,y1,x2,y2 in lines[x]:
        cv2.line(contoured_image,(x1,y1),(x2,y2),(0,255,0),2)
  return edges, contoured_image

def DrawContourLines(img, contours, color):
  h, w, channels = img.shape
  origin_x = int(w/2)
  origin_y = 0
  horizon_x = origin_x
  horizon_y = h
  tiny = []
  vertical = []
  horizontal = []
  for this_c in contours:
    rect = cv2.minAreaRect(this_c)
    # rect: center (x,y), (width, height), angle of rotation
    print("R", rect)
    line = CalcRectCenterline(rect, w, h)
    cv2.line(img, line[0], line[1], color ,2)
  return img

def ContourLines(img, gray, Drawlines=False, DrawBoth=False):
  # canny edge detection
  #bw_edged = auto_canny(gray, 0.33)
  bw_edged = cv2.Canny(gray, 30, 200)
  cont2, contours, hierarchy = cv2.findContours(bw_edged.copy(),cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)
  #cont2, contours, hierarchy = cv2.findContours(bw_edged.copy(),cv2.RETR_TREE,cv2.CHAIN_APPROX_TC89_L1)
  if len(img.shape) == 2:
    cropped_height, cropped_width = img.shape
  else:
    cropped_height, cropped_width, cropped_channels = img.shape
  (tiny, vertical, horizontal) = CreateContours(contours, cropped_width, cropped_height)
  if Drawlines or DrawBoth:
    contoured_image = DrawContourLines(img.copy(), tiny, (128,128,0))
    contoured_image = DrawContourLines(contoured_image, vertical, (128,128,0))
    contoured_image = DrawContourLines(contoured_image, horizontal, (128,128,0))
  else:
    contoured_image = img.copy()
  if (not Drawlines) or DrawBoth:
    contoured_image = cv2.drawContours(contoured_image.copy(), tiny, -1, (128,0,128), 1)
    contoured_image = cv2.drawContours(contoured_image.copy(), vertical, -1, (0,255,0), 1)
    contoured_image = cv2.drawContours(contoured_image.copy(), horizontal, -1, (255,0,0), 1)
  DumpContours(contours)
  return bw_edged, contoured_image



#
# The draw contour functions take an image and set of contours and
# return a new image with the contours drawn in some way.
#

def DrawContourFilled(img, contours):
  image_shape = img.shape
  mask_shape = (image_shape[0], image_shape[1], 1)
  final = img.copy()
  mask = np.zeros(mask_shape, np.uint8)

  for i in range(len(contours)):
    #if len(contours[i]) < 9:
    #  continue
    mask[...]=0								# zero out mask
    mask = cv2.drawContours(mask, contours, i, 255, -1)	# draw contour on mask
    avg_color = (255, 0, 0)
    avg_color = cv2.mean(img, mask)
    avg_color = (int(avg_color[0]), int(avg_color[1]), int(avg_color[2]))
    white_threshold = 175
    white_threshold = 0
    if white_threshold > 0:
      if (avg_color[0] < white_threshold) and (avg_color[1] < white_threshold) and (avg_color[2] < white_threshold):
        avg_color = (0, 0, 0)
        avg_color = (0, 0, 255)
      else:
        avg_color = (255, 255, 255)
    #black_threshold = 128
    #if (avg_color[0] > black_threshold) and (avg_color[1] > black_threshold) and (avg_color[2] > black_threshold):
    #  avg_color = (255, 255, 255)
    cv2.drawContours(final, contours, i, avg_color, -1)    # draw filled countour, using avg color
    #cv2.drawContours(final, contours, i, (0,0,255), 1)    # draw contour outlines
  return final


def CrayolaFilter2(im, bw_threshold=20, mix_threshold=50):
    #im = simplest_cb(im, 20)
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    mask = np.asarray([224, 224, 224], dtype=np.uint8)
    mask = np.asarray([192, 128, 128], dtype=np.uint8)
    mask = np.asarray([192, 192, 192], dtype=np.uint8)
    mask = np.asarray([224, 128, 128], dtype=np.uint8)
    out = cv2.bitwise_and(hsv, mask)
    im = cv2.cvtColor(out, cv2.COLOR_HSV2BGR)
    bw = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    canny_image = auto_canny(bw, 0.33)
    (imgxx, opencv_contours, hierarchy) = cv2.findContours(canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    im = cv2.drawContours(im, opencv_contours, -1, (255, 0, 255), 1)
    #return canny_image
    return im


def CrayolaFilter(im, bw_threshold=20, mix_threshold=50):
    color_map = {
        'b': np.asarray([0, 0, 0], dtype=np.uint8),
        'w': np.asarray([255, 255, 255], dtype=np.uint8),
        'l': np.asarray([255, 0, 0], dtype=np.uint8),
        'g': np.asarray([0, 255, 0], dtype=np.uint8),
        'r': np.asarray([0, 0, 255], dtype=np.uint8),
        'y': np.asarray([0, 128, 128], dtype=np.uint8),
        'z': np.asarray([128, 128, 128], dtype=np.uint8),
    }
    height, width, channels = im.shape
    out_im = np.zeros(im.shape, np.uint8)
    for y in range(height):
        for x in range(width):
            color = im[y, x]			# BGR
            t = ColorString(color, bw_threshold=bw_threshold, mix_threshold=mix_threshold)
            tc = t[0]
            if tc in color_map:
                c_out = color_map[tc]
            else:
                c_out = color_map['z']
            print(y, x, t, color, c_out)
            out_im[y, x] = c_out
    return out_im

def ColorString(color, bw_threshold=20, mix_threshold=50):
  # bw_sthreshold of 30 was about right for white line
  min_v = min(color)
  max_v = max(color)
  blue = color[0]
  green = color[1]
  red = color[2]
  if ((max_v - min_v) < bw_threshold):
      if (min_v > 128):
          c = "white"
      else:
          c =  "black"
  elif blue >= max_v:
      c = "l-blue"
  elif green >= max_v:
      if abs(green - red) < mix_threshold:
          c = "yellow"
      else:
          c = "green"
  else:
      c = "red"
  return c + ' ' + repr(color)

def FilterContours(img, contours, SelectColors='r'):
  image_shape = img.shape
  mask_shape = (image_shape[0], image_shape[1], 1)
  final = img.copy()
  mask = np.zeros(mask_shape, np.uint8)
  area_threshold = 90	 # minimum area sized contour to draw
  area_threshold =  5	 # minimum area sized contour to draw
  area_threshold = 10	 # minimum area sized contour to draw
  new_contours = []

  for i in range(len(contours)):
    mask[...]=0								# zero out mask
    mask = cv2.drawContours(mask, contours, i, 255, -1)	# draw contour on mask
    avg_color = cv2.mean(img, mask)
    avg_color = (int(avg_color[0]), int(avg_color[1]), int(avg_color[2]))
    color_str = ColorString(avg_color)
    this_c = contours[i]
    area = cv2.contourArea(this_c)
    if color_str[0] in SelectColors:
      continue
    if area < area_threshold:
      continue
    #print("Vertices:", len(this_c), "Area:", area, "@", int(rect[0][0]), int(rect[0][1]), "size", int(rect[1][0]), int(rect[1][1]),  "R:", int(rect[2]), "Color:", color_str)
    new_contours.append(this_c)
  new_contours = sorted(new_contours, key = cv2.contourArea, reverse = True)[0:8]
  return new_contours

def mean(numbers):
    if len(numbers) == 0:
        return 0
    return sum(numbers) / len(numbers)

class ReflexEntities(object):
    def __init__(self, image, process="CY", colors="WRY"):
        color_list = []
        for this in colors:
            if this == "W":
                color_list.append(HSV_WHITE)
            elif this == "R":
                color_list.append(HSV_RED)
            elif this == "Y":
                color_list.append(HSV_YELLOW)
            elif this == "B":
                color_list.append(HSV_BLUE)
        # im is an OpenCV BGR image object
        self.original = image
        self.image = image
        for this in process:
            if this == 'B':
                #print("simplest_cb")
                self.image = simplest_cb(self.image.copy(), 20)
            elif this == 'C':
                #print("ColorMask", color_list)
                self.image = ColorMask(self.image.copy(), colors=color_list, threshold=RACE_THRESHOLD, wthreshold=RACE_WTHRESHOLD)		# red, white
            elif this == 'E':
                self.image = cv2.equalizeHist(self.image.copy())
            elif this == 'G':
                self.image = cv2.GaussianBlur(self.image.copy(), (5,5), 0)
            elif this == 'W':
                self.image = BGR2GRAY(self.image)
            elif this == 'Y':
                #print("Canny")
                self.image = auto_canny(self.image.copy(), 0.1)		# ben's sigma was 0.33
        self.h_lines = cv2.HoughLinesP(self.image, 1, np.pi/180, 15, minLineLength=30, maxLineGap=10)
        #if self.h_lines is None:
        #    print("LINES -- NONE")
        #else:
        #    print("LINES", len(self.h_lines))
        self.map_lines = []
        self.avg_slope = 0

    def ProcessLines(self):
        VERTICAL_SLOPE = 9999
        h_color = (0, 0, 255)				# blue
        h_width = 1
        self.map_lines = []
        self.avg_slope = 0
        self.slope_ct = 0
        h = self.image.shape[0]
        w = self.image.shape[1]
        if len(self.image.shape) > 2:
            c = self.image.shape[2]
        else:
            c = 1
        m = int(w/2)
        if self.h_lines is not None:
            for x in range(0, len(self.h_lines)):
                for x1,y1,x2,y2 in self.h_lines[x]:
                    #cv2.line(self.annotated,(x1,y1),(x2,y2), h_color, h_width)
                    #deposition += "%d. (%d,%d) (%d,%d)\n" % (x, x1, y1, x2, y2)
                    mx1 = x1 - m
                    mx2 = x2 - m
                    my1 = h - y1
                    my2 = h - y2
                    mrise = float(my2 - my1)
                    mrun = float(mx2 - mx1)
                    if (mrun > -0.01) and (mrun < 0.01):
                        mslope = VERTICAL_SLOPE
                    else:
                        mslope = mrise / mrun
                    mlen = math.sqrt((mrise ** 2) + (mrun ** 2))
                    p1dist = math.sqrt((mx1 ** 2) + (my1 ** 2))
                    p2dist = math.sqrt((mx2 ** 2) + (my2 ** 2))
                    mdist = min(p1dist, p2dist)
                    if mdist < 300:
                        self.map_lines.append((mdist, mlen, mslope, (mx1, my1), (mx2, my2), (x1, y1), (x2, y2), mrise, mrun))
            self.map_lines.sort()
            print(self.map_lines[0])
            #print("Map Lines", len(self.map_lines))
            p1 = self.map_lines[0][5]
            p2 = self.map_lines[0][6]
            x1 = int((p1[0] + p2[0]) / 2)
            y1 = int((p1[1] + p2[1]) / 2)
            m = self.map_lines[0][2]
            return (x1, y1, m)
        else:
            return None

    def AnnotateFullImage(self, image, linect=10, x1=0, y1=0, color=None):
        if color is None:
            color = (0, 255, 0)				# green
        a_width = 5
        for this in self.map_lines[:linect]:
            p1 = (this[5][0]+x1, this[5][1]+y1)
            p2 = (this[6][0]+x1, this[6][1]+y1)
            cv2.line(image, p1, p2, color, a_width)

    def AnalyzeLines(self):
        cum_slope = 0
        ct_slope = 0
        if len(self.map_lines) < 1:
            return
        for this in self.map_lines[:1]:
            cv2.line(self.annotated,this[5],this[6], a_color, a_width)
            #print(this)
            mlen = this[1]
            mslope = this[2]
            if (mslope < 0.5) and (mlen < 20):
                # this might be the front edge of a dash, go straight
                mslope = 999
            ct_slope += 1
            cum_slope += mslope
        if ct_slope > 0:
            avg_slope = cum_slope / ct_slope
        else:
            avg_slope = VERTICAL_SLOPE
        print("MAP", avg_slope)
        self.avg_slope = avg_slope
        self.slope_ct = ct_slope
        cv2.imwrite('temp/ann.jpeg', self.annotated)

def Raw_Crop_TranslateSym(c, ext, p1=None):
    if isinstance(c, basestring):
        if c[0] == 'm':
            if c == 'm':
                return ext / 2
            else:
                return (ext / 2) + int(c[1:])
        elif c[0] == 'e':
            if c == 'e':
                return ext
            else:
                return ext + int(c[1:])
        elif (c[0] == 'p') and (p1 is not None):
            if c == 'p':
                return p1
            else:
                return p1 + int(c[1:])
        elif c[0] == 'b':
            if c == 'b':
                return 0
            else:
                return int(c[1:])
        else:
            print("CROP-T", c, int(c))
            c = int(c)
            if c < 0:
                return ext + c
            else:
                return c
    else:
        if c < 0:
            return ext + c
        else:
            return c

def Crop_TranslateSym(c, ext, p1=None):
    res = Raw_Crop_TranslateSym(c=c, ext=ext, p1=p1)
    if res < 0:
        return 0
    if res > ext:
        return ext
    return res

def Crop_TranslateYX(im, y_range, x_range):
    height, width, channels = im.shape
    y_low = Crop_TranslateSym(y_range[0], height)
    y_high = Crop_Translat_Sym(y_range[1], height)
    x_low = Crop_TranslateSym(x_range[0], width)
    x_high = Crop_TranslateSym(x_range[1], width)
    if x_low > x_high:
        x_low, x_high = x_high, x_low
    if y_low > y_high:
        y_low, y_high = y_high, y_low
    return (y_low, y_high, x_low, x_high)

def Crop_TranslatePP(im, p1, p2):
    height, width, channels = im.shape
    x_low = Crop_TranslateSym(p1[0], width)
    y_low = Crop_TranslateSym(p1[1], height)
    x_high = Crop_TranslateSym(p2[0], width, x_low)
    y_high = Crop_TranslateSym(p2[1], height, y_low)
    if x_low > x_high:
        x_low, x_high = x_high, x_low
    if y_low > y_high:
        y_low, y_high = y_high, y_low
    return (y_low, y_high, x_low, x_high)

class Robogames(object):
    def __init__(self, image, colors):
        # im is an OpenCV BGR image object
        self.original = image
        self.green = (0, 255, 0)				# green
        if (RACE_CROP_X is not None) or (RACE_CROP_Y is not None):
            height, width, channels = image.shape
            if RACE_CROP_X is None:
                c_x = 0
                c_w = width
            else:
                c_x = self.img_crop[0]
                c_w = self.img_crop[1]
            if RACE_CROP_Y is None:
                c_y = 0
            else:
                c_y = height - RACE_CROP_Y
            print("Crop: (%d, %d) start (%d, %d) width %d" % (width, height, c_x, c_y, c_w))
            image = image[c_y:height, c_x:c_x+c_w]
        self.annotated = image.copy()
        #image = simplest_cb(self.original, 20)
        image = ColorMask(image, colors=colors, threshold=RACE_THRESHOLD, wthreshold=RACE_WTHRESHOLD)		# red, white
        #bw_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        #bw_image = cv2.blur(bw_image.copy(), (5,5))
        if RACE_BLUR:
            image = cv2.GaussianBlur(image.copy(), (5,5), 0)
        if RACE_CANNY:
            image = auto_canny(image, 0.33)
        #(imgxx, opencv_contours, hierarchy) = cv2.findContours(canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        self.h_lines = cv2.HoughLinesP(image, 1, np.pi/180, 15, minLineLength=50, maxLineGap=30)
        self.map_lines = []
        self.avg_slope = 0

    def ProcessLines(self):
        VERTICAL_SLOPE = 9999
        h_color = (0, 0, 255)				# blue
        h_width = 1
        a_width = 2
        self.map_lines = []
        self.avg_slope = 0
        self.slope_ct = 0
        h, w, c = self.annotated.shape
        m = int(w/2)
        if self.h_lines is not None:
            for x in range(0, len(self.h_lines)):
                for x1,y1,x2,y2 in self.h_lines[x]:
                    cv2.line(self.annotated,(x1,y1),(x2,y2), h_color, h_width)
                    #deposition += "%d. (%d,%d) (%d,%d)\n" % (x, x1, y1, x2, y2)
                    mx1 = x1 - m
                    mx2 = x2 - m
                    my1 = h - y1
                    my2 = h - y2
                    mrise = my2 - my1
                    mrun = mx2 - mx1
                    if abs(mrun) < 0.01:
                        mslope = VERTICAL_SLOPE
                    else:
                        mslope = mrise / mrun
                    mlen = math.sqrt((mrise ** 2) + (mrun ** 2))
                    p1dist = math.sqrt((mx1 ** 2) + (my1 ** 2))
                    p2dist = math.sqrt((mx2 ** 2) + (my2 ** 2))
                    mdist = min(p1dist, p2dist)
                    mdist = mlen
                    # mx, mx are transposed to origin at bottom center
                    # x, y are opencv origin upper/left
                    self.map_lines.append((mdist, mlen, mslope, (mx1, my1), (mx2, my2), (x1, y1), (x2, y2)))
            self.map_lines.sort()

    def FilterLines(self):
            cum_slope = 0
            ct_slope = 0
            #print("MAP", h, m, w)
            self.filteredLines = []
            for this in self.map_lines[:5]:
                slope = abs(this[2])
                print(slope)
                #if (slope < 4) or (slope > 18):
                #if slope > 1:
                #    continue
                p1 = this[5]
                p2 = this[6]
                middleX = int((p1[0] + p2[0]) / 2)
                self.filteredLines.append((middleX, this))

    def SelectLines(self):
            print("FI:TERED", len(self.filteredLines))
            self.rectangles = []
            self.selectedLines = []
            Allpoints = []
            for thisX in self.filteredLines:
                this = thisX[1]
                points = [this[5], this[6]]
                Allpoints  += points
            self.MakeRec(Allpoints)

    def SelectCone(self):
            self.selectedLines = []
            if len(self.filteredLines) >= 2:
                # we need two lines to form a cone
                self.filteredLines.sort()
                for ix, this in enumerate(self.filteredLines[:-1]):
                    l1 = this[1]
                    l2 = self.filteredLines[ix+1][1]
                    slope1 = l1[2]
                    slope2 = l2[2]
                    if (slope1 > 0) and (slope2 < 0):
                        self.selectedLines.append((l1, l2))

    def MakeConeRec(self):
                self.rectangles = []
                for this in self.selectedLines:
                    points = [this[0][5], this[0][6], this[1][5], this[1][6]]
                    self.MakeRec(points)

    def MakeRec(self, points):
                    if len(points) < 1:
                        return
                    a_width = 1
                    lowerleftX = points[0][0]
                    upperrightX = points[0][0]
                    lowerleftY = points[0][1]
                    upperrightY = points[0][1]
                    for thisp in points[1:]:
                        if thisp[0] < lowerleftX:
                            lowerleftX = thisp[0]
                        if thisp[0] > upperrightX:
                            upperrightX = thisp[0]
                        if thisp[1] > lowerleftY:
                            # y-values are inverted
                            lowerleftY = thisp[1]
                        if thisp[1] < upperrightY:
                            upperrightY = thisp[1]
                    llp = (lowerleftX, lowerleftY)
                    urp = (upperrightX, upperrightY)
                    cv2.rectangle(self.annotated, llp, urp, self.green, a_width)
                    self.rectangles.append((llp, urp))
                    print("RECT", llp, urp)


class ImageAnalyzer(object):
    def __init__(self, fpath=None, Crop=None, CroppedHeight=None,
				CannyMethod=1, ContourFill='b', ContourOutline=True,
				DoFilterContours=True,
				ColorBalance='c', Blur='x'):
        self.img_fpath = fpath
        self.img_crop = Crop
        self.img_cropped_height = CroppedHeight
        self.img_blur_method = Blur
        self.img_canny_method = CannyMethod
        self.img_color_balance_method = ColorBalance
        self.img_annotated = None		# OpenCV annotated image object
        self.img_source_dir = ''
        self.img_fname_suffix = ''
        self.annotate_fill_method = ContourFill
        self.annotate_contour_outline = ContourOutline
        self.annotate_opencv_contours = True
        self.do_filter_contours = DoFilterContours
        self.img_contour_colors = "r"
        self.img_contour_colors = "wy"
        self.snap_shots = []
        self.snap_titles = []
        self.do_save_snaps = True
        self.vert_line = None
        self.horz_line = None

    def FindLines(self, image=None):
        if image is None:
            fpath = os.path.join(self.img_source_dir, self.img_fpath + self.img_fname_suffix + '.jpg')
            print(fpath)
            image = cv2.imread(fpath)
        DrawGrid(self.Snapshot(image, 'Original'))

        start_clock = time.clock()
        if self.img_color_balance_method == 'c':
            image = simplest_cb(image, 20)
        self.Snapshot(image, 'ColorBalanced')

        # crop
        if (self.img_crop is not None) or (self.img_cropped_height is not None):
            height, width, channels = image.shape
            if self.img_crop is None:
                c_x = 0
                c_w = width
            else:
                c_x = self.img_crop[0]
                c_w = self.img_crop[1]
            if self.img_cropped_height is None:
                c_y = 0
            else:
                c_y = height - self.img_cropped_height
            print("Crop: (%d, %d) start (%d, %d) width %d" % (width, height, c_x, c_y, c_w))
            cropped_image = image[c_y:height, c_x:c_x+c_w]
            self.Snapshot(cropped_image, 'Cropped')
        else:
            cropped_image = image.copy()

        # bw img
        bw_image = cv2.cvtColor(cropped_image, cv2.COLOR_BGR2GRAY)
        self.Snapshot(bw_image, 'BW')
        if self.img_blur_method == 'g':
            bw_image = cv2.Gaussianself.img_blur_method(bw_image, (21,21), 0)
        elif self.img_blur_method == 'b':
            bw_image = cv2.blur(bw_image.copy(), (5,5))  # or maybe (3,3)
        elif self.img_blur_method == 'c':
            bw_image = ColorKey(bw_image)
        elif self.img_blur_method == 'f':
            bw_image = cv2.bilateralFilter(bw_image.copy(), 11, 17, 17)
        elif self.img_blur_method == 'h':
            bw_image = cv2.equalizeHist(bw_image.copy())
        elif self.img_blur_method == 'z':
            bw_image = simplest_cb(bw_image.copy(), 20)
        self.Snapshot(bw_image, 'Blurred')

        if self.img_canny_method == 1:
            canny_image = auto_canny(bw_image, 0.33)
        elif self.img_canny_method == 2:
            # based on pyimagesearch method
            canny_image = cv2.Canny(bw_image, 30, 200)
        (imgxx, opencv_contours, hierarchy) = cv2.findContours(canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        print("Contour Ct:", len(opencv_contours))

        print("FindLines() elapsed time:", time.clock() - start_clock)
        if self.do_filter_contours:
            contours = FilterContours(cropped_image, opencv_contours, SelectColors=self.img_contour_colors)
            print("Filtered Contour Ct:", len(contours))
            self.ClassifyContours(cropped_image, contours)
        else:
            contours = opencv_contours
        print("FindLines() elapsed time:", time.clock() - start_clock)

        annotated_cropped_image = cropped_image.copy()
        outline_color = (0, 255, 0)	# green
        opencv_color = (255, 0, 0)	# red
        path_guide_color = (0, 255, 255)
        if self.annotate_opencv_contours:
            cv2.drawContours(annotated_cropped_image, opencv_contours, -1, opencv_color, 1)

        if self.vert_line is not None:
            cv2.line(annotated_cropped_image, self.vert_line[0], self.vert_line[1], path_guide_color, 2)
        if self.horz_line is not None:
            print("HORZ", self.horz_line)
            cv2.line(annotated_cropped_image, self.horz_line[0], self.horz_line[1], path_guide_color, 2)

        print("FindLines() elapsed time:", time.clock() - start_clock)
        if self.annotate_fill_method == 'b':
            self.AnnotateContourBoxes(annotated_cropped_image, contours)
        elif self.annotate_fill_method == 'f':
            self.DrawContourFilled(annotated_cropped_image, contours)

        print("FindLines() elapsed time:", time.clock() - start_clock)
        if self.annotate_contour_outline:
            outline_color = (0, 255, 0)	# green
            cv2.drawContours(annotated_cropped_image, contours, -1, outline_color, 1)
        self.img_annotated = self.Snapshot(annotated_cropped_image, 'Annotated')

        self.WriteSnapshots()

        return self.img_annotated

    def WriteSnapshots(self):
        if not self.do_save_snaps:
            return
        delete_pattern = self.img_fpath + "_D*.jpg"
        dir = self.img_source_dir
        if dir == '':
            dir = '.'
        for f in os.listdir(dir):
            if re.search(delete_pattern, f):
                print("Deleting", f)
                os.remove(os.path.join(dir, f))

        for ix, image in enumerate(self.snap_shots):
          fn = "%s_D%02d_%s.jpg" % (self.img_fpath, ix, self.snap_titles[ix])
          fpath = os.path.join(self.img_source_dir, fn)
          cv2.imwrite(fpath, image)

    def ClassifyContours(self, img, contours):
        height, width = img.shape[:2]
        vert = []
        vert_contours = []
        horz = []
        horz_contours = []
        for this_c in contours:
            rect = cv2.minAreaRect(this_c)
            print(rect)
            # rect: center (x,y), (width, height), angle of rotation
            angle = int(rect[2])
            ctr_line = CalcRectCenterline(rect)
            print("Ctr Line:", ctr_line)
            if angle <= -60:
                vert.append(angle)
                vert_contours.append(ctr_line[0])
                vert_contours.append(ctr_line[1])
            else:
                horz.append(angle)
                horz_contours.append(ctr_line[0])
                horz_contours.append(ctr_line[1])
        #
        vert_points = np.asarray(vert_contours)
        print("Vert:", vert, mean(vert), "Points:", vert_points)
        self.vert_line = None
        if len(vert_points) > 0:
            [vx,vy,x,y] = cv2.fitLine(vert_points, cv2.DIST_L1,0,0.01,0.01)			# four points
            left_y = int((-x*vy/vx) + y)
            right_y = int(((width-x)*vy/vx)+y)
            if (left_y >= 0) and (left_y <= height) and (right_y >= 0) and (right_y <= height):
                self.vert_line = ((width-1,right_y), (0,left_y))
        print(self.vert_line)
        #
        horz_points = np.asarray(horz_contours)
        print("Horz:", horz, mean(horz), "Points:", horz_points)
        self.horz_line = None
        if len(horz_points) > 0:
            [vx,vy,x,y] = cv2.fitLine(horz_points, cv2.DIST_L1,0,0.01,0.01)			# four points
            left_y = int((-x*vy/vx) + y)
            right_y = int(((width-x)*vy/vx)+y)
            if (left_y >= 0) and (left_y <= height) and (right_y >= 0) and (right_y <= height):
                self.horz_line = ((width-1,right_y), (0,left_y))

    def Snapshot(self, image, title='image'):
        """
            Snapshot() makes and saves a copy of the image. In operational mode,
            the save can be globally turned off. The copy is still made so
            clients can use this as a general image copy function, even if
            the save operation is off.
        """
        snap = image.copy()
        if self.do_save_snaps:
            self.snap_shots.append(snap)
            self.snap_titles.append(title)
        return snap

    def AnnotateContourBoxes(self, img, cnts):
        area_threshold = 1		# minimum area sized contour to draw
        for this_c in cnts:
            area = cv2.contourArea(this_c)
            if area < area_threshold:
                continue
            peri = cv2.arcLength(this_c, True)
            approx = cv2.approxPolyDP(this_c, 0.02 * peri, True)
            rect = cv2.minAreaRect(this_c)
            box = cv2.boxPoints(rect)
            box = np.int0(box)
            cv2.drawContours(img,[box],0,(0,0,255),2)

def CalcRectCenterline(cvRect):
  # Box2D: center (x,y), (width, height), angle of rotation
  box_x = cvRect[0][0]
  box_y = cvRect[0][1]
  box_w = cvRect[1][0]
  box_h = cvRect[1][1]
  hyp = box_h / 2
  box_r = math.radians(-cvRect[2])
  print("deg",cvRect[2], "rad", box_r, math.sin(box_r), math.cos(box_r))
  y_offset = int(hyp * math.cos(box_r))
  x_offset = int(hyp * math.sin(box_r))
  return ((int(box_x + x_offset), int(box_y + y_offset)), (int(box_x - x_offset), int(box_y - y_offset)))

def CreateContours(src, w, h):
  origin_x = int(w/2)
  origin_y = 0
  horizon_x = origin_x
  horizon_y = h
  tiny = []
  vertical = []
  horizontal = []
  for this_c in src:
    if len(this_c) < 4:
      # not enough vertices
      #tiny.append(this_c)
      continue
    brec = cv2.boundingRect(this_c)
    #if brec[1] < 30:
    if brec[1] < 0:
      # Too far up in frame, ignore till we get closer.
      # This needs to be smarter because it catches lines that begin at the
      # top of the frame but continue into the relevant part of hte frame.
      tiny.append(this_c)
      continue
    print("B", brec, "Vertices", len(this_c))
    rect = cv2.minAreaRect(this_c)
    # rect: center (x,y), (width, height), angle of rotation
    print("R", rect)
    print(CalcRectCenterline(rect, w, h))
    x = rect[0][0]
    y = rect[0][1]
    w = rect[1][0]
    h = rect[1][1]
    r = abs(rect[2])
    if r > 75:
      (w, h) = (h, w)
    if w > (h * 1.5):
      print("Horizontal")
      horizontal.append(this_c)
      continue
    print("Vertical")
    box = cv2.boxPoints(rect)
    box = np.int0(box)
    #vertical.append(box)
    vertical.append(this_c)
  #
  print(len(tiny), len(vertical), len(horizontal))
  return (tiny, vertical, horizontal)

def DumpContours(contours):
  c_l = len(contours)
  print("Contours len: ", c_l)
  for ix, this_c in enumerate(contours):
    for iy, this_vertex in enumerate(this_c):
      print("C[%d-%d] %s" % (ix, iy, this_vertex))

def FindVertices(contour):
  ul = contour[0]
  ur = contour[0]
  ll = contour[0]
  rr = contour[0]
  for ix, this_v in enumerate(contour):
    if this_v[0] < ul[0]:
      pass

def DrawGrid(img):
  grid_incr = 25
  height, width, channels = img.shape
  for x in range(grid_incr, width, grid_incr):
    cv2.line(img,(x, 0),(x, width),(255,0,0), 1)
  for y in range(grid_incr, height, grid_incr):
    cv2.line(img,(0,y),(width,y),(255,0,0), 1)

def test_old():
  fn = 'R20170325021241_1_0001.jpeg'
  fn = "R20170325021241_2_0001.jpeg"
  im = cv2.imread('temp/' + fn)
  p = Race(im)
  p.ProcessLines()
  sys,exit(0)

  start_time = time.clock()
  brain = ImageAnalyzer()
  brain.img_fpath = 'opencv_3'; brain.img_crop=(350,150)		# distance calibration
  brain.img_fpath = 'opencv_1'; brain.img_crop=(450,75)		# center stripe
  brain.img_fpath = 'opencv_1'; brain.img_crop=(600,75)		# right stripe
  brain.img_fpath = 'opencv_4'; brain.img_crop=(550,75)		# right stripe
  brain.img_fpath = 'R10_11'; brain.img_crop=(250,450)
  brain.img_fpath = 'opencv_6'; brain.img_crop=(250,450)
  brain.img_fpath = 'opencv_7'; brain.img_crop=(250,450)
  brain.img_fpath = 'opencv_7'; brain.img_crop=(300,200); brain.img_cropped_height=75
  brain.img_source_dir = '/volumes/pi/projects/vnavs/temp'
  brain.img_source_dir = 'samples'
  brain.img_fname_suffix = ''
  brain.img_fname_suffix = '_s'
  brain.do_filter_contours = True
  brain.do_filter_contours = False
  brain.FindLines()
  stop_time = time.clock()
  print("Elapsed Time:", (stop_time - start_time))

def test_ColorMask():
    fn = 'test_images/red_strap.jpeg'
    fn = 'test_images/red_strap_box.jpeg'
    fn = 'test_images/white_line.jpeg'
    im = cv2.imread(fn)
    bw = ColorMask(im, colors=[HSV_WHITE, HSV_RED], wthreshold=5)		# red, yellow

    cv2.imshow('c', im)
    cv2.imshow('bw', bw)
    cv2.waitKey()


def test_Cone():
    # Setup SimpleBlobDetector parameters.
    params = cv2.SimpleBlobDetector_Params()

    # Change thresholds
    params.minThreshold = 0;
    params.maxThreshold = 256;

    # Filter by Area.
    params.filterByArea = True
    params.minArea = 30

    # Filter by Circularity
    params.filterByCircularity = False
    params.minCircularity = 0.1

    # Filter by Convexity
    params.filterByConvexity = True
    params.filterByConvexity = False
    params.minConvexity = 0.5

    # Filter by Inertia
    params.filterByInertia = True
    params.filterByInertia = False
    params.minInertiaRatio = 0.01
    params.minInertiaRatio = 0.50

    # Create a detector with the parameters
    ver = (cv2.__version__).split('.')
    if int(ver[0]) < 3 :
        detector = cv2.SimpleBlobDetector(params)
    else :
        detector = cv2.SimpleBlobDetector_create(params)



    fn = 'samples/cone_s.jpeg'
    im = cv2.imread(fn)
    r = Robogames(im)
    r.ProcessLines()
    bw = r.annotated

    #bw = ColorMask(im, colors=[HSV_RED], threshold=150)
    #bw = np.bitwise_xor(bw, 255)
    #canny_image = auto_canny(bw, 0.33)
    #edges, im = HoughLines(im, bw)
    #(imgxx, opencv_contours, hierarchy) = cv2.findContours(bw.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    #(opencv_contours, hierarchy) = cv2.findContours(canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    #print("ContourCt", len(opencv_contours))
    #big_area = 0
    #big_ix = 0
    #for ix, this in enumerate(opencv_contours):
    #    area = cv2.contourArea(this)
    #    if area > big_area:
    #      big_area = area
    #      bix_ix = ix
    #outline_color = (0, 255, 0)	# green
    #opencv_color = (255, 0, 0)	# red
    #path_guide_color = (0, 255, 255)
    #cv2.drawContours(im, opencv_contours, big_ix, outline_color, -1)

    #keypoints = detector.detect(bw)

    # Draw detected blobs as red circles.
    # cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS ensures the size of the circle corresponds to the size of blob
    #im = cv2.drawKeypoints(im, keypoints, np.array([]), (0,0,255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)

    cv2.imshow('c', im)
    cv2.imshow('bw', bw)
    cv2.waitKey()
if __name__ == '__main__':
  #test_ColorMask()
  test_Cone()
