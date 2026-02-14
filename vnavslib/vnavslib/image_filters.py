import numpy as np

from vnavslib import opticchiasm as oc
from ezcomms import vnavs_data as vdata

vdata.DataAttribIntList._oc_module = oc


class ImageFilterCollection:
    image_filters = {}
    image_filter_names = []


class ImageFilter:
    __slots__ = ("annotate_code", "clsdata", "flags", "code", "name", "parms")

    def __init__(self, name, code, parms, flags=None):
        self.name = name
        self.code = code
        self.parms = parms  # a list of vdata.DataAttrib() and descendent objects
        self.flags = flags  # a list of string flag names
        self.annotate_code = None
        self.clsdata = ImageFilterCollection
        self.clsdata.image_filters[name] = self
        self.clsdata.image_filter_names.append(name)
        self.clsdata.image_filter_names.sort()


FILTER_NAME_ANALYZER = "Analyzer"
FILTER_NAME_COLORMASK_MULTI = "ColorMaskMulti"
FILTER_NAME_COLORMASK_SINGLE = "ColorMaskSingle"
FILTER_NAME_CROPPP = "CropPP"
FILTER_NAME_IMAGE = "Image"

FLAG_ISBASE = "isbase"
FLAG_SLIDERS = "sliders"


#
# Filter code is processed with exec with available globals OpticCiasm, cv2,
# 	previous step exec_im and its shape as im, h, w and c,
# 	xstep is the current ProcessStep() with exec_im set to None.
#
ImageFilter(
    FILTER_NAME_IMAGE, "{x_output_im} = xstep.source_im.copy()", [], flags=[FLAG_ISBASE]
)

ImageFilter(
    FILTER_NAME_COLORMASK_MULTI,
    "{x_output_im} = oc.Image(oc.color_mask(im_in.im_as_hsv(), colors=[{colors}], huerange={hueRange},"
    + " saturation={saturation}, saturationrange={saturationRange},"
    + " value={value}, valuerange={valueRange})",
    [
        vdata.DataAttribIntList("colors", "oc.HSV_WHITE, oc.HSV_RED"),
        vdata.DataAttribInt(
            "hueRange", "25", min_value=0, max_value=oc.HSV_MAX_HUE, use_slider=True
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
        vdata.DataAttribStr("colorcode", oc.IM_HSV),
    ],
    flags=[],
)

ImageFilter(
    FILTER_NAME_COLORMASK_SINGLE,
    "{x_output_hsvspec} = oc.HsvSpec("
    + " hue={hue}, huerange={hueRange},"
    + " saturation={saturation}, saturationrange={saturationRange},"
    + " value={value}, valuerange={valueRange})\n"
    '{x_output_im} = oc.Image(oc.color_mask_one_hue(im_in.im_as_any("{colorcode}"), {x_output_hsvspec}),'
    + "	colorcode=oc.IM_GRAY)",
    [
        vdata.DataAttribInt(
            "hue", "25", min_value=0, max_value=oc.HSV_MAX_HUE, use_slider=True
        ),
        vdata.DataAttribInt(
            "hueRange", "25", min_value=0, max_value=oc.HSV_MAX_HUE, use_slider=True
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
        vdata.DataAttribStr("colorcode", oc.IM_HSV),
    ],
    flags=[FLAG_SLIDERS],
)

image_filter = ImageFilter(
    FILTER_NAME_CROPPP,
    "{x_output_rect} = im_in.right_rect_from_symbolic_pp({p1}, {p2})\n"
    + "{x_output_im} = im_in.crop({x_output_rect})\n"
    + "print(im_in.shape, {x_output_rect})\n",
    [
        vdata.DataAttribPointSym("p1", "m-50,m+50"),
        vdata.DataAttribPointSym("p2", "-100,e"),
    ],
    flags=[],
)
image_filter.annotate_code = (
    "{x_output_annotated} = im_base.copy()\n"
    + "{x_output_annotated}.draw_rectangle({x_output_rect}, color=oc.DRAW_BGR_GREEN, thickness=2)\n"
)

image_filter = ImageFilter(
    "CropYX",
    "{x_output_rect} = im_in.right_rect_from_symbolic_yx({y_range}, {x_range})\n"
    + "{x_output_im} = im_in.crop({x_output_rect})\n"
    + "print(im_in.shape, {x_output_rect})\n",
    [
        vdata.DataAttribPointSym("y_range", "-100,"),
        vdata.DataAttribPointSym("x_range", "m-50,m+50"),
    ],
    flags=[],
)
image_filter.annotate_code = (
    "{x_output_annotated} = im_base.copy()\n"
    + "{x_output_annotated}.draw_rectangle({x_output_rect}, color=oc.DRAW_BGR_GREEN, thickness=2)\n"
)

ImageFilter("Gray", "{x_output_im} = im_in.copy_as_gray()", [], flags=[])

ImageFilter(
    "Blur",
    "{x_output_im} = oc.Image(im=cv2.blur(im_in.im, {ksize}), colorcode=im_in.colorcode)",
    [vdata.DataAttribPoint("ksize", "3,3")],
    flags=[],
)

ImageFilter(
    "Cameraman",
    '{x_output_im} = oc.cameraman_snapshot(im_in, "{path}", "{fn}")',
    [
        vdata.DataAttribStr("path", "./scripts"),
        vdata.DataAttribStr("fn", "test.cam"),
    ],
    flags=[],
)

ImageFilter(
    "BlurBilateralFilter",
    "{x_output_im} = oc.Image(im=cv2.bilateralFilter(im_in.im, {diameter}, {sigmaColor}, {sigmaSpace}), colorcode=im_in.colorcode)",
    [
        vdata.DataAttribInt("diameter", "5"),
        vdata.DataAttribInt("sigmaColor", "17"),
        vdata.DataAttribInt("sigmaSpace", "17"),
    ],
    flags=[],
)
# diameter > 5 is very slow, use 5 for real time processing or 9 for off-line heavy image_filtering
# the two sigma values are often the same value. <10 doesn't do much, >150 is cartoonish

ImageFilter(
    "BlurGaussian",
    "{x_output_im} = oc.Image(im=cv2.GaussianBlur(im_in.im, {ksize}, {sigmaX}), colorcode=im_in.colorcode)",
    [vdata.DataAttribPoint("ksize", "3,3"), vdata.DataAttribFloat("sigmaX", "0.0")],
    flags=[],
)

ImageFilter(
    "BlurMedian",
    "{x_output_im} = oc.Image(im=cv2.medianBlur(im_in.im, {ksize}), colorcode=im_in.colorcode)",
    [vdata.DataAttribInt("ksize", "3")],
    flags=[],
)

ImageFilter(
    "Canny",
    "{x_output_im} = oc.Image(im=cv2.Canny(im_in.im_as_gray(), {threshold1}, {threshold2}), colorcode=oc.IM_GRAY)",
    [
        vdata.DataAttribFloat("threshold1", "100"),
        vdata.DataAttribFloat("threshold2", "300"),
    ],
    flags=[],
)

ImageFilter(
    "CannyAuto",
    "{x_output_im} = oc.Image(im=oc.auto_canny(im_in.im_as_gray(), {sigma}), colorcode=oc.IM_GRAY)",
    [vdata.DataAttribFloat("sigma", "0.33")],
    flags=[],
)

image_filter = ImageFilter(
    "ChaseLine", "line_points = im_base.chase_line(hsvspec_in, rect_in)", [], flags=[]
)
# ChaseLine depends on previous rect and hsvspec. These probably changed im_in to a
# black and while image from HueMaskSingle or similar. This therefore uses
# im_base to reset to the original color image
image_filter.annotate_code = (
    "{x_output_annotated} = im_base.copy()\n"
    + "{x_output_annotated}.draw_line_points(line_points, color=oc.DRAW_BGR_GREEN, thickness=2)\n"
)


ImageFilter(
    "ColorBalance",
    "{x_output_im} = oc.simplest_cb(im, {pct})",
    [vdata.DataAttribInt("pct", "20")],
    flags=[],
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
    flags=[],
)

ImageFilter(
    "MorphDilate",
    "kernel = np.ones(({kernel_dim}, {kernel_dim}), np.uint8)\n"
    + "{x_output_im} = oc.Image(im=cv2.dilate(im_in.im, kernel, iterations={iterations}),\n"
    + "			colorcode=im_in.colorcode)\n",
    [vdata.DataAttribInt("kernel_dim", "5"), vdata.DataAttribInt("iterations", "1")],
    flags=[],
)

ImageFilter(
    "MorphErode",
    "kernel = np.ones(({kernel_dim}, {kernel_dim}), np.uint8)\n"
    + "{x_output_im} = oc.Image(im=cv2.erode(im_in.im, kernel, iterations={iterations}),\n"
    + "			colorcode=im_in.colorcode)\n",
    [vdata.DataAttribInt("kernel_dim", "5"), vdata.DataAttribInt("iterations", "1")],
    flags=[],
)

ImageFilter(
    "MorphGradient",
    "kernel = np.ones(({kernel_dim}, {kernel_dim}), np.uint8)\n"
    + "{x_output_im} = oc.Image(im=cv2.morphologyEx(im_in._im, cv2.MORPH_GRADIENT, kernel, iterations={iterations}),\n"
    + "			colorcode=im_in.colorcode)\n",
    [vdata.DataAttribInt("kernel_dim", "5"), vdata.DataAttribInt("iterations", "1")],
    flags=[],
)

ImageFilter(
    "MorphOpen",
    "kernel = np.ones(({kernel_dim}, {kernel_dim}), np.uint8)\n"
    + "{x_output_im} = oc.Image(im=cv2.morphologyEx(im_in._im, cv2.MORPH_OPEN, kernel, iterations={iterations}),\n"
    + "			colorcode=im_in.colorcode)\n",
    [vdata.DataAttribInt("kernel_dim", "5"), vdata.DataAttribInt("iterations", "1")],
    flags=[],
)

#
# Contour Filters
#
# findContours modifies the soure image. The image is assumed to be binary, ususally from canny
# somewhere along line cont2 eliminated
#'cont2, {x_output_contours}, {x_output_hierarchy} = cv2.findContours(im_in.im_as_gray(copy=True), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)\n',
image_filter = ImageFilter(
    "ContoursFind",
    "{x_output_contours}, {x_output_hierarchy} = cv2.findContours(im_in.im_as_gray(copy=True), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)\n",
    [
        vdata.DataAttribInt("MaxLevel", "-1"),
    ],
    flags=[],
)
# image_filter.annotate_code = '{x_output_annotated} = im_base.copy_as_gray().copy_as_bgr()\n' \
# 				+ 'print("Contour", len({x_output_contours}))\n' \
# 				+ 'for i in range(0, len({x_output_contours})):\n' \
# 				+ '    color = (np.random.randint(0, 255), np.random.randint(0, 255), np.random.randint(0, 255))\n' \
# 				+ '    cv2.drawContours({x_output_annotated}._im, {x_output_contours}, i, color, 3)\n' \
#                               + 'print("Contour", color)\n'
# 			+ 'oc.contours_to_line_vectors({x_output_annotated}.im, {x_output_contours}, {x_output_hierarchy})\n' \
# 			+ 'oc.crayola_contours({x_output_annotated}.im, {x_output_contours}, {x_output_hierarchy}, max_level={MaxLevel})\n' \
# 			+ 'cv2.drawContours({x_output_annotated}.im, {x_output_contours}, -1, oc.DRAW_BGR_RED, 1)\n' \

image_filter.annotate_code = (
    "{x_output_annotated} = im_in.copy_as_bgr()\n"
    + "cv2.drawContours({x_output_annotated}._im, {x_output_contours}, -1, (0, 0, 255), 3)\n"
)
# 			+ 'print("Contour", len(contours_in))\n' \

ImageFilter(
    "EqualizeHistogram",
    "{x_output_im} = oc.Image(im=cv2.equalizeHist(im_in.im_as_gray()), colorcode=oc.IM_GRAY)",
    [],
    flags=[],
)

ImageFilter("HistogramCB", "oc.histogram_cb(im)", [], flags=[])

image_filter = ImageFilter(
    FILTER_NAME_ANALYZER,
    "r = im_base.right_rect_from_symbolic_pp({p1}, {p2})\n",
    [
        vdata.DataAttribPointSym("p1", "m-3,m-3"),
        vdata.DataAttribPointSym("p2", "p+3,p+3"),
    ],
    flags=[],
)
image_filter.annotate_code = (
    "{x_output_annotated} = im_base.copy()\n"
    + "{x_output_annotated}.draw_rectangle(r, color=oc.DRAW_BGR_GREEN, thickness=2)\n"
    + 'xstep.SetInfo(0, "Hue", im_base.crop(r).average_hue())\n'
)

image_filter = ImageFilter(
    "HoughLinesP",
    "{x_output_objects} = oc.hough_lines_p(im_in, min_line_length={MinLineLength}, max_line_gap={MaxLineGap})",
    [vdata.DataAttribInt("MinLineLength", "30"), vdata.DataAttribInt("MaxLineGap", 10)],
    flags=[""],
)
image_filter.annotate_code = (
    "{x_output_annotated} = im_base.copy()\n"
    + "print(f'HoughLinesP: {{len({x_output_objects})}} lines')\n"
    + "oc.init_color()\n"
    + "for this in {x_output_objects}:\n"
    + "    this.annotate({x_output_annotated})\n"
)

ImageFilter(
    "Map", "cv2.warpPerspective(im, transform, (int(w*3), int(h*4)))", [], flags=[]
)
