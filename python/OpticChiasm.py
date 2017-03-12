import os, cv2, numpy as np
import math
import time
#from scipy import weave
import sys
import re


# automatically set threshold using technique from 
# http://www.pyimagesearch.com/2015/04/06/zero-parameter-automatic-canny-edge-detection-with-python-and-opencv/
# just saw URL, and have seen it before, so that's re-assuring that I like it
def auto_canny(img_to_canny, auto_canny_sigma):
    img_to_canny_median = np.median(img_to_canny)
    lower_canny_thresh = int(max(0, (1 - auto_canny_sigma) * img_to_canny_median ))
    upper_canny_thresh = int(max(255, (1 + auto_canny_sigma) * img_to_canny_median ))
    return cv2.Canny(img_to_canny,lower_canny_thresh,upper_canny_thresh)


def apply_mask(channel, mask, fill_value):
    masked = np.ma.array(channel, mask=mask, fill_value=fill_value)
    return masked.filled()

def apply_threshold(channel, low_value, high_value):
    low_mask = channel < low_value
    channel = apply_mask(channel, low_mask, low_value)

    high_mask = channel > high_value
    channel = apply_mask(channel, high_mask, high_value)

    return channel

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

        print "Lowval: ", low_val
        print "Highval: ", high_val

        # saturate below the low percentileile and above the high percentileile
        thresholded = apply_threshold(channel, low_val, high_val)
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
  edges = cv2.Canny(gray.copy() ,100,200,apertureSize = 3)	# app size is 3, 5 or 7
  #edges = auto_canny(gray.copy(), 0.33)

  minLineLength = 30
  maxLineGap = 5
  maxLineGap = 1
  maxLineGap = 10
  rho = 30
  rho = 90
  rho = 1
  theta = np.pi / 180
  threshold = 15
  threshold = 1
  lines = cv2.HoughLinesP(edges, rho, theta, threshold, minLineLength,maxLineGap)
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
  return c + ' ' + `color`

def FilterContours(img, contours, SelectColors='r'):
  image_shape = img.shape
  mask_shape = (image_shape[0], image_shape[1], 1)
  final = img.copy()
  mask = np.zeros(mask_shape, np.uint8)
  area_threshold = 90	 # minimum area sized contour to draw
  area_threshold = 05	 # minimum area sized contour to draw
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
            print fpath
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

if __name__ == '__main__':
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

