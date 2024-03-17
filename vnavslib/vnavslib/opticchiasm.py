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

from vnavslib import vnavs_data as vdata

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
# OpenCv images are numpy arrays
#   [0,0] is the upper, left corner of the image
#   The image is stored as an array of horizontal lines, so the index is [y, x]
#
def ReprOpenCv(im):
    imx = Image(im=im, colorcode=IM_BGR)
    return imx.__repr__()


class Image(object):
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
        colorcode = colorcode.upper()  # change picamera format to OpenCv
        self.crop_source = None  # Image() from which this is cropped
        self.crop_x = None  # left x starting position of this crop in source image
        self.crop_y = None  # upper y` starting position of this crop in source image
        self.ReplaceImage(im, colorcode)

    def __repr__(self):
        return "Image {}x{}x{} {}".format(
            self.width, self.height, self.colordepth, self.colorcode
        )

    def copy(self):
        if self._im is None:
            return Image(im=None, colorcode=self.colorcode)
        else:
            return Image(im=self._im.copy(), colorcode=self.colorcode)

    def CopyAsBGR(self):
        if self.colorcode == IM_BGR:
            return self.Copy()
        transform = getattr(cv2, "COLOR_{}2{}".format(self.colorcode, IM_BGR))
        return Image(im=cv2.cvtColor(self._im, transform), colorcode=IM_BGR)

    def CopyAsGray(self):
        if self.colorcode == IM_GRAY:
            return self.Copy()
        transform = getattr(cv2, "COLOR_{}2{}".format(self.colorcode, IM_GRAY))
        return Image(im=cv2.cvtColor(self._im, transform), colorcode=IM_GRAY)

    @property
    def im(self):  # im is a property to discourage skipping ReplaceImage()
        return self._im

    def ImAsBGR(self):
        return self.ImAsAny(IM_BGR)

    def ImAsRGB(self):
        return self.ImAsAny(IM_RGB)

    def ImAsHSV(self):
        return self.ImAsAny(IM_HSV)

    def ImAsGray(self, Copy=False):
        if self.colorcode == IM_GRAY:
            if Copy:
                return self._im.copy()
            else:
                return self._im
        return self.ImAsAny(IM_GRAY)

    def ImAsAny(self, colorcode, Copy=False):
        # print("ImAsAny()", self.colorcode, colorcode, self._im.__class__.__name__)
        if self._im is None:
            return None
        colorcode = colorcode.upper()
        if not colorcode in IM_COLORCODES:
            return None
        if self.colorcode == colorcode:
            if Copy:
                return self._im.copy()
            else:
                return self._im
        transform = getattr(cv2, "COLOR_{}2{}".format(self.colorcode, IM_HSV), None)
        if transform is None:
            return None
        return cv2.cvtColor(self._im, transform)

    def ReplaceImage(self, im, colorcode):
        assert colorcode in IM_COLORCODES
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

    def Write(self, fn=None):
        if fn is None:
            fn = self.file_path
        cv2.imwrite(fn, self.ImAsBGR())
        # except IOError as e:
        # IOError: [Errno 28] Out of disk space
        #                    if e.errno == 28:

    def AverageHue(self, rect=None):
        if rect is None:
            hsv = self.ImAsHSV()
        else:
            hsv = self.Crop(rect).ImAsHSV()
        average_color = hsv[:, :, 0].mean()
        return average_color

    def Crop(self, rect, Isolate=False):
        # print("Crop()", rect)
        if rect is None:
            return self.Copy()
        new_image = Image(
            im=self._im[
                rect.y_min : rect.y_max + 1, rect.x_min : rect.x_max + 1
            ].copy(),
            colorcode=self.colorcode,
        )
        if not Isolate:
            new_image.crop_source = self
            new_image.crop_x = rect.x_min
            new_image.crop_y = rect.y_min
        return new_image

    def DrawLinePoints(self, linepoints, color=DRAW_BGR_GREEN, thickness=2):
        # Annotates an array of RightRect or RotatedRect from ChaseLine() or elsewhere
        if linepoints is not None:
            for this in linepoints:
                cv2.rectangle(self._im, this.p1, this.p2, color, thickness)

    def DrawRectangle(self, rect, color=DRAW_BGR_GREEN, thickness=2):
        cv2.rectangle(self._im, rect.p1, rect.p2, color, thickness)

    def RightRectFromSymbolicYX(self, y_range, x_range):
        return RightRectFromSymbolicYX(self._im, y_range, x_range)

    def RightRectFromSymbolicPP(self, p1, p2):
        return RightRectFromSymbolicPP(self._im, p1, p2)

    def ChaseLine(
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
        print("ChaseLine()", self, line_hsvspec, line_rect)

        def QualifyLineSegment():
            global next_hsv_spec
            # This advances the search through the image. Adjusting line_hsvspec and line_rect.
            # check if the blob is reasonably a line segment
            # size? color? location?
            # print("ChaseLine() Qualify", line_hsvspec, line_rect)
            blobs, next_hsv_spec = self.FindColorBlobs(
                hsvspec=line_hsvspec,
                rect=line_rect,
                kernel_dim=kernel_dim,
                iterations=iterations,
                MinimumBlobArea=min_blob_area,
                MaximumCtOfRectsWanted=1,
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
                "ChaseLine() Loop",
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

    def FindColorBlobs(
        self,
        hsvspec,
        rect=None,
        kernel_dim=3,
        iterations=1,
        MinimumBlobArea=1,
        MaximumCtOfRectsWanted=3,
    ):
        # print("FindColorBlobs()", self, rect, hsvspec)
        if rect is None:
            im_cropped = self
        else:
            im_cropped = self.Crop(rect)
        im_hsv = im_cropped.ImAsHSV()
        im_masked = ColorMaskOneHue(im_hsv, hsvspec)
        # print("FindColorBlobs() Cropped " + ReprOpenCv(im_masked))
        kernel = np.ones((kernel_dim, kernel_dim), np.uint8)
        im_dilated = cv2.dilate(im_masked, kernel, iterations=iterations)
        cont2, contours, hierarchy = cv2.findContours(
            im_dilated.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )
        rotated_rect_list = ContoursExtract(
            contours,
            hierarchy,
            MinimumArea=MinimumBlobArea,
            MaximumCtOfRectsWanted=MaximumCtOfRectsWanted,
        )
        next_hsv_spec = None
        if (rotated_rect_list is not None) and (len(rotated_rect_list) > 0):
            # use im_masked because im_dilated includes out of range hsv values
            next_hsv_spec = NextHsvSpec(
                im_hsv, mask=im_masked, rect=rotated_rect_list[0]
            )
            if rect is not None:
                for this in rotatated_rect_list:  # adjust to original image coordinates
                    this.center_x += rect.x_min
                    this.center_y += rect.y_min
        print("FindColorBlobs()", rotated_rect_list)
        return rotated_rect_list, next_hsv_spec


def ImageFromPicamera(picam_image, format, file_path=None):
    # format is picamera style format
    img = Image()
    img.file_path = file_path
    if format == "bgr":
        img.ReplaceImage(picam_image.array, IM_BGR)
    elif format == "rgb":
        img.ReplaceImage(picam_image.array, IM_RGB)
    elif format == "yuv":
        img.ReplaceImage(picam_image.array, IM_YUV)
    return img


# Filter functions should modify only:
# 	xstep.im
# GetParm() must image_filter parameters to avoid code injection attacks


FILTER_NAME_ANALYZER = "Analyzer"
FILTER_NAME_COLORMASK_MULTI = "ColorMaskMulti"
FILTER_NAME_COLORMASK_SINGLE = "ColorMaskSingle"
FILTER_NAME_CROPPP = "CropPP"
FILTER_NAME_IMAGE = "Image"

FLAG_ISBASE = "isbase"
FLAG_SLIDERS = "sliders"


class ImageFilterCollection(object):
    image_filters = {}
    image_filter_names = []


class ImageFilter(object):
    __slots__ = ("annotate_code", "clsdata", "flags", "code", "name", "parms")

    def __init__(self, name, code, parms, Flags=None):
        self.name = name
        self.code = code
        self.parms = parms  # a list of vdata.DataAttrib() and descendent objects
        self.flags = Flags  # a list of string flag names
        self.annotate_code = None
        self.clsdata = ImageFilterCollection
        self.clsdata.image_filters[name] = self
        self.clsdata.image_filter_names.append(name)
        self.clsdata.image_filter_names.sort()


#
# Filter code is processed with exec with available globals OpticCiasm, cv2,
# 	previous step exec_im and its shape as im, h, w and c,
# 	xstep is the current ProcessStep() with exec_im set to None.
#
ImageFilter(
    FILTER_NAME_IMAGE, "{x_output_im} = xstep.source_im.Copy()", [], Flags=[FLAG_ISBASE]
)

ImageFilter(
    FILTER_NAME_COLORMASK_MULTI,
    "{x_output_im} = oc.Image(oc.ColorMask(im_in.ImAsHSV(), colors=[{colors}], huerange={hueRange},"
    + " saturation={saturation}, saturationrange={saturationRange},"
    + " value={value}, valuerange={valueRange})",
    [
        vdata.DataAttribIntList("colors", "oc.HSV_WHITE, oc.HSV_RED"),
        vdata.DataAttribInt(
            "hueRange", "25", min_value=0, max_value=HSV_MAX_HUE, use_slider=True
        ),
        vdata.DataAttribInt(
            "saturation", "205", min_value=0, max_value=255, use_slider=True
        ),
        vdata.DataAttribInt(
            "saturationRange", "50", min_value=0, max_value=255, use_slider=True
        ),
        vdata.DataAttribInt(
            "value", "205", min_value=0, max_value=255, use_slider=True
        ),
        vdata.DataAttribInt(
            "valueRange", "50", min_value=0, max_value=255, use_slider=True
        ),
        vdata.DataAttribStr("colorcode", IM_HSV),
    ],
    Flags=[],
)

ImageFilter(
    FILTER_NAME_COLORMASK_SINGLE,
    "{x_output_hsvspec} = oc.HsvSpec("
    + " hue={hue}, huerange={hueRange},"
    + " saturation={saturation}, saturationrange={saturationRange},"
    + " value={value}, valuerange={valueRange})\n"
    '{x_output_im} = oc.Image(oc.ColorMaskOneHue(im_in.ImAsAny("{colorcode}"), {x_output_hsvspec}),'
    + "	colorcode=oc.IM_GRAY)",
    [
        vdata.DataAttribInt(
            "hue", "25", min_value=0, max_value=HSV_MAX_HUE, use_slider=True
        ),
        vdata.DataAttribInt(
            "hueRange", "25", min_value=0, max_value=HSV_MAX_HUE, use_slider=True
        ),
        vdata.DataAttribInt(
            "saturation", "205", min_value=0, max_value=255, use_slider=True
        ),
        vdata.DataAttribInt(
            "saturationRange", "50", min_value=0, max_value=255, use_slider=True
        ),
        vdata.DataAttribInt(
            "value", "205", min_value=0, max_value=255, use_slider=True
        ),
        vdata.DataAttribInt(
            "valueRange", "50", min_value=0, max_value=255, use_slider=True
        ),
        vdata.DataAttribStr("colorcode", IM_HSV),
    ],
    Flags=[FLAG_SLIDERS],
)

image_filter = ImageFilter(
    FILTER_NAME_CROPPP,
    "{x_output_rect} = im_in.RightRectFromSymbolicPP({p1}, {p2})\n"
    + "{x_output_im} = im_in.Crop({x_output_rect})\n"
    + "print(im_in.shape, {x_output_rect})\n",
    [
        vdata.DataAttribPointSym("p1", "m-50,m+50"),
        vdata.DataAttribPointSym("p2", "-100,e"),
    ],
    Flags=[],
)
image_filter.annotate_code = (
    "{x_output_annotated} = im_base.Copy()\n"
    + "{x_output_annotated}.DrawRectangle({x_output_rect}, color=oc.DRAW_BGR_GREEN, thickness=2)\n"
)

image_filter = ImageFilter(
    "CropYX",
    "{x_output_rect} = im_in.RightRectFromSymbolicYX({y_range}, {x_range})\n"
    + "{x_output_im} = im_in.Crop({x_output_rect})\n"
    + "print(im_in.shape, {x_output_rect})\n",
    [
        vdata.DataAttribPointSym("y_range", "-100,"),
        vdata.DataAttribPointSym("x_range", "m-50,m+50"),
    ],
    Flags=[],
)
image_filter.annotate_code = (
    "{x_output_annotated} = im_base.Copy()\n"
    + "{x_output_annotated}.DrawRectangle({x_output_rect}, color=oc.DRAW_BGR_GREEN, thickness=2)\n"
)

ImageFilter("Gray", "{x_output_im} = im_in.CopyAsGray()", [], Flags=[])

ImageFilter(
    "Blur",
    "{x_output_im} = oc.Image(im=cv2.blur(im_in.im, {ksize}), colorcode=im_in.colorcode)",
    [vdata.DataAttribPoint("ksize", "3,3")],
    Flags=[],
)

ImageFilter(
    "Cameraman",
    '{x_output_im} = oc.Cameraman(im_in, "{path}", "{fn}")',
    [
        vdata.DataAttribStr("path", "/Users/almargolis/projects/vnavs/scripts"),
        vdata.DataAttribStr("fn", "test.cam"),
    ],
    Flags=[],
)

ImageFilter(
    "BlurBilateralFilter",
    "{x_output_im} = oc.Image(im=cv2.bilateralFilter(im_in.im, {diameter}, {sigmaColor}, {sigmaSpace}), colorcode=im_in.colorcode)",
    [
        vdata.DataAttribInt("diameter", "5"),
        vdata.DataAttribInt("sigmaColor", "17"),
        vdata.DataAttribInt("sigmaSpace", "17"),
    ],
    Flags=[],
)
# diameter > 5 is very slow, use 5 for real time processing or 9 for off-line heavy image_filtering
# the two sigma values are often the same value. <10 doesn't do much, >150 is cartoonish

ImageFilter(
    "BlurGaussian",
    "{x_output_im} = oc.Image(im=cv2.GaussianBlur(im_in.im, {ksize}, {sigmaX}), colorcode=im_in.colorcode)",
    [vdata.DataAttribPoint("ksize", "3,3"), vdata.DataAttribFloat("sigmaX", "0.0")],
    Flags=[],
)

ImageFilter(
    "BlurMedian",
    "{x_output_im} = oc.Image(im=cv2.medianBlur(im_in.im, {ksize}), colorcode=im_in.colorcode)",
    [vdata.DataAttribInt("ksize", "3")],
    Flags=[],
)

ImageFilter(
    "Canny",
    "{x_output_im} = oc.Image(im=cv2.Canny(im_in.ImAsGray(), {threshold1}, {threshold2}), colorcode=oc.IM_GRAY)",
    [
        vdata.DataAttribFloat("threshold1", "100"),
        vdata.DataAttribFloat("threshold2", "300"),
    ],
    Flags=[],
)

ImageFilter(
    "CannyAuto",
    "{x_output_im} = oc.Image(im=oc.AutoCanny(im_in.ImAsGray(), {sigma}), colorcode=oc.IM_GRAY)",
    [vdata.DataAttribFloat("sigma", "0.33")],
    Flags=[],
)

image_filter = ImageFilter(
    "ChaseLine", "line_points = im_base.ChaseLine(hsvspec_in, rect_in)", [], Flags=[]
)
# ChaseLine depends on previous rect and hsvspec. These probably changed im_in to a
# black and while image from HueMaskSingle or similar. This therefore uses
# im_base to reset to the original color image
image_filter.annotate_code = (
    "{x_output_annotated} = im_base.Copy()\n"
    + "{x_output_annotated}.DrawLinePoints(line_points, color=oc.DRAW_BGR_GREEN, thickness=2)\n"
)


ImageFilter(
    "ColorBalance",
    "{x_output_im} = oc.simplest_cb(im, {pct})",
    [vdata.DataAttribInt("pct", "20")],
    Flags=[],
)
#
# Morphing Filters
#
# There are more of these. There is also a function to build a morphng engine, which appernly how dilate and
# erode are defined. Kernel can be non-rectanglar and there is a function to build those. If we enhance kernel,
# probably want to specify anchor too.
#
# https://docs.opencv.org/2.4/modules/imgproc/doc/image_filtering.html
# https://docs.opencv.org/3.0-beta/doc/py_tutorials/py_imgproc/py_morphological_ops/py_morphological_ops.html
#
ImageFilter(
    "MorphClose",
    "kernel = np.ones(({kernel_dim}, {kernel_dim}), np.uint8)\n"
    + "{x_output_im} = oc.Image(im=cv2.morphologyEx(im_in._im, cv2.MORPH_CLOSE, kernel, iterations={iterations}),\n"
    + "			colorcode=im_in.colorcode)\n",
    [vdata.DataAttribInt("kernel_dim", "5"), vdata.DataAttribInt("iterations", "1")],
    Flags=[],
)

ImageFilter(
    "MorphDilate",
    "kernel = np.ones(({kernel_dim}, {kernel_dim}), np.uint8)\n"
    + "{x_output_im} = oc.Image(im=cv2.dilate(im_in.im, kernel, iterations={iterations}),\n"
    + "			colorcode=im_in.colorcode)\n",
    [vdata.DataAttribInt("kernel_dim", "5"), vdata.DataAttribInt("iterations", "1")],
    Flags=[],
)

ImageFilter(
    "MorphErode",
    "kernel = np.ones(({kernel_dim}, {kernel_dim}), np.uint8)\n"
    + "{x_output_im} = oc.Image(im=cv2.erode(im_in.im, kernel, iterations={iterations}),\n"
    + "			colorcode=im_in.colorcode)\n",
    [vdata.DataAttribInt("kernel_dim", "5"), vdata.DataAttribInt("iterations", "1")],
    Flags=[],
)

ImageFilter(
    "MorphGradient",
    "kernel = np.ones(({kernel_dim}, {kernel_dim}), np.uint8)\n"
    + "{x_output_im} = oc.Image(im=cv2.morphologyEx(im_in._im, cv2.MORPH_GRADIENT, kernel, iterations={iterations}),\n"
    + "			colorcode=im_in.colorcode)\n",
    [vdata.DataAttribInt("kernel_dim", "5"), vdata.DataAttribInt("iterations", "1")],
    Flags=[],
)

ImageFilter(
    "MorphOpen",
    "kernel = np.ones(({kernel_dim}, {kernel_dim}), np.uint8)\n"
    + "{x_output_im} = oc.Image(im=cv2.morphologyEx(im_in._im, cv2.MORPH_OPEN, kernel, iterations={iterations}),\n"
    + "			colorcode=im_in.colorcode)\n",
    [vdata.DataAttribInt("kernel_dim", "5"), vdata.DataAttribInt("iterations", "1")],
    Flags=[],
)

#
# Contour Filters
#
# findContours modifies the soure image. The image is assumed to be binary, ususally from canny
# somewhere along line cont2 eliminated
#'cont2, {x_output_contours}, {x_output_hierarchy} = cv2.findContours(im_in.ImAsGray(Copy=True), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)\n',
image_filter = ImageFilter(
    "ContoursFind",
    "{x_output_contours}, {x_output_hierarchy} = cv2.findContours(im_in.ImAsGray(Copy=True), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)\n",
    [
        vdata.DataAttribInt("MaxLevel", "-1"),
    ],
    Flags=[],
)
# image_filter.annotate_code = '{x_output_annotated} = im_base.CopyAsGray().CopyAsBGR()\n' \
# 				+ 'print("Contour", len({x_output_contours}))\n' \
# 				+ 'for i in range(0, len({x_output_contours})):\n' \
# 				+ '    color = (np.random.randint(0, 255), np.random.randint(0, 255), np.random.randint(0, 255))\n' \
# 				+ '    cv2.drawContours({x_output_annotated}._im, {x_output_contours}, i, color, 3)\n' \
#                               + 'print("Contour", color)\n'
# 			+ 'oc.ContoursToLineVectors({x_output_annotated}.im, {x_output_contours}, {x_output_hierarchy})\n' \
# 			+ 'oc.CrayolaContours({x_output_annotated}.im, {x_output_contours}, {x_output_hierarchy}, MaxLevel={MaxLevel})\n' \
# 			+ 'cv2.drawContours({x_output_annotated}.im, {x_output_contours}, -1, oc.DRAW_BGR_RED, 1)\n' \

image_filter.annotate_code = (
    "{x_output_annotated} = im_in.CopyAsBGR()\n"
    + "cv2.drawContours({x_output_annotated}._im, {x_output_contours}, -1, (0, 0, 255), 3)\n"
)
# 			+ 'print("Contour", len(contours_in))\n' \

ImageFilter(
    "EqualizeHistogram",
    "{x_output_im} = oc.Image(im=cv2.equalizeHist(im_in.ImAsGray()), colorcode=oc.IM_GRAY)",
    [],
    Flags=[],
)

ImageFilter("HistogramCB", "oc.Histogram_CB(im)", [], Flags=[])

image_filter = ImageFilter(
    FILTER_NAME_ANALYZER,
    "r = im_base.RightRectFromSymbolicPP({p1}, {p2})\n",
    [
        vdata.DataAttribPointSym("p1", "m-3,m-3"),
        vdata.DataAttribPointSym("p2", "p+3,p+3"),
    ],
    Flags=[],
)
image_filter.annotate_code = (
    "{x_output_annotated} = im_base.Copy()\n"
    + "{x_output_annotated}.DrawRectangle(r, color=oc.DRAW_BGR_GREEN, thickness=2)\n"
    + 'xstep.SetInfo(0, "Hue", im_base.Crop(r).AverageHue())\n'
)

image_filter = ImageFilter(
    "HoughLinesP",
    "{x_output_objects} = oc.HoughLinesP(im_in, minLineLength={MinLineLength}, maxLineGap={MaxLineGap})",
    [vdata.DataAttribInt("MinLineLength", "30"), vdata.DataAttribInt("MaxLineGap", 10)],
    Flags=[""],
)
image_filter.annotate_code = (
    "{x_output_annotated} = im_base.Copy()\n"
    + "print({x_output_objects})\n"
    + "oc.InitColor()\n"
    + "for this in {x_output_objects}:\n"
    + "    this.Annotate({x_output_annotated})\n"
)

ImageFilter(
    "Map", "cv2.warpPerspective(im, transform, (int(w*3), int(h*4)))", [], Flags=[]
)


#
# This is an interesting example of line locating
# https://github.com/naokishibuya/car-finding-lane-lines
#
# automatically set threshold using technique from
# http://www.pyimagesearch.com/2015/04/06/zero-parameter-automatic-canny-edge-detection-with-python-and-opencv/
# just saw URL, and have seen it before, so that's re-assuring that I like it
def AutoCanny(grayscale_im, AutoCanny_sigma):
    grayscale_im_median = np.median(grayscale_im)
    lower_canny_thresh = int(max(0, (1 - AutoCanny_sigma) * grayscale_im_median))
    upper_canny_thresh = int(min(255, (1 + AutoCanny_sigma) * grayscale_im_median))
    # print("AutoCanny()", grayscale_im_median, lower_canny_thresh, upper_canny_thresh)
    # lower_canny_thresh = 100
    # upper_canny_thresh = 130
    return cv2.Canny(grayscale_im, lower_canny_thresh, upper_canny_thresh)


#
# BGR / RGB Conversions
# thanks to https://www.scivision.co/numpy-image-bgr-to-rgb/
#
def BGR2RGB(bgr):
    # OpenCV image to Matplotlib or Pillow Image.fromarray()
    return bgr[..., ::-1]


def RGB2BGR(rgb):
    # image to OpenCV
    return rgb[..., ::-1]


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


def Cameraman(im, path, fn):
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


def InitColor():
    global color_ix
    color_ix = -1


def NextColor():
    global color_ix
    color_ix += 1
    if color_ix >= len(DRAW_COLORS):
        color_ix = 0
    return DRAW_COLORS[color_ix]


def ListOfRotatedRectAsListOfDicts(in_list):
    # Takes list of RotatedRect and converts to a JSON serializable
    # list of dicts. The list is from Image.ChaseLine() or similar.
    res = []
    for this in in_list:
        res.append(ObjectAsDict(this))
    return res


def ListOfRotatedRectFromListofDicts(in_list):
    # Takes a list of dicts and convert to a list
    # of RotatedRect
    if in_list is None:
        return []
    res = []
    for this in in_list:
        res.append(RotatedRectFromDict(this))
    return res


def SlopeOfListOfRotatedRect(list_of_rects):
    [vx, vy, x, y] = cv2.fitLine(points, cv2.DIST_L1, 0, 0.01, 0.01)
    print("slope", float(vy / vx))
    left_y = int((-x * vy / vx) + y)
    right_y = int(((width - x) * vy / vx) + y)

    if (left_y >= 0) and (left_y <= height) and (right_y >= 0) and (right_y <= height):
        vert_line = ((width - 1, right_y), (0, left_y))


def RotatedRectFromDict(d):
    # print("RotatedRectFromDict()", d)
    return RotatedRect(
        ((d["center_x"], d["center_y"]), (d["width"], d["height"]), d["angle"])
    )


def ObjectAsDict(src):
    res = {}
    for this in src.__slots__:
        res[this] = getattr(src, this)
    return res


class RotatedRect(object):
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

    def BoxPointsList(self):
        return cv2.boxPoints(self.AsRotatedRect()).tolist()  # returns array of 4 [x, y]

    def AsRotatedRect(self):
        return [[self.center_x, self.center_y], [self.width, self.height], angle]

    def TopY(self, x):
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


def RotatedRectFromOpenCvImage(im):
    shape = im.shape
    height = shape[0]
    width = shape[1]
    center = (float(width / 2.0), float(height / 2.0))
    dims = (width, height)
    return RotatedRect((center, dims, 0.0))


def ContoursExtract(contours, hierarchy, MinimumArea=1, MaximumCtOfRectsWanted=3):
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
        if area >= MinimumArea:
            print("KEEP", area, MinimumArea)
            areas.append((area, h_ix))
        else:
            print("DISC", area, MinimumArea)
            discarded_contour_count = 0
        h_ix = h[0]
    areas.sort(reverse=True)  # sort from largest to smallest)
    rotated_rect_list = []
    for this in areas[: MaximumCtOfRectsWanted + 1]:
        h_ix = this[1]
        cnt = contours[h_ix]
        rect = RotatedRect(cv2.minAreaRect(cnt))  # ((x, y), (w, h), angle)
        rotated_rect_list.append(rect)
    print("ContoursExtract()", rotated_rect_list)
    return rotated_rect_list


def ContoursToLineVectors(
    img, contours, hierarchy, MinimumArea=1, MaximumCtOfRectsWanted=3
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
        if area >= MinimumArea:
            areas.append((area, h_ix))
        h_ix = h[0]
    areas.sort(reverse=True)  # sort from largest to smallest)
    for this in areas[:MaximumCtOfRectsWanted]:
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
                child_ix = ColorBranch(child_ix, c, this_level + 1, max_level)
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
        # normalized = cv2.normalize(thresholded, thresholded.copy(), 0, 255, cv2.NORM_MINMAX)
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
    return I & ~M


def ColorMaskWhite(hsvChannels, threshold=50):
    minValue = 255 - threshold
    maxSaturation = threshold
    ret, saturationMask = cv2.threshold(
        hsvChannels[1], maxSaturation, 255, cv2.THRESH_BINARY_INV
    )
    ret, valueMask = cv2.threshold(hsvChannels[2], minValue, 255, cv2.THRESH_BINARY)
    image_filterMask = cv2.bitwise_and(saturationMask, valueMask)
    return image_filterMask


class HsvSpec(object):
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

    def AsPayload(self):
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


def HsvSpecFromPayload(payload):
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


def NextHsvSpec(hsvImage, mask=None, rotated_rect=None, minrange=20):
    # hsvImage is an OpenCvImage. rotated_rect is an RotatedRect.
    # Creates an HsvSpec based on the upper part of this image.
    # It considers only the center x and y from center to top.
    # Optionally considers only image pixels hilighted (>0) by mask.
    # Looks at either center of image or center of optional rect.
    # Used by Image.ChaseLine()
    def CalcRange(hist):
        # check if rng reasonable, avg close to hist[0], colorwrap
        avg = int((int(hist[1]) + int(hist[2])) / 2)
        rng = hist[2] - avg
        if rng < minrange:
            rng = minrange
        return avg, rng

    # print("NextHsvSpec()", ReprOpenCv(hsvImage), ReprOpenCv(mask), rotated_rect)
    value_ct = 0
    values = []
    values.append([0, 255, 0])  # sum, min value, max value)
    values.append([0, 255, 0])  # sum, min value, max value)
    values.append([0, 255, 0])  # sum, min value, max value)
    if rotated_rect is None:
        rotated_rect = RotatedRectFromOpenCvImage(hsvImage)
    x = int(rotated_rect.center_x)
    y = int(rotated_rect.center_y)
    top_y = int(rotated_rect.TopY(x))
    for this_y in range(y, top_y, -1):
        # print("NextHsvSpec() Loop", this_y, x, hueMask[this_y, x], hsvImage[this_y, x])
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
        # print("NextHsvSpec()", value_ct, None, values)
        return None
    hsv_spec = HsvSpec(0)
    hsv_spec.hue, hsv_spec.huerange = CalcRange(values[0])
    hsv_spec.saturation, hsv_spec.saturationrange = CalcRange(values[1])
    hsv_spec.value, hsv_spec.valuerange = CalcRange(values[2])
    # print("NextHsvSpec()", value_ct, hsv_spec, values)
    return hsv_spec


def ColorMaskOneHue(hsvImage, hsvspec):
    # In literature, hue space goes from 0 to 360 degrees, but OpenCV rescales the range to 0 up to HSV_MAX_HUE,
    # because 360 does not fit in a single byte. There is another mode where 0..360 is rescaled to 0..255 but this isn't as common.
    # Red color, value 0,  is one of the special case where our selection range wraps 0/HSV_MAX_HUE.
    assert (hsvspec.hue >= 0) and (hsvspec.hue <= HSV_MAX_HUE)

    if hsvImage is None:
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

    # print("ColorMaskOneHue()", hue_min, hue_max, saturation_min, saturation_max, value_min, value_max)
    hueMask = cv2.inRange(
        hsvImage,
        np.array([hue_min, saturation_min, value_min], np.uint8),
        np.array([hue_max, saturation_max, value_max], np.uint8),
    )
    if hue_min_2 is not None:
        hueMask_2 = cv2.inRange(
            hsvImage,
            np.array([hue_min_2, saturation_min, value_min], np.uint8),
            np.array([hue_max_2, saturation_max, value_max], np.uint8),
        )
        hueMask = cv2.bitwise_or(hueMask, hueMask_2)

    return hueMask


def ColorMask(
    hsvImage,
    colors=[0],
    huerange=25,
    saturation=205,
    saturationrange=50,
    value=205,
    valuerange=50,
):
    # adapted from http://stackoverflow.com/questions/35866411/opencv-how-to-detect-lines-of-a-specific-colour
    # input is an HSV image. Output is a monochrome image
    # print("ColorMask()", colors, huerange)

    result = None
    for this_hue in colors:
        if this_hue < 0:
            this_result = ColorMaskWhite(hsvChannels, threshold=wthreshold)
        else:
            hsvspec = HsvSpec(
                this_hue,
                huerange=huerange,
                saturation=saturation,
                saturationrange=saturationrange,
                value=value,
                valuerange=valuerange,
            )
            this_result = ColorMaskOneHue(hsvImage, hsvspec)
        if result is None:
            result = this_result
        else:
            result = cv2.bitwise_or(result, this_result)
    return result


def ROI(img, x1, y1, x2, y2):
    # extract a region of interest, accepting "normal order" coordinates
    # (x1, y1) is the upper/left corner, (x2, y2) is the lower/right corner
    # origin is upper/left of image
    roi = img[y1:y2, x1:x2]
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


def DrawContourLines(img, contours, color):
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
        line = CalcRectCenterline(rect, w, h)
        cv2.line(img, line[0], line[1], color, 2)
    return img


def ContourLines(img, gray, Drawlines=False, DrawBoth=False):
    # canny edge detection
    # bw_edged = AutoCanny(gray, 0.33)
    bw_edged = cv2.Canny(gray, 30, 200)
    cont2, contours, hierarchy = cv2.findContours(
        bw_edged.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    # cont2, contours, hierarchy = cv2.findContours(bw_edged.copy(),cv2.RETR_TREE,cv2.CHAIN_APPROX_TC89_L1)
    if len(img.shape) == 2:
        cropped_height, cropped_width = img.shape
    else:
        cropped_height, cropped_width, cropped_channels = img.shape
    (tiny, vertical, horizontal) = CreateContours(
        contours, cropped_width, cropped_height
    )
    if Drawlines or DrawBoth:
        contoured_image = DrawContourLines(img.copy(), tiny, (128, 128, 0))
        contoured_image = DrawContourLines(contoured_image, vertical, (128, 128, 0))
        contoured_image = DrawContourLines(contoured_image, horizontal, (128, 128, 0))
    else:
        contoured_image = img.copy()
    if (not Drawlines) or DrawBoth:
        contoured_image = cv2.drawContours(
            contoured_image.copy(), tiny, -1, (128, 0, 128), 1
        )
        contoured_image = cv2.drawContours(
            contoured_image.copy(), vertical, -1, (0, 255, 0), 1
        )
        contoured_image = cv2.drawContours(
            contoured_image.copy(), horizontal, -1, (255, 0, 0), 1
        )
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


def CrayolaFilter2(im, bw_threshold=20, mix_threshold=50):
    # im = simplest_cb(im, 20)
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    mask = np.asarray([224, 224, 224], dtype=np.uint8)
    mask = np.asarray([192, 128, 128], dtype=np.uint8)
    mask = np.asarray([192, 192, 192], dtype=np.uint8)
    mask = np.asarray([224, 128, 128], dtype=np.uint8)
    out = cv2.bitwise_and(hsv, mask)
    im = cv2.cvtColor(out, cv2.COLOR_HSV2BGR)
    bw = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    canny_image = AutoCanny(bw, 0.33)
    (imgxx, opencv_contours, hierarchy) = cv2.findContours(
        canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    im = cv2.drawContours(im, opencv_contours, -1, (255, 0, 255), 1)
    # return canny_image
    return im


def CrayolaFilter(im, bw_threshold=20, mix_threshold=50):
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
            t = ColorString(
                color, bw_threshold=bw_threshold, mix_threshold=mix_threshold
            )
            tc = t[0]
            if tc in color_map:
                c_out = color_map[tc]
            else:
                c_out = color_map["z"]
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


def FilterContours(img, contours, SelectColors="r"):
    image_shape = img.shape
    mask_shape = (image_shape[0], image_shape[1], 1)
    final = img.copy()
    mask = np.zeros(mask_shape, np.uint8)
    area_threshold = 90  # minimum area sized contour to draw
    area_threshold = 5  # minimum area sized contour to draw
    area_threshold = 10  # minimum area sized contour to draw
    new_contours = []

    for i in range(len(contours)):
        mask[...] = 0  # zero out mask
        mask = cv2.drawContours(mask, contours, i, 255, -1)  # draw contour on mask
        avg_color = cv2.mean(img, mask)
        avg_color = (int(avg_color[0]), int(avg_color[1]), int(avg_color[2]))
        color_str = ColorString(avg_color)
        this_c = contours[i]
        area = cv2.contourArea(this_c)
        if color_str[0] in SelectColors:
            continue
        if area < area_threshold:
            continue
        # print("Vertices:", len(this_c), "Area:", area, "@", int(rect[0][0]), int(rect[0][1]), "size", int(rect[1][0]), int(rect[1][1]),  "R:", int(rect[2]), "Color:", color_str)
        new_contours.append(this_c)
    new_contours = sorted(new_contours, key=cv2.contourArea, reverse=True)[0:8]
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
            if this == "B":
                # print("simplest_cb")
                self.image = simplest_cb(self.image.copy(), 20)
            elif this == "C":
                # print("ColorMask", color_list)
                self.image = ColorMask(
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
                self.image = BGR2GRAY(self.image)
            elif this == "Y":
                # print("Canny")
                self.image = AutoCanny(self.image.copy(), 0.1)  # ben's sigma was 0.33
        self.h_lines = cv2.HoughLinesP(
            self.image, 1, np.pi / 180, 15, minLineLength=30, maxLineGap=10
        )
        # if self.h_lines is None:
        #    print("LINES -- NONE")
        # else:
        #    print("LINES", len(self.h_lines))
        self.map_lines = []
        self.avg_slope = 0

    def ProcessLines(self):
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

    def AnnotateFullImage(self, image, linect=10, x1=0, y1=0, color=None):
        if color is None:
            color = (0, 255, 0)  # green
        a_width = 5
        for this in self.map_lines[:linect]:
            p1 = (this[5][0] + x1, this[5][1] + y1)
            p2 = (this[6][0] + x1, this[6][1] + y1)
            cv2.line(image, p1, p2, color, a_width)

    def AnalyzeLines(self):
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
def ResolveSymbolicIndex(c, ext, p1=None):
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


def HoughLinesP(im, minLineLength=30, maxLineGap=10):
    cv_lines = cv2.HoughLinesP(
        im.im, 1, np.pi / 180, 15, minLineLength=minLineLength, maxLineGap=maxLineGap
    )
    object_list = []
    for this in cv_lines:
        for x1, y1, x2, y2 in this:
            object_list.append(LineObject(x1, y1, x2, y2))
    return object_list


class LineObject(object):
    __slots__ = ("x1", "y1", "x2", "y2")

    def __init__(self, x1, y1, x2, y2):
        self.x1 = x1
        self.y1 = y1
        self.x2 = y2
        self.y2 = y2

    def Annotate(self, im, color=None, width=1):
        if color is None:
            color = NextColor()
        cv2.line(im.im, self.P1, self.P2, color, width)

    @property
    def p1(self):
        return (self.x1, self.y1)

    @property
    def p2(self):
        return (self.x2, self.y2)


class RightRect(object):
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

    def AsPayload(self):
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

    def TopY(self, x=None):
        return self.y_min


def RightRectFromOpenCvImage(im):
    shape = im.shape
    return RightRect(0, shape[0], 0, shape[1])


def RightFromPayload(payload):
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


def RightRectFromSymbolicYX(im, y_range, x_range):
    height, width, channels = im.shape
    y_min = ResolveSymbolicIndex(y_range[0], height)
    y_max = ResolveSymbolicIndex(y_range[1], height)
    x_min = ResolveSymbolicIndex(x_range[0], width)
    x_max = ResolveSymbolicIndex(x_range[1], width)
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if y_min > y_max:
        y_min, y_max = y_max, y_min
    return RightRect(y_min, y_max, x_min, x_max)


def RightRectFromSymbolicPP(im, p1, p2):
    if im is None:
        return None
    if len(im.shape) > 2:
        height, width, channels = im.shape
    else:
        height, width = im.shape
        channels = 1
    x_min = ResolveSymbolicIndex(p1[0], width)
    y_min = ResolveSymbolicIndex(p1[1], height)
    x_max = ResolveSymbolicIndex(p2[0], width, x_min)
    y_max = ResolveSymbolicIndex(p2[1], height, y_min)
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if y_min > y_max:
        y_min, y_max = y_max, y_min
    return RightRect(y_min, y_max, x_min, x_max)


class Robogames(object):
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
        image = ColorMask(image, colors=colors)
        # bw_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        # bw_image = cv2.blur(bw_image.copy(), (5,5))
        if RACE_BLUR:
            image = cv2.GaussianBlur(image.copy(), (5, 5), 0)
        if RACE_CANNY:
            image = AutoCanny(image, 0.33)
        # (imgxx, opencv_contours, hierarchy) = cv2.findContours(canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        self.h_lines = cv2.HoughLinesP(
            image, 1, np.pi / 180, 15, minLineLength=50, maxLineGap=30
        )
        self.map_lines = []
        self.avg_slope = 0

    def ProcessLines(self):
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

    def FilterLines(self):
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

    def SelectLines(self):
        print("FILTERED", len(self.filtered_lines))
        self.rectangles = []
        self.selectedLines = []
        Allpoints = []
        for thisX in self.filtered_lines:
            this = thisX[1]
            points = [this[5], this[6]]
            Allpoints += points
        self.MakeRec(Allpoints)

    def SelectCone(self):
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
    def __init__(
        self,
        fpath=None,
        Crop=None,
        CroppedHeight=None,
        CannyMethod=1,
        ContourFill="b",
        ContourOutline=True,
        DoFilterContours=True,
        ColorBalance="c",
        Blur="x",
    ):
        self.img_fpath = fpath
        self.img_crop = Crop
        self.img_cropped_height = CroppedHeight
        self.img_blur_method = Blur
        self.img_canny_method = CannyMethod
        self.img_color_balance_method = ColorBalance
        self.img_annotated = None  # OpenCV annotated image object
        self.img_source_dir = ""
        self.img_fname_suffix = ""
        self.annotate_fill_method = ContourFill
        self.annotate_contour_outline = ContourOutline
        self.annotate_opencv_contours = True
        self.do_image_filter_contours = DoFilterContours
        self.img_contour_colors = "r"
        self.img_contour_colors = "wy"
        self.snap_shots = []
        self.snap_titles = []
        self.do_save_snaps = True
        self.vert_line = None
        self.horz_line = None

    def FindLines(self, image=None):
        if image is None:
            fpath = os.path.join(
                self.img_source_dir, self.img_fpath + self.img_fname_suffix + ".jpg"
            )
            print(fpath)
            image = cv2.imread(fpath)
        DrawGrid(self.Snapshot(image, "Original"))

        start_clock = time.clock()
        if self.img_color_balance_method == "c":
            image = simplest_cb(image, 20)
        self.Snapshot(image, "ColorBalanced")

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
            print(
                "Crop: (%d, %d) start (%d, %d) width %d"
                % (width, height, c_x, c_y, c_w)
            )
            cropped_image = image[c_y:height, c_x : c_x + c_w]
            self.Snapshot(cropped_image, "Cropped")
        else:
            cropped_image = image.copy()

        # bw img
        bw_image = cv2.cvtColor(cropped_image, cv2.COLOR_BGR2GRAY)
        self.Snapshot(bw_image, "BW")
        if self.img_blur_method == "g":
            bw_image = cv2.Gaussianself.img_blur_method(bw_image, (21, 21), 0)
        elif self.img_blur_method == "b":
            bw_image = cv2.blur(bw_image.copy(), (5, 5))  # or maybe (3,3)
        elif self.img_blur_method == "c":
            bw_image = ColorKey(bw_image)
        elif self.img_blur_method == "f":
            bw_image = cv2.bilateralFilter(bw_image.copy(), 11, 17, 17)
        elif self.img_blur_method == "h":
            bw_image = cv2.equalizeHist(bw_image.copy())
        elif self.img_blur_method == "z":
            bw_image = simplest_cb(bw_image.copy(), 20)
        self.Snapshot(bw_image, "Blurred")

        if self.img_canny_method == 1:
            canny_image = AutoCanny(bw_image, 0.33)
        elif self.img_canny_method == 2:
            # based on pyimagesearch method
            canny_image = cv2.Canny(bw_image, 30, 200)
        (imgxx, opencv_contours, hierarchy) = cv2.findContours(
            canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )
        print("Contour Ct:", len(opencv_contours))

        print("FindLines() elapsed time:", time.clock() - start_clock)
        if self.do_image_filter_contours:
            contours = FilterContours(
                cropped_image, opencv_contours, SelectColors=self.img_contour_colors
            )
            print("Filtered Contour Ct:", len(contours))
            self.ClassifyContours(cropped_image, contours)
        else:
            contours = opencv_contours
        print("FindLines() elapsed time:", time.clock() - start_clock)

        annotated_cropped_image = cropped_image.copy()
        outline_color = (0, 255, 0)  # green
        opencv_color = (255, 0, 0)  # red
        path_guide_color = (0, 255, 255)
        if self.annotate_opencv_contours:
            cv2.drawContours(
                annotated_cropped_image, opencv_contours, -1, opencv_color, 1
            )

        if self.vert_line is not None:
            cv2.line(
                annotated_cropped_image,
                self.vert_line[0],
                self.vert_line[1],
                path_guide_color,
                2,
            )
        if self.horz_line is not None:
            print("HORZ", self.horz_line)
            cv2.line(
                annotated_cropped_image,
                self.horz_line[0],
                self.horz_line[1],
                path_guide_color,
                2,
            )

        print("FindLines() elapsed time:", time.clock() - start_clock)
        if self.annotate_fill_method == "b":
            self.AnnotateContourBoxes(annotated_cropped_image, contours)
        elif self.annotate_fill_method == "f":
            self.DrawContourFilled(annotated_cropped_image, contours)

        print("FindLines() elapsed time:", time.clock() - start_clock)
        if self.annotate_contour_outline:
            outline_color = (0, 255, 0)  # green
            cv2.drawContours(annotated_cropped_image, contours, -1, outline_color, 1)
        self.img_annotated = self.Snapshot(annotated_cropped_image, "Annotated")

        self.WriteSnapshots()

        return self.img_annotated

    def WriteSnapshots(self):
        if not self.do_save_snaps:
            return
        delete_pattern = self.img_fpath + "_D*.jpg"
        dir = self.img_source_dir
        if dir == "":
            dir = "."
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
            [vx, vy, x, y] = cv2.fitLine(
                vert_points, cv2.DIST_L1, 0, 0.01, 0.01
            )  # four points
            left_y = int((-x * vy / vx) + y)
            right_y = int(((width - x) * vy / vx) + y)
            if (
                (left_y >= 0)
                and (left_y <= height)
                and (right_y >= 0)
                and (right_y <= height)
            ):
                self.vert_line = ((width - 1, right_y), (0, left_y))
        print(self.vert_line)
        #
        horz_points = np.asarray(horz_contours)
        print("Horz:", horz, mean(horz), "Points:", horz_points)
        self.horz_line = None
        if len(horz_points) > 0:
            [vx, vy, x, y] = cv2.fitLine(
                horz_points, cv2.DIST_L1, 0, 0.01, 0.01
            )  # four points
            left_y = int((-x * vy / vx) + y)
            right_y = int(((width - x) * vy / vx) + y)
            if (
                (left_y >= 0)
                and (left_y <= height)
                and (right_y >= 0)
                and (right_y <= height)
            ):
                self.horz_line = ((width - 1, right_y), (0, left_y))

    def Snapshot(self, image, title="image"):
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
        area_threshold = 1  # minimum area sized contour to draw
        for this_c in cnts:
            area = cv2.contourArea(this_c)
            if area < area_threshold:
                continue
            peri = cv2.arcLength(this_c, True)
            approx = cv2.approxPolyDP(this_c, 0.02 * peri, True)
            rect = cv2.minAreaRect(this_c)
            box = cv2.boxPoints(rect)
            box = np.int0(box)
            cv2.drawContours(img, [box], 0, (0, 0, 255), 2)


def CalcRectCenterline(cvRect):
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


def CreateContours(src, w, h):
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
        # vertical.append(box)
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
        cv2.line(img, (x, 0), (x, width), (255, 0, 0), 1)
    for y in range(grid_incr, height, grid_incr):
        cv2.line(img, (0, y), (width, y), (255, 0, 0), 1)


def test_old():
    fn = "R20170325021241_1_0001.jpeg"
    fn = "R20170325021241_2_0001.jpeg"
    im = cv2.imread("temp/" + fn)
    p = Race(im)
    p.ProcessLines()
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
    brain.FindLines()
    stop_time = time.clock()
    print("Elapsed Time:", (stop_time - start_time))


def test_ColorMask():
    fn = "test_images/red_strap.jpeg"
    fn = "test_images/red_strap_box.jpeg"
    fn = "test_images/white_line.jpeg"
    im = cv2.imread(fn)
    bw = ColorMask(im, colors=[HSV_WHITE, HSV_RED], wthreshold=5)  # red, yellow

    cv2.imshow("c", im)
    cv2.imshow("bw", bw)
    cv2.waitKey()


def test_Cone():
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
    r.ProcessLines()
    bw = r.annotated

    # bw = ColorMask(im, colors=[HSV_RED], threshold=150)
    # bw = np.bitwise_xor(bw, 255)
    # canny_image = AutoCanny(bw, 0.33)
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
    # test_ColorMask()
    test_Cone()
