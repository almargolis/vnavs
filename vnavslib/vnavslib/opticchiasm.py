# from __future__ import absolute_import, division, print_function
# from past.builtins import basestring    # pip install future
# from builtins import (bytes, str, open, super, range,
#                      zip, round, input, int, pow, object)

import io
import importlib
import os, cv2, numpy as np
import math
import time

# from scipy import weave
from operator import itemgetter
import sys
import re

# OpenCv uses a range of 0 to HSV_MAX_HUE instead of 0 to 360.
# old, non-working values were yellow=30, orange=12, blue=120, red=178
HSV_MAX_HUE = 179
HSV_RATIO = float(HSV_MAX_HUE) / 360.0
HSV_WHITE = -1
HSV_YELLOW = int(70.0 * HSV_RATIO)
HSV_ORANGE = int(60.0 * HSV_RATIO)
HSV_BLUE = int(240.0 * HSV_RATIO)
HSV_RED = int(350.0 * HSV_RATIO)

# These are OpenCv compatible codes.
# Picamera uses lower case and also supports other formats.
IM_BGR = "BGR"
IM_GRAY = "GRAY"
IM_HSL = "HSL"
IM_HSV = "HSV"
IM_RGB = "RGB"
IM_YUV = "YUV"
IM_COLORCODES = [IM_BGR, IM_GRAY, IM_HSL, IM_HSV, IM_RGB, IM_YUV]

DRAW_BGR_RED = (0, 0, 255)
DRAW_BGR_MAGENTA = (255, 0, 255)
DRAW_BGR_BLUE = (255, 0, 0)
DRAW_BGR_GREEN = (0, 255, 0)
DRAW_BGR_YELLOW = (0, 255, 255)
DRAW_BGR_CYAN = (255, 255, 0)
DRAW_BGR_BLACK = (0, 0, 0)
DRAW_BGR_WHITE = (255, 255, 255)
DRAW_COLORS = (
    DRAW_BGR_GREEN,
    DRAW_BGR_RED,
    DRAW_BGR_BLUE,
    DRAW_BGR_YELLOW,
    DRAW_BGR_MAGENTA,
    DRAW_BGR_CYAN,
)
color_ix = -1


#
# OpenCv images are numpy arrays
#   [0,0] is the upper, left corner of the image
#   The image is stored as an array of horizontal lines, so the index is [y, x]
#
def repr_opencv(im):
    imx = Image(im=im, colorcode=IM_BGR)
    return imx.__repr__()


class Image:
    """
    Image is a wrapper around OpenCv images. Its main unique value is adding colorcode as a property
    of the image, avoiding a variety of bugs. It also provides convenience functions to deal with
    OpenCv and numpy operations that I find non-intuitive.
    """

    __slots__ = (
        "colorcode",
        "colordepth",
        "crop_source",
        "crop_x",
        "crop_y",
        "file_path",
        "height",
        "_im",
        "shape",
        "width",
    )

    def __init__(self, im=None, colorcode=None, opencv_fn=None):
        self.file_path = opencv_fn
        if opencv_fn is not None:
            im = cv2.imread(opencv_fn)
            colorcode = IM_BGR
        if colorcode is not None:
            colorcode = colorcode.upper()  # change picamera format to OpenCv
        self.crop_source = None  # Image() from which this is cropped
        self.crop_x = None  # left x starting position of this crop in source image
        self.crop_y = None  # upper y` starting position of this crop in source image
        self.replace_image(im, colorcode)

    def __repr__(self):
        return "Image {}x{}x{} {}".format(
            self.width, self.height, self.colordepth, self.colorcode
        )

    def copy(self):
        if self._im is None:
            return Image(im=None, colorcode=self.colorcode)
        else:
            return Image(im=self._im.copy(), colorcode=self.colorcode)

    def copy_as_bgr(self):
        if self.colorcode == IM_BGR:
            return self.copy()
        transform = getattr(cv2, "COLOR_{}2{}".format(self.colorcode, IM_BGR))
        return Image(im=cv2.cvtColor(self._im, transform), colorcode=IM_BGR)

    def copy_as_gray(self):
        if self.colorcode == IM_GRAY:
            return self.copy()
        transform = getattr(cv2, "COLOR_{}2{}".format(self.colorcode, IM_GRAY))
        return Image(im=cv2.cvtColor(self._im, transform), colorcode=IM_GRAY)

    @property
    def im(self):  # im is a property to discourage skipping replace_image()
        return self._im

    def im_as_bgr(self):
        return self.im_as_any(IM_BGR)

    def im_as_rgb(self):
        return self.im_as_any(IM_RGB)

    def im_as_hsv(self):
        return self.im_as_any(IM_HSV)

    def im_as_gray(self, copy=False):
        if self.colorcode == IM_GRAY:
            if copy:
                return self._im.copy()
            else:
                return self._im
        return self.im_as_any(IM_GRAY)

    def im_as_any(self, colorcode, copy=False):
        # print("im_as_any()", self.colorcode, colorcode, self._im.__class__.__name__)
        if self._im is None:
            return None
        colorcode = colorcode.upper()
        if not colorcode in IM_COLORCODES:
            return None
        if self.colorcode == colorcode:
            if copy:
                return self._im.copy()
            else:
                return self._im
        transform = getattr(cv2, "COLOR_{}2{}".format(self.colorcode, IM_HSV), None)
        if transform is None:
            return None
        return cv2.cvtColor(self._im, transform)

    def replace_image(self, im, colorcode):
        if not colorcode in IM_COLORCODES:
            raise ValueError(f"Invalid colorcode '{colorcode}")
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
        self.shape = (self.height, self.width, self.colordepth)

    def write(self, fn=None):
        if fn is None:
            fn = self.file_path
        cv2.imwrite(fn, self.im_as_bgr())
        # except IOError as e:
        # IOError: [Errno 28] Out of disk space
        #                    if e.errno == 28:

    def average_hue(self, rect=None):
        if rect is None:
            hsv = self.im_as_hsv()
        else:
            hsv = self.crop(rect).im_as_hsv()
        average_color = hsv[:, :, 0].mean()
        return average_color

    def crop(self, rect, isolate=False):
        # print("crop()", rect)
        if rect is None:
            return self.copy()
        new_image = Image(
            im=self._im[
                rect.y_min : rect.y_max + 1, rect.x_min : rect.x_max + 1
            ].copy(),
            colorcode=self.colorcode,
        )
        if not isolate:
            new_image.crop_source = self
            new_image.crop_x = rect.x_min
            new_image.crop_y = rect.y_min
        return new_image

    def draw_line_points(self, linepoints, color=DRAW_BGR_GREEN, thickness=2):
        # Annotates an array of RightRect or RotatedRect from chase_line() or elsewhere
        if linepoints is not None:
            for this in linepoints:
                cv2.rectangle(self._im, this.p1, this.p2, color, thickness)

    def draw_rectangle(self, rect, color=DRAW_BGR_GREEN, thickness=2):
        cv2.rectangle(self._im, rect.p1, rect.p2, color, thickness)

    def right_rect_from_symbolic_yx(self, y_range, x_range):
        return right_rect_from_symbolic_yx(self._im, y_range, x_range)

    def right_rect_from_symbolic_pp(self, p1, p2):
        return right_rect_from_symbolic_pp(self._im, p1, p2)

    def chase_line(
        self, hsvspec, rect, end_y=0, sliceheight=20, kernel_dim=3, iterations=1
    ):
        # don't modify source specs, make a working copy to step through
        if (hsvspec is None) or (rect is None):
            return None
        line_hsvspec = hsvspec.copy()
        line_rect = rect.copy()
        chase_ct = 0
        min_blob_area = 10
        min_blob_area = 1
        min_blob_area = (sliceheight * 0.5) * 3  # 1/2 slice height by 3 pixels
        max_missing = 2
        print("chase_line()", self, line_hsvspec, line_rect)

        def QualifyLineSegment():
            global next_hsv_spec
            # This advances the search through the image. Adjusting line_hsvspec and line_rect.
            # check if the blob is reasonably a line segment
            # size? color? location?
            # print("chase_line() Qualify", line_hsvspec, line_rect)
            blobs, next_hsv_spec = self.find_color_blobs(
                hsvspec=line_hsvspec,
                rect=line_rect,
                kernel_dim=kernel_dim,
                iterations=iterations,
                minimum_blob_area=min_blob_area,
                maximum_ct_of_rects_wanted=1,
            )
            if (blobs is None) or (len(blobs) < 1):
                return None, None
            return blobs[0], next_hsv_spec

        def AdvanceLineSearch(prev_segment):
            # adjust hsvspec and rect for next slice
            # +/- x, match color and intensity
            line_rect.y_min, line_rect.y_max = (
                line_rect.y_min - sliceheight,
                line_rect.y_min,
            )
            if line_rect.y_min < end_y:
                return False  # past top of image
            if prev_segment is not None:
                # else, leave x alone. maybe should advance like prev good segment
                line_rect.x_min = int(prev_segment.center_x - (prev_segment.width * 2))
                if line_rect.x_min < 0:
                    line_rect.x_min = 0
                line_rect.x_max = int(prev_segment.center_x + (prev_segment.width * 2))
                if line_rect.x_max >= self.width:
                    line_rect.x_max = self.width - 1
                if (line_rect.x_max - line_rect.x_min) < prev_segment.width:
                    return False  # shifted too close to left/right edge
            return True

        line_points = []
        missing_slices = 0
        while True:
            chase_ct += 1
            print(
                "chase_line() Loop",
                chase_ct,
                missing_slices,
                line_points,
                line_hsvspec,
                line_rect,
            )
            this_segment, this_hsvspec = QualifyLineSegment()
            if this_segment is None:
                missing_slices += 1
            else:
                missing_slices = 0
                line_points.append(this_segment)
            if this_hsvspec is not None:
                line_hsvspec = this_hsvspec
            if (missing_slices > max_missing) or (not AdvanceLineSearch(this_segment)):
                # Missing_slices image_filters for reasonably continuous lines.
                # Added because when line was lost this was finding random blobs to chase
                # far from line. If following dashed line, we might want a more cyclic check.
                # False positives are worse than false negatives.
                return line_points

    def find_color_blobs(
        self,
        hsvspec,
        rect=None,
        kernel_dim=3,
        iterations=1,
        minimum_blob_area=1,
        maximum_ct_of_rects_wanted=3,
    ):
        # print("find_color_blobs()", self, rect, hsvspec)
        if rect is None:
            im_cropped = self
        else:
            im_cropped = self.crop(rect)
        im_hsv = im_cropped.im_as_hsv()
        im_masked = color_mask_one_hue(im_hsv, hsvspec)
        # print("find_color_blobs() Cropped " + repr_opencv(im_masked))
        kernel = np.ones((kernel_dim, kernel_dim), np.uint8)
        im_dilated = cv2.dilate(im_masked, kernel, iterations=iterations)
        cont2, contours, hierarchy = cv2.findContours(
            im_dilated.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )
        rotated_rect_list = contours_extract(
            contours,
            hierarchy,
            minimum_area=minimum_blob_area,
            maximum_ct_of_rects_wanted=maximum_ct_of_rects_wanted,
        )
        next_hsv_spec = None
        if (rotated_rect_list is not None) and (len(rotated_rect_list) > 0):
            # use im_masked because im_dilated includes out of range hsv values
            next_hsv_spec = next_hsv_spec_fn(
                im_hsv, mask=im_masked, rect=rotated_rect_list[0]
            )
            if rect is not None:
                for this in rotatated_rect_list:  # adjust to original image coordinates
                    this.center_x += rect.x_min
                    this.center_y += rect.y_min
        print("find_color_blobs()", rotated_rect_list)
        return rotated_rect_list, next_hsv_spec


def image_from_picamera(picam_image, format, file_path=None):
    # format is picamera style format
    img = Image()
    img.file_path = file_path
    if format == "bgr":
        img.replace_image(picam_image.array, IM_BGR)
    elif format == "rgb":
        img.replace_image(picam_image.array, IM_RGB)
    elif format == "yuv":
        img.replace_image(picam_image.array, IM_YUV)
    return img


#
# This is an interesting example of line locating
# https://github.com/naokishibuya/car-finding-lane-lines
#
# automatically set threshold using technique from
# http://www.pyimagesearch.com/2015/04/06/zero-parameter-automatic-canny-edge-detection-with-python-and-opencv/
# just saw URL, and have seen it before, so that's re-assuring that I like it
def auto_canny(grayscale_im, auto_canny_sigma):
    grayscale_im_median = np.median(grayscale_im)
    lower_canny_thresh = int(max(0, (1 - auto_canny_sigma) * grayscale_im_median))
    upper_canny_thresh = int(min(255, (1 + auto_canny_sigma) * grayscale_im_median))
    # print("auto_canny()", grayscale_im_median, lower_canny_thresh, upper_canny_thresh)
    # lower_canny_thresh = 100
    # upper_canny_thresh = 130
    return cv2.Canny(grayscale_im, lower_canny_thresh, upper_canny_thresh)


def apply_mask(channel, mask, fill_value):
    masked = np.ma.array(channel, mask=mask, fill_value=fill_value)
    return masked.filled()


def apply_threshold(channel, low_value, high_value):
    low_mask = channel < low_value
    channel = apply_mask(channel, low_mask, low_value)

    high_mask = channel > high_value
    channel = apply_mask(channel, high_mask, high_value)

    return channel


def cameraman_snapshot(im, path, fn):
    exfn = os.path.join(path, fn)
    with open(exfn, "r") as f:
        src = f.read()
    c = compile(src, "cvcode.py", "exec", dont_inherit=True)
    glb = {}
    glb["cv2"] = cv2
    glb["oc"] = importlib.import_module("OpticChiasm")
    loc = {}
    loc["im_base"] = im
    exec(c, glb, loc)
    return loc["display_image"]


def histogram_cb(img):
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
    # assert img.shape[2] == 3
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

        flat = np.sort(flat)  # sort this channel (R, G or B) by intensity

        n_cols = flat.shape[0]
        # I added the int(). Floor retuns a float. Flat doesn't want a float. This probably was written
        # for python 3 which does some of these conversions differently.
        low_val = flat[int(math.floor(n_cols * half_percentile))]
        high_val = flat[int(math.ceil(n_cols * (1.0 - half_percentile)))]

        # print "Lowval: ", low_val
        # print "Highval: ", high_val

        # saturate below the low percentileile and above the high percentileile
        thresholded = apply_threshold(channel, low_val, high_val)
        # scale the channel
        normalized = cv2.normalize(
            thresholded, thresholded.copy(), 0, 255, cv2.NORM_MINMAX
        )
        out_channels.append(normalized)

    return cv2.merge(out_channels)


def init_color():
    global color_ix
    color_ix = -1


def next_color():
    global color_ix
    color_ix += 1
    if color_ix >= len(DRAW_COLORS):
        color_ix = 0
    return DRAW_COLORS[color_ix]


def list_of_rotated_rect_as_list_of_dicts(in_list):
    # Takes list of RotatedRect and converts to a JSON serializable
    # list of dicts. The list is from Image.chase_line() or similar.
    res = []
    for this in in_list:
        res.append(object_as_dict(this))
    return res


def list_of_rotated_rect_from_list_of_dicts(in_list):
    # Takes a list of dicts and convert to a list
    # of RotatedRect
    if in_list is None:
        return []
    res = []
    for this in in_list:
        res.append(rotated_rect_from_dict(this))
    return res


def rotated_rect_from_dict(d):
    # print("rotated_rect_from_dict()", d)
    return RotatedRect(
        ((d["center_x"], d["center_y"]), (d["width"], d["height"]), d["angle"])
    )


def object_as_dict(src):
    res = {}
    for this in src.__slots__:
        res[this] = getattr(src, this)
    return res


class RotatedRect:
    __slots__ = ("angle", "center_x", "center_y", "height", "width")

    def __init__(self, rect):  # rect from cv2.minAreaRect() ((x, y), (w, h), angle)
        center = rect[0]
        dims = rect[1]
        self.angle = rect[2]
        self.center_x = center[0]
        self.center_y = center[1]
        self.width = dims[0]
        self.height = dims[1]

    def __repr__(self):
        return "(({center_x}, {center_y}), ({width}, {height}), {angle})".format(
            center_x=self.center_x,
            center_y=self.center_y,
            width=self.width,
            height=self.height,
            angle=self.angle,
        )

    def box_points_list(self):
        return cv2.boxPoints(self.as_rotated_rect()).tolist()  # returns array of 4 [x, y]

    def as_rotated_rect(self):
        return [[self.center_x, self.center_y], [self.width, self.height], angle]

    def top_y(self, x):
        # This is incomplete. Need to consider angle.
        # Return y coordinate of top line at position x.
        top = self.center_y - (self.height / 2.0)
        if top < 0.0:
            top = 0.0
        return top

    @property
    def center(self):
        return (self.center_x, self.center_y)

    @property
    def p1(self):
        # return upper/right corner point of right rectangle
        half_width = self.width / 2
        half_height = self.height / 2
        return (int(self.center_x - half_width), int(self.center_y - half_width))

    @property
    def p2(self):
        # return lower/left corner point of right rectangle
        half_width = self.width / 2
        half_height = self.height / 2
        return (int(self.center_x + half_width), int(self.center_y + half_width))


def rotated_rect_from_opencv_image(im):
    shape = im.shape
    height = shape[0]
    width = shape[1]
    center = (float(width / 2.0), float(height / 2.0))
    dims = (width, height)
    return RotatedRect((center, dims, 0.0))


def contours_extract(contours, hierarchy, minimum_area=1, maximum_ct_of_rects_wanted=3):
    # returns a list of the largest contours as minimum sized RotatedRect
    if hierarchy is None:
        return None
    # Scan contours, discarding small ones
    h_ix = 0
    discarded_contour_count = 0
    areas = []
    while h_ix >= 0:
        h = hierarchy[0, h_ix]
        cnt = contours[h_ix]
        area = cv2.contourArea(cnt)
        if area >= minimum_area:
            print("KEEP", area, minimum_area)
            areas.append((area, h_ix))
        else:
            print("DISC", area, minimum_area)
            discarded_contour_count = 0
        h_ix = h[0]
    areas.sort(reverse=True)  # sort from largest to smallest)
    rotated_rect_list = []
    for this in areas[: maximum_ct_of_rects_wanted + 1]:
        h_ix = this[1]
        cnt = contours[h_ix]
        rect = RotatedRect(cv2.minAreaRect(cnt))  # ((x, y), (w, h), angle)
        rotated_rect_list.append(rect)
    print("contours_extract()", rotated_rect_list)
    return rotated_rect_list


def contours_to_line_vectors(
    img, contours, hierarchy, minimum_area=1, maximum_ct_of_rects_wanted=3
):
    # This only looks at top level of hierarchy.
    # This analyzes contours and draws them on thee image -- modifying the image.
    # This is my original attempt for learning about / exploring.
    # I'm not working to make it obsolete, separating the analysis from the
    # drqwing with more structured data.
    #
    if hierarchy is None:
        return None
    print("VECTOR vvvvvvv")
    h_ix = 0
    areas = []
    while h_ix >= 0:
        h = hierarchy[0, h_ix]
        cnt = contours[h_ix]
        area = cv2.contourArea(cnt)
        if area >= minimum_area:
            areas.append((area, h_ix))
        h_ix = h[0]
    areas.sort(reverse=True)  # sort from largest to smallest)
    for this in areas[:maximum_ct_of_rects_wanted]:
        h_ix = this[1]
        cnt = contours[h_ix]
        rect = cv2.minAreaRect(cnt)
        box = cv2.boxPoints(rect).tolist()
        box.sort(key=itemgetter(1))  # sort by descending y-coordinate
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


def crayola_contours(img, contours, hierarchy, max_level=-1):
    def ColorBranch(ix, c, this_level, max_level):
        h = hierarchy[0, ix]
        c = NextColorIx(c)
        color = DRAW_COLORS[c]
        next_ix = h[0]
        child_ix = h[2]
        cnt = contours[ix]
        cv2.drawContours(img, [cnt], 0, color, -1)
        if (max_level < 0) or (this_level < max_level):
            while child_ix >= 0:
                child_ix = ColorBranch(child_ix, c, this_level + 1, max_level)
                c = NextColorIx(c)
        return next_ix

    if hierarchy is None:
        return img
    h_ix = 0
    h_color = -1
    while h_ix >= 0:
        h_ix = ColorBranch(h_ix, h_color, 1, max_level)
        h_color = NextColorIx(h_color)
    return img


def color_mask_white(hsv_channels, threshold=50):
    minValue = 255 - threshold
    maxSaturation = threshold
    ret, saturationMask = cv2.threshold(
        hsv_channels[1], maxSaturation, 255, cv2.THRESH_BINARY_INV
    )
    ret, valueMask = cv2.threshold(hsv_channels[2], minValue, 255, cv2.THRESH_BINARY)
    image_filterMask = cv2.bitwise_and(saturationMask, valueMask)
    return image_filterMask


class HsvSpec:
    __slots__ = (
        "hue",
        "huerange",
        "saturation",
        "saturationrange",
        "value",
        "valuerange",
    )

    def __init__(
        self,
        hue,
        huerange=25,
        saturation=205,
        saturationrange=50,
        value=205,
        valuerange=50,
    ):
        self.hue = hue
        self.huerange = huerange
        self.saturation = saturation
        self.saturationrange = saturationrange
        self.value = value
        self.valuerange = valuerange

    def __repr__(self):
        return "(H {} {} S {} {} V {} {})".format(
            self.hue,
            self.huerange,
            self.saturation,
            self.saturationrange,
            self.value,
            self.valuerange,
        )

    def as_payload(self):
        p = {}
        for this in self.__slots__:
            p[this] = getattr(self, this)
        return p

    def copy(self):
        return HsvSpec(
            hue=self.hue,
            huerange=self.huerange,
            saturation=self.saturation,
            saturationrange=self.saturationrange,
            value=self.value,
            valuerange=self.valuerange,
        )


def hsv_spec_from_payload(payload):
    if not ("hue" in payload):
        return None
    hue = int(payload["hue"])
    if "huerange" in payload:
        huerange = int(payload["huerange"])
    else:
        huerange = 25
    if "saturation" in payload:
        saturation = int(payload["saturation"])
    else:
        saturation = 205
    if "saturationrange" in payload:
        saturationrange = int(payload["saturationrange"])
    else:
        saturationrange = 50
    if "value" in payload:
        value = int(payload["value"])
    else:
        value = 205
    if "valuerange" in payload:
        valuerange = int(payload["valuerange"])
    else:
        valuerange = 50
    return HsvSpec(
        hue=hue,
        huerange=huerange,
        saturation=saturation,
        saturationrange=saturationrange,
        value=value,
        valuerange=valuerange,
    )


def next_hsv_spec_fn(hsvImage, mask=None, rotated_rect=None, minrange=20):
    # hsvImage is an OpenCvImage. rotated_rect is an RotatedRect.
    # Creates an HsvSpec based on the upper part of this image.
    # It considers only the center x and y from center to top.
    # Optionally considers only image pixels hilighted (>0) by mask.
    # Looks at either center of image or center of optional rect.
    # Used by Image.chase_line()
    def CalcRange(hist):
        # check if rng reasonable, avg close to hist[0], colorwrap
        avg = int((int(hist[1]) + int(hist[2])) / 2)
        rng = hist[2] - avg
        if rng < minrange:
            rng = minrange
        return avg, rng

    # print("next_hsv_spec_fn()", repr_opencv(hsvImage), repr_opencv(mask), rotated_rect)
    value_ct = 0
    values = []
    values.append([0, 255, 0])  # sum, min value, max value)
    values.append([0, 255, 0])  # sum, min value, max value)
    values.append([0, 255, 0])  # sum, min value, max value)
    if rotated_rect is None:
        rotated_rect = rotated_rect_from_opencv_image(hsvImage)
    x = int(rotated_rect.center_x)
    y = int(rotated_rect.center_y)
    top_y = int(rotated_rect.top_y(x))
    for this_y in range(y, top_y, -1):
        # print("next_hsv_spec_fn() Loop", this_y, x, hueMask[this_y, x], hsvImage[this_y, x])
        if (mask is None) or (mask[this_y, x] > 0):
            value_ct += 1
            hsv = hsvImage[this_y, x]
            for ix, this_byte in enumerate(hsv):
                values[ix][0] += this_byte
                if this_byte < values[ix][1]:
                    values[ix][1] = this_byte
                if this_byte > values[ix][2]:
                    values[ix][2] = this_byte
    if value_ct < 3:
        # print("next_hsv_spec_fn()", value_ct, None, values)
        return None
    hsv_spec = HsvSpec(0)
    hsv_spec.hue, hsv_spec.huerange = CalcRange(values[0])
    hsv_spec.saturation, hsv_spec.saturationrange = CalcRange(values[1])
    hsv_spec.value, hsv_spec.valuerange = CalcRange(values[2])
    # print("next_hsv_spec_fn()", value_ct, hsv_spec, values)
    return hsv_spec


def color_mask_one_hue(hsv_image, hsvspec):
    # In literature, hue space goes from 0 to 360 degrees, but OpenCV rescales the range to 0 up to HSV_MAX_HUE,
    # because 360 does not fit in a single byte. There is another mode where 0..360 is rescaled to 0..255 but this isn't as common.
    # Red color, value 0,  is one of the special case where our selection range wraps 0/HSV_MAX_HUE.
    assert (hsvspec.hue >= 0) and (hsvspec.hue <= HSV_MAX_HUE)

    if hsv_image is None:
        return None

    hue_min = hsvspec.hue - hsvspec.huerange
    hue_max = hsvspec.hue + hsvspec.huerange
    hue_min_2 = None
    hue_max_s = None
    if hue_min < 0:
        hue_min_2 = HSV_MAX_HUE + hue_min
        hue_max_2 = HSV_MAX_HUE
        hue_min = 0
    if hue_max > HSV_MAX_HUE:
        hue_min_2 = 0
        hue_max_2 = hue_max - HSV_MAX_HUE
        hue_max = HSV_MAX_HUE

    saturation_min = hsvspec.saturation - hsvspec.saturationrange
    saturation_max = hsvspec.saturation + hsvspec.saturationrange
    if saturation_min < 0:
        saturation_min = 0
    if saturation_max > 255:
        saturation_max = 255

    value_min = hsvspec.value - hsvspec.valuerange
    value_max = hsvspec.value + hsvspec.valuerange
    if value_min < 0:
        value_min = 0
    if value_max > 255:
        value_max = 255

    # print("color_mask_one_hue()", hue_min, hue_max, saturation_min, saturation_max, value_min, value_max)
    hueMask = cv2.inRange(
        hsv_image,
        np.array([hue_min, saturation_min, value_min], np.uint8),
        np.array([hue_max, saturation_max, value_max], np.uint8),
    )
    if hue_min_2 is not None:
        hueMask_2 = cv2.inRange(
            hsv_image,
            np.array([hue_min_2, saturation_min, value_min], np.uint8),
            np.array([hue_max_2, saturation_max, value_max], np.uint8),
        )
        hueMask = cv2.bitwise_or(hueMask, hueMask_2)

    return hueMask


def color_mask(
    hsv_image,
    colors=[0],
    huerange=25,
    saturation=205,
    saturationrange=50,
    value=205,
    valuerange=50,
):
    # adapted from http://stackoverflow.com/questions/35866411/opencv-how-to-detect-lines-of-a-specific-colour
    # input is an HSV image. Output is a monochrome image
    # print("color_mask()", colors, huerange)

    result = None
    for this_hue in colors:
        if this_hue < 0:
            this_result = color_mask_white(hsvChannels, threshold=wthreshold)
        else:
            hsvspec = HsvSpec(
                this_hue,
                huerange=huerange,
                saturation=saturation,
                saturationrange=saturationrange,
                value=value,
                valuerange=valuerange,
            )
            this_result = color_mask_one_hue(hsv_image, hsvspec)
        if result is None:
            result = this_result
        else:
            result = cv2.bitwise_or(result, this_result)
    return result


def roi(img, x1, y1, x2, y2):
    # extract a region of interest, accepting "normal order" coordinates
    # (x1, y1) is the upper/left corner, (x2, y2) is the lower/right corner
    # origin is upper/left of image
    roi = img[y1:y2, x1:x2]
    return roi


#
# Translate an image axis index c
#   c:
# 	if positive integer: simply the index
#       if negative integer: index backwards from ext
#       Otherwise a simple symbolic math operation +/- where the first operand can be:
#               b: beginning / 0 / zero
# 		e: extent / end of axis
# 		m: middle of axis
#               p: relative to index p1, used to specify end index as an offset (ususally lenght/width)
#
#   ext: (extent) maximum index value for that axis (integer)
def resolve_symbolic_index(c, ext, p1=None):
    def Raw_ResolveSymbolicIndex(c, ext, p1=None):
        # print('Raw_ResolveSymbolicIndex', repr(c), ext, p1)
        if isinstance(c, str):
            if c[0] == "m":
                if c == "m":
                    return int(ext / 2)
                else:
                    return int(ext / 2) + int(c[1:])
            elif c[0] == "e":
                if c == "e":
                    return ext
                else:
                    return ext + int(c[1:])
            elif (c[0] == "p") and (p1 is not None):
                if c == "p":
                    return p1
                else:
                    return p1 + int(c[1:])  # c[1:] begins with plus or minus sign
            elif c[0] == "b":
                if c == "b":
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

    # Main part of function, limits raw calcualtaion to image extents
    res = Raw_ResolveSymbolicIndex(c=c, ext=ext, p1=p1)
    if res < 0:
        return 0
    if res > ext:
        return ext
    return res


def hough_lines_p(im, min_line_length=30, max_line_gap=10):
    try:
        cv_lines = cv2.HoughLinesP(
            im.im, 1, np.pi / 180, 15, minLineLength=min_line_length, maxLineGap=max_line_gap
        )
    except cv2.error:
        print("HoughLinesP requires a grayscale (single-channel) image. Convert to gray first.")
        return []
    object_list = []
    if cv_lines is not None:
        for this in cv_lines:
            for x1, y1, x2, y2 in this:
                object_list.append(LineObject(x1, y1, x2, y2))
    return object_list


class LineObject:
    __slots__ = ("x1", "y1", "x2", "y2")

    def __init__(self, x1, y1, x2, y2):
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2

    def annotate(self, im, color=None, width=1):
        if color is None:
            color = next_color()
        cv2.line(im.im, self.p1, self.p2, color, width)

    @property
    def p1(self):
        return (self.x1, self.y1)

    @property
    def p2(self):
        return (self.x2, self.y2)


class RightRect:
    # This is a right rectangle. See RotatedRect for rotated rectangle.
    __slots__ = ("y_min", "y_max", "x_min", "x_max")

    def __init__(self, y_min, y_max, x_min, x_max):
        # assert y_min < y_max		# maybe just reorder instead. If we do that,
        # assert x_min < x_max		# should make them properties to keep enforced.
        self.y_min = y_min
        self.y_max = y_max
        self.x_min = x_min
        self.x_max = x_max

    def __repr__(self):
        return "[({0}, {1}), ({2}, {3})]".format(
            self.x_min, self.y_min, self.x_max, self.y_max
        )

    def copy(self):
        res = RightRect(self.y_min, self.y_max, self.x_min, self.x_max)
        return res

    def as_payload(self):
        p = {}
        for this in self.__slots__:
            p[this] = getattr(self, this)
        return p

    @property
    def center(self):
        return (int((self.x_min + self.x_max) / 2), int((self.y_min + self.y_max) / 2))

    @property
    def center_x(self):
        return int((self.x_min + self.x_max) / 2)

    @property
    def center_y(self):
        return int((self.y_min + self.y_max) / 2)

    @property
    def height(self):
        return self.y_max - self.y_min

    @property
    def p1(self):
        return (self.x_min, self.y_min)

    @property
    def p2(self):
        return (self.x_max, self.y_max)

    def top_y(self, x=None):
        return self.y_min


def right_rect_from_opencv_image(im):
    shape = im.shape
    return RightRect(0, shape[0], 0, shape[1])


def right_from_payload(payload):
    if "y_min" in payload:
        y_min = int(payload["y_min"])
        y_max = int(payload["y_max"])
        x_min = int(payload["x_min"])
        x_max = int(payload["x_max"])
    else:
        y_min = int(payload["y"])
        x_min = int(payload["x"])
        w = int(payload["w"])
        h = int(payload["h"])
        x_max = x_min + w
        y_max = y_min + h
    return RightRect(y_min, y_max, x_min, x_max)


def right_rect_from_symbolic_yx(im, y_range, x_range):
    height, width, channels = im.shape
    y_min = resolve_symbolic_index(y_range[0], height)
    y_max = resolve_symbolic_index(y_range[1], height)
    x_min = resolve_symbolic_index(x_range[0], width)
    x_max = resolve_symbolic_index(x_range[1], width)
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if y_min > y_max:
        y_min, y_max = y_max, y_min
    return RightRect(y_min, y_max, x_min, x_max)


def right_rect_from_symbolic_pp(im, p1, p2):
    if im is None:
        return None
    if len(im.shape) > 2:
        height, width, channels = im.shape
    else:
        height, width = im.shape
        channels = 1
    x_min = resolve_symbolic_index(p1[0], width)
    y_min = resolve_symbolic_index(p1[1], height)
    x_max = resolve_symbolic_index(p2[0], width, x_min)
    y_max = resolve_symbolic_index(p2[1], height, y_min)
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if y_min > y_max:
        y_min, y_max = y_max, y_min
    return RightRect(y_min, y_max, x_min, x_max)


#
# ReflexEntities — used by cameraman.py for line-following vision
#
RACE_WTHRESHOLD = 20
RACE_THRESHOLD = 150


def bgr2gray(bgr):
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


class ReflexEntities:
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
            if this == "B":
                self.image = simplest_cb(self.image.copy(), 20)
            elif this == "C":
                self.image = color_mask(
                    self.image.copy(),
                    colors=color_list,
                    threshold=RACE_THRESHOLD,
                    wthreshold=RACE_WTHRESHOLD,
                )
            elif this == "E":
                self.image = cv2.equalizeHist(self.image.copy())
            elif this == "G":
                self.image = cv2.GaussianBlur(self.image.copy(), (5, 5), 0)
            elif this == "W":
                self.image = bgr2gray(self.image)
            elif this == "Y":
                self.image = auto_canny(self.image.copy(), 0.1)
        self.h_lines = cv2.HoughLinesP(
            self.image, 1, np.pi / 180, 15, minLineLength=30, maxLineGap=10
        )
        self.map_lines = []
        self.avg_slope = 0

    def process_lines(self):
        VERTICAL_SLOPE = 9999
        self.map_lines = []
        self.avg_slope = 0
        self.slope_ct = 0
        h = self.image.shape[0]
        w = self.image.shape[1]
        m = int(w / 2)
        if self.h_lines is not None:
            for x in range(0, len(self.h_lines)):
                for x1, y1, x2, y2 in self.h_lines[x]:
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
            mlen = this[1]
            mslope = this[2]
            if (mslope < 0.5) and (mlen < 20):
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
