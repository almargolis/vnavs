import math
import os
import sys
import time

import cv2
import numpy as np

from cvpipeline import opticchiasm as oc


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


#
# BGR / RGB Conversions
# thanks to https://www.scivision.co/numpy-image-bgr-to-rgb/
#
def bgr2rgb(bgr):
    # OpenCV image to Matplotlib or Pillow Image.fromarray()
    return bgr[..., ::-1]


def rgb2bgr(rgb):
    # image to OpenCV
    return rgb[..., ::-1]


def bgr2gray(bgr):
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


class ColorBalance:
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
            flat = np.sort(flat)  # sort this channel (R, G or B) by intensity
            n_cols = flat.shape[0]
            # I added the int(). Floor retuns a float. Flat doesn't want a float. This probably was written
            # for python 3 which does some of these conversions differently.
            self.low_vals.append(flat[int(math.floor(n_cols * half_percentile))])
            self.high_vals.append(
                flat[int(math.ceil(n_cols * (1.0 - half_percentile)))]
            )
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
            normalized = cv2.normalize(
                thresholded, thresholded.copy(), 0, 255, cv2.NORM_MINMAX
            )
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
    return I & ~M


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
    # src = cv2.imread("kanji.png")
    # if src == None:
    # 	sys.exit()
    bw = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
    _, bw2 = cv2.threshold(bw, 10, 255, cv2.THRESH_BINARY)
    bw2 = thinning(bw2)
    return bw2
    cv2.imshow("src", bw)
    cv2.imshow("thinning", bw2)
    cv2.waitKey()


def contour_lines(img, gray, drawlines=False, draw_both=False):
    # canny edge detection
    # bw_edged = auto_canny(gray, 0.33)
    bw_edged = cv2.Canny(gray, 30, 200)
    cont2, contours, hierarchy = cv2.findContours(
        bw_edged.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    # cont2, contours, hierarchy = cv2.findContours(bw_edged.copy(),cv2.RETR_TREE,cv2.CHAIN_APPROX_TC89_L1)
    if len(img.shape) == 2:
        cropped_height, cropped_width = img.shape
    else:
        cropped_height, cropped_width, cropped_channels = img.shape
    (tiny, vertical, horizontal) = create_contours(
        contours, cropped_width, cropped_height
    )
    if drawlines or draw_both:
        contoured_image = draw_contour_lines(img.copy(), tiny, (128, 128, 0))
        contoured_image = draw_contour_lines(contoured_image, vertical, (128, 128, 0))
        contoured_image = draw_contour_lines(contoured_image, horizontal, (128, 128, 0))
    else:
        contoured_image = img.copy()
    if (not drawlines) or draw_both:
        contoured_image = cv2.drawContours(
            contoured_image.copy(), tiny, -1, (128, 0, 128), 1
        )
        contoured_image = cv2.drawContours(
            contoured_image.copy(), vertical, -1, (0, 255, 0), 1
        )
        contoured_image = cv2.drawContours(
            contoured_image.copy(), horizontal, -1, (255, 0, 0), 1
        )
    dump_contours(contours)
    return bw_edged, contoured_image


#
# The draw contour functions take an image and set of contours and
# return a new image with the contours drawn in some way.
#


def draw_contour_filled(img, contours):
    image_shape = img.shape
    mask_shape = (image_shape[0], image_shape[1], 1)
    final = img.copy()
    mask = np.zeros(mask_shape, np.uint8)

    for i in range(len(contours)):
        # if len(contours[i]) < 9:
        #  continue
        mask[...] = 0  # zero out mask
        mask = cv2.drawContours(mask, contours, i, 255, -1)  # draw contour on mask
        avg_color = (255, 0, 0)
        avg_color = cv2.mean(img, mask)
        avg_color = (int(avg_color[0]), int(avg_color[1]), int(avg_color[2]))
        white_threshold = 175
        white_threshold = 0
        if white_threshold > 0:
            if (
                (avg_color[0] < white_threshold)
                and (avg_color[1] < white_threshold)
                and (avg_color[2] < white_threshold)
            ):
                avg_color = (0, 0, 0)
                avg_color = (0, 0, 255)
            else:
                avg_color = (255, 255, 255)
        # black_threshold = 128
        # if (avg_color[0] > black_threshold) and (avg_color[1] > black_threshold) and (avg_color[2] > black_threshold):
        #  avg_color = (255, 255, 255)
        cv2.drawContours(
            final, contours, i, avg_color, -1
        )  # draw filled countour, using avg color
        # cv2.drawContours(final, contours, i, (0,0,255), 1)    # draw contour outlines
    return final


def draw_contour_lines(img, contours, color):
    h, w, channels = img.shape
    origin_x = int(w / 2)
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
        line = calc_rect_centerline(rect, w, h)
        cv2.line(img, line[0], line[1], color, 2)
    return img


def crayola_filter2(im, bw_threshold=20, mix_threshold=50):
    # im = simplest_cb(im, 20)
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    mask = np.asarray([224, 224, 224], dtype=np.uint8)
    mask = np.asarray([192, 128, 128], dtype=np.uint8)
    mask = np.asarray([192, 192, 192], dtype=np.uint8)
    mask = np.asarray([224, 128, 128], dtype=np.uint8)
    out = cv2.bitwise_and(hsv, mask)
    im = cv2.cvtColor(out, cv2.COLOR_HSV2BGR)
    bw = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    canny_image = oc.auto_canny(bw, 0.33)
    (imgxx, opencv_contours, hierarchy) = cv2.findContours(
        canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    im = cv2.drawContours(im, opencv_contours, -1, (255, 0, 255), 1)
    # return canny_image
    return im


def crayola_filter(im, bw_threshold=20, mix_threshold=50):
    color_map = {
        "b": np.asarray([0, 0, 0], dtype=np.uint8),
        "w": np.asarray([255, 255, 255], dtype=np.uint8),
        "l": np.asarray([255, 0, 0], dtype=np.uint8),
        "g": np.asarray([0, 255, 0], dtype=np.uint8),
        "r": np.asarray([0, 0, 255], dtype=np.uint8),
        "y": np.asarray([0, 128, 128], dtype=np.uint8),
        "z": np.asarray([128, 128, 128], dtype=np.uint8),
    }
    height, width, channels = im.shape
    out_im = np.zeros(im.shape, np.uint8)
    for y in range(height):
        for x in range(width):
            color = im[y, x]  # BGR
            t = color_string(color, bw_threshold=bw_threshold, mix_threshold=mix_threshold)
            tc = t[0]
            if tc in color_map:
                c_out = color_map[tc]
            else:
                c_out = color_map["z"]
            print(y, x, t, color, c_out)
            out_im[y, x] = c_out
    return out_im


def color_string(color, bw_threshold=20, mix_threshold=50):
    # bw_sthreshold of 30 was about right for white line
    min_v = min(color)
    max_v = max(color)
    blue = color[0]
    green = color[1]
    red = color[2]
    if (max_v - min_v) < bw_threshold:
        if min_v > 128:
            c = "white"
        else:
            c = "black"
    elif blue >= max_v:
        c = "l-blue"
    elif green >= max_v:
        if abs(green - red) < mix_threshold:
            c = "yellow"
        else:
            c = "green"
    else:
        c = "red"
    return c + " " + repr(color)


def slope_of_list_of_rotated_rect(list_of_rects):
    [vx, vy, x, y] = cv2.fitLine(points, cv2.DIST_L1, 0, 0.01, 0.01)
    print("slope", float(vy / vx))
    left_y = int((-x * vy / vx) + y)
    right_y = int(((width - x) * vy / vx) + y)

    if (left_y >= 0) and (left_y <= height) and (right_y >= 0) and (right_y <= height):
        vert_line = ((width - 1, right_y), (0, left_y))


def calc_rect_centerline(cvRect):
    # Box2D: center (x,y), (width, height), angle of rotation
    box_x = cvRect[0][0]
    box_y = cvRect[0][1]
    box_w = cvRect[1][0]
    box_h = cvRect[1][1]
    hyp = box_h / 2
    box_r = math.radians(-cvRect[2])
    print("deg", cvRect[2], "rad", box_r, math.sin(box_r), math.cos(box_r))
    y_offset = int(hyp * math.cos(box_r))
    x_offset = int(hyp * math.sin(box_r))
    return (
        (int(box_x + x_offset), int(box_y + y_offset)),
        (int(box_x - x_offset), int(box_y - y_offset)),
    )


def create_contours(src, w, h):
    origin_x = int(w / 2)
    origin_y = 0
    horizon_x = origin_x
    horizon_y = h
    tiny = []
    vertical = []
    horizontal = []
    for this_c in src:
        if len(this_c) < 4:
            # not enough vertices
            # tiny.append(this_c)
            continue
        brec = cv2.boundingRect(this_c)
        # if brec[1] < 30:
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
        print(calc_rect_centerline(rect, w, h))
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
        # vertical.append(box)
        vertical.append(this_c)
    #
    print(len(tiny), len(vertical), len(horizontal))
    return (tiny, vertical, horizontal)


def dump_contours(contours):
    c_l = len(contours)
    print("Contours len: ", c_l)
    for ix, this_c in enumerate(contours):
        for iy, this_vertex in enumerate(this_c):
            print("C[%d-%d] %s" % (ix, iy, this_vertex))


def find_vertices(contour):
    ul = contour[0]
    ur = contour[0]
    ll = contour[0]
    rr = contour[0]
    for ix, this_v in enumerate(contour):
        if this_v[0] < ul[0]:
            pass


class ReflexEntities:
    def __init__(self, image, process="CY", colors="WRY"):
        color_list = []
        for this in colors:
            if this == "W":
                color_list.append(oc.HSV_WHITE)
            elif this == "R":
                color_list.append(oc.HSV_RED)
            elif this == "Y":
                color_list.append(oc.HSV_YELLOW)
            elif this == "B":
                color_list.append(oc.HSV_BLUE)
        # im is an OpenCV BGR image object
        self.original = image
        self.image = image
        for this in process:
            if this == "B":
                # print("simplest_cb")
                self.image = oc.simplest_cb(self.image.copy(), 20)
            elif this == "C":
                # print("color_mask", color_list)
                self.image = oc.color_mask(
                    self.image.copy(),
                    colors=color_list,
                    threshold=RACE_THRESHOLD,
                    wthreshold=RACE_WTHRESHOLD,
                )  # red, white
            elif this == "E":
                self.image = cv2.equalizeHist(self.image.copy())
            elif this == "G":
                self.image = cv2.GaussianBlur(self.image.copy(), (5, 5), 0)
            elif this == "W":
                self.image = bgr2gray(self.image)
            elif this == "Y":
                # print("Canny")
                self.image = oc.auto_canny(self.image.copy(), 0.1)  # ben's sigma was 0.33
        self.h_lines = cv2.HoughLinesP(
            self.image, 1, np.pi / 180, 15, minLineLength=30, maxLineGap=10
        )
        # if self.h_lines is None:
        #    print("LINES -- NONE")
        # else:
        #    print("LINES", len(self.h_lines))
        self.map_lines = []
        self.avg_slope = 0

    def process_lines(self):
        VERTICAL_SLOPE = 9999
        h_color = (0, 0, 255)  # blue
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
        m = int(w / 2)
        if self.h_lines is not None:
            for x in range(0, len(self.h_lines)):
                for x1, y1, x2, y2 in self.h_lines[x]:
                    # cv2.line(self.annotated,(x1,y1),(x2,y2), h_color, h_width)
                    # deposition += "%d. (%d,%d) (%d,%d)\n" % (x, x1, y1, x2, y2)
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
                    mlen = math.sqrt((mrise**2) + (mrun**2))
                    p1dist = math.sqrt((mx1**2) + (my1**2))
                    p2dist = math.sqrt((mx2**2) + (my2**2))
                    mdist = min(p1dist, p2dist)
                    if mdist < 300:
                        self.map_lines.append(
                            (
                                mdist,
                                mlen,
                                mslope,
                                (mx1, my1),
                                (mx2, my2),
                                (x1, y1),
                                (x2, y2),
                                mrise,
                                mrun,
                            )
                        )
            self.map_lines.sort()
            print(self.map_lines[0])
            # print("Map Lines", len(self.map_lines))
            p1 = self.map_lines[0][5]
            p2 = self.map_lines[0][6]
            x1 = int((p1[0] + p2[0]) / 2)
            y1 = int((p1[1] + p2[1]) / 2)
            m = self.map_lines[0][2]
            return (x1, y1, m)
        else:
            return None

    def annotate_full_image(self, image, linect=10, x1=0, y1=0, color=None):
        if color is None:
            color = (0, 255, 0)  # green
        a_width = 5
        for this in self.map_lines[:linect]:
            p1 = (this[5][0] + x1, this[5][1] + y1)
            p2 = (this[6][0] + x1, this[6][1] + y1)
            cv2.line(image, p1, p2, color, a_width)

    def analyze_lines(self):
        cum_slope = 0
        ct_slope = 0
        if len(self.map_lines) < 1:
            return
        for this in self.map_lines[:1]:
            cv2.line(self.annotated, this[5], this[6], a_color, a_width)
            # print(this)
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
        cv2.imwrite("temp/ann.jpeg", self.annotated)


class Robogames:
    def __init__(self, image, colors):
        # im is an OpenCV BGR image object
        self.original = image
        self.green = (0, 255, 0)  # green
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
            print(
                "Crop: (%d, %d) start (%d, %d) width %d"
                % (width, height, c_x, c_y, c_w)
            )
            image = image[c_y:height, c_x : c_x + c_w]
        self.annotated = image.copy()
        # image = simplest_cb(self.original, 20)
        image = oc.color_mask(image, colors=colors)
        # bw_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # bw_image = cv2.blur(bw_image.copy(), (5,5))
        if RACE_BLUR:
            image = cv2.GaussianBlur(image.copy(), (5, 5), 0)
        if RACE_CANNY:
            image = oc.auto_canny(image, 0.33)
        # (imgxx, opencv_contours, hierarchy) = cv2.findContours(canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        self.h_lines = cv2.HoughLinesP(
            image, 1, np.pi / 180, 15, minLineLength=50, maxLineGap=30
        )
        self.map_lines = []
        self.avg_slope = 0

    def process_lines(self):
        VERTICAL_SLOPE = 9999
        h_color = (0, 0, 255)  # blue
        h_width = 1
        a_width = 2
        self.map_lines = []
        self.avg_slope = 0
        self.slope_ct = 0
        h, w, c = self.annotated.shape
        m = int(w / 2)
        if self.h_lines is not None:
            for x in range(0, len(self.h_lines)):
                for x1, y1, x2, y2 in self.h_lines[x]:
                    cv2.line(self.annotated, (x1, y1), (x2, y2), h_color, h_width)
                    # deposition += "%d. (%d,%d) (%d,%d)\n" % (x, x1, y1, x2, y2)
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
                    mlen = math.sqrt((mrise**2) + (mrun**2))
                    p1dist = math.sqrt((mx1**2) + (my1**2))
                    p2dist = math.sqrt((mx2**2) + (my2**2))
                    mdist = min(p1dist, p2dist)
                    mdist = mlen
                    # mx, mx are transposed to origin at bottom center
                    # x, y are opencv origin upper/left
                    self.map_lines.append(
                        (
                            mdist,
                            mlen,
                            mslope,
                            (mx1, my1),
                            (mx2, my2),
                            (x1, y1),
                            (x2, y2),
                        )
                    )
            self.map_lines.sort()

    def filter_lines(self):
        cum_slope = 0
        ct_slope = 0
        # print("MAP", h, m, w)
        self.filtered_lines = []
        for this in self.map_lines[:5]:
            slope = abs(this[2])
            print(slope)
            # if (slope < 4) or (slope > 18):
            # if slope > 1:
            #    continue
            p1 = this[5]
            p2 = this[6]
            middleX = int((p1[0] + p2[0]) / 2)
            self.filtered_lines.append((middleX, this))

    def select_lines(self):
        print("FILTERED", len(self.filtered_lines))
        self.rectangles = []
        self.selectedLines = []
        Allpoints = []
        for thisX in self.filtered_lines:
            this = thisX[1]
            points = [this[5], this[6]]
            Allpoints += points
        self.make_rec(Allpoints)

    def select_cone(self):
        self.selectedLines = []
        if len(self.filtered_lines) >= 2:
            # we need two lines to form a cone
            self.filtered_lines.sort()
            for ix, this in enumerate(self.filtered_lines[:-1]):
                l1 = this[1]
                l2 = self.filtered_lines[ix + 1][1]
                slope1 = l1[2]
                slope2 = l2[2]
                if (slope1 > 0) and (slope2 < 0):
                    self.selectedLines.append((l1, l2))

    def make_cone_rec(self):
        self.rectangles = []
        for this in self.selectedLines:
            points = [this[0][5], this[0][6], this[1][5], this[1][6]]
            self.make_rec(points)

    def make_rec(self, points):
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


def draw_grid(img):
    grid_incr = 25
    height, width, channels = img.shape
    for x in range(grid_incr, width, grid_incr):
        cv2.line(img, (x, 0), (x, width), (255, 0, 0), 1)
    for y in range(grid_incr, height, grid_incr):
        cv2.line(img, (0, y), (width, y), (255, 0, 0), 1)


def mean(numbers):
    if len(numbers) == 0:
        return 0
    return sum(numbers) / len(numbers)


def test_old():
    fn = "R20170325021241_1_0001.jpeg"
    fn = "R20170325021241_2_0001.jpeg"
    im = cv2.imread("temp/" + fn)
    p = Race(im)
    p.process_lines()
    sys, exit(0)

    start_time = time.clock()
    brain = ImageAnalyzer()
    brain.img_fpath = "opencv_3"
    brain.img_crop = (350, 150)  # distance calibration
    brain.img_fpath = "opencv_1"
    brain.img_crop = (450, 75)  # center stripe
    brain.img_fpath = "opencv_1"
    brain.img_crop = (600, 75)  # right stripe
    brain.img_fpath = "opencv_4"
    brain.img_crop = (550, 75)  # right stripe
    brain.img_fpath = "R10_11"
    brain.img_crop = (250, 450)
    brain.img_fpath = "opencv_6"
    brain.img_crop = (250, 450)
    brain.img_fpath = "opencv_7"
    brain.img_crop = (250, 450)
    brain.img_fpath = "opencv_7"
    brain.img_crop = (300, 200)
    brain.img_cropped_height = 75
    brain.img_source_dir = "/volumes/pi/projects/vnavs/temp"
    brain.img_source_dir = "samples"
    brain.img_fname_suffix = ""
    brain.img_fname_suffix = "_s"
    brain.do_image_filter_contours = True
    brain.do_image_filter_contours = False
    brain.find_lines()
    stop_time = time.clock()
    print("Elapsed Time:", (stop_time - start_time))


def test_color_mask():
    fn = "test_images/red_strap.jpeg"
    fn = "test_images/red_strap_box.jpeg"
    fn = "test_images/white_line.jpeg"
    im = cv2.imread(fn)
    bw = oc.color_mask(im, colors=[oc.HSV_WHITE, oc.HSV_RED], wthreshold=5)  # red, yellow

    cv2.imshow("c", im)
    cv2.imshow("bw", bw)
    cv2.waitKey()


def test_cone():
    # Setup SimpleBlobDetector parameters.
    params = cv2.SimpleBlobDetector_Params()

    # Change thresholds
    params.minThreshold = 0
    params.maxThreshold = 256

    # Filter by Area.
    params.image_filterByArea = True
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
    ver = (cv2.__version__).split(".")
    if int(ver[0]) < 3:
        detector = cv2.SimpleBlobDetector(params)
    else:
        detector = cv2.SimpleBlobDetector_create(params)

    fn = "samples/cone_s.jpeg"
    im = cv2.imread(fn)
    r = Robogames(im)
    r.process_lines()
    bw = r.annotated

    # bw = color_mask(im, colors=[HSV_RED], threshold=150)
    # bw = np.bitwise_xor(bw, 255)
    # canny_image = auto_canny(bw, 0.33)
    # edges, im = HoughLines(im, bw)
    # (imgxx, opencv_contours, hierarchy) = cv2.findContours(bw.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    # (opencv_contours, hierarchy) = cv2.findContours(canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    # print("ContourCt", len(opencv_contours))
    # big_area = 0
    # big_ix = 0
    # for ix, this in enumerate(opencv_contours):
    #    area = cv2.contourArea(this)
    #    if area > big_area:
    #      big_area = area
    #      bix_ix = ix
    # outline_color = (0, 255, 0)	# green
    # opencv_color = (255, 0, 0)	# red
    # path_guide_color = (0, 255, 255)
    # cv2.drawContours(im, opencv_contours, big_ix, outline_color, -1)

    # keypoints = detector.detect(bw)

    # Draw detected blobs as red circles.
    # cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS ensures the size of the circle corresponds to the size of blob
    # im = cv2.drawKeypoints(im, keypoints, np.array([]), (0,0,255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)

    cv2.imshow("c", im)
    cv2.imshow("bw", bw)
    cv2.waitKey()


if __name__ == "__main__":
    # test_color_mask()
    # test_cone()
    pass
