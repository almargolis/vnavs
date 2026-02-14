import math
import os
import re
import time

import cv2
import numpy as np

from vnavslib import opticchiasm as oc


class ImageAnalyzer:
    def __init__(
        self,
        fpath=None,
        crop=None,
        cropped_height=None,
        canny_method=1,
        contour_fill="b",
        contour_outline=True,
        do_filter_contours=True,
        color_balance="c",
        blur="x",
    ):
        self.img_fpath = fpath
        self.img_crop = crop
        self.img_cropped_height = cropped_height
        self.img_blur_method = blur
        self.img_canny_method = canny_method
        self.img_color_balance_method = color_balance
        self.img_annotated = None  # OpenCV annotated image object
        self.img_source_dir = ""
        self.img_fname_suffix = ""
        self.annotate_fill_method = contour_fill
        self.annotate_contour_outline = contour_outline
        self.annotate_opencv_contours = True
        self.do_image_filter_contours = do_filter_contours
        self.img_contour_colors = "r"
        self.img_contour_colors = "wy"
        self.snap_shots = []
        self.snap_titles = []
        self.do_save_snaps = True
        self.vert_line = None
        self.horz_line = None

    def find_lines(self, image=None):
        if image is None:
            fpath = os.path.join(
                self.img_source_dir, self.img_fpath + self.img_fname_suffix + ".jpg"
            )
            print(fpath)
            image = cv2.imread(fpath)
        draw_grid(self.snapshot(image, "Original"))

        start_clock = time.clock()
        if self.img_color_balance_method == "c":
            image = oc.simplest_cb(image, 20)
        self.snapshot(image, "ColorBalanced")

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
            self.snapshot(cropped_image, "Cropped")
        else:
            cropped_image = image.copy()

        # bw img
        bw_image = cv2.cvtColor(cropped_image, cv2.COLOR_BGR2GRAY)
        self.snapshot(bw_image, "BW")
        if self.img_blur_method == "g":
            bw_image = cv2.Gaussianself.img_blur_method(bw_image, (21, 21), 0)
        elif self.img_blur_method == "b":
            bw_image = cv2.blur(bw_image.copy(), (5, 5))  # or maybe (3,3)
        elif self.img_blur_method == "c":
            bw_image = color_key(bw_image)
        elif self.img_blur_method == "f":
            bw_image = cv2.bilateralFilter(bw_image.copy(), 11, 17, 17)
        elif self.img_blur_method == "h":
            bw_image = cv2.equalizeHist(bw_image.copy())
        elif self.img_blur_method == "z":
            bw_image = oc.simplest_cb(bw_image.copy(), 20)
        self.snapshot(bw_image, "Blurred")

        if self.img_canny_method == 1:
            canny_image = oc.auto_canny(bw_image, 0.33)
        elif self.img_canny_method == 2:
            # based on pyimagesearch method
            canny_image = cv2.Canny(bw_image, 30, 200)
        (imgxx, opencv_contours, hierarchy) = cv2.findContours(
            canny_image.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )
        print("Contour Ct:", len(opencv_contours))

        print("find_lines() elapsed time:", time.clock() - start_clock)
        if self.do_image_filter_contours:
            contours = filter_contours(
                cropped_image, opencv_contours, select_colors=self.img_contour_colors
            )
            print("Filtered Contour Ct:", len(contours))
            self.classify_contours(cropped_image, contours)
        else:
            contours = opencv_contours
        print("find_lines() elapsed time:", time.clock() - start_clock)

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

        print("find_lines() elapsed time:", time.clock() - start_clock)
        if self.annotate_fill_method == "b":
            self.annotate_contour_boxes(annotated_cropped_image, contours)
        elif self.annotate_fill_method == "f":
            self.draw_contour_filled(annotated_cropped_image, contours)

        print("find_lines() elapsed time:", time.clock() - start_clock)
        if self.annotate_contour_outline:
            outline_color = (0, 255, 0)  # green
            cv2.drawContours(annotated_cropped_image, contours, -1, outline_color, 1)
        self.img_annotated = self.snapshot(annotated_cropped_image, "Annotated")

        self.write_snapshots()

        return self.img_annotated

    def write_snapshots(self):
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

    def classify_contours(self, img, contours):
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
            ctr_line = calc_rect_centerline(rect)
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

    def snapshot(self, image, title="image"):
        """
        snapshot() makes and saves a copy of the image. In operational mode,
        the save can be globally turned off. The copy is still made so
        clients can use this as a general image copy function, even if
        the save operation is off.
        """
        snap = image.copy()
        if self.do_save_snaps:
            self.snap_shots.append(snap)
            self.snap_titles.append(title)
        return snap

    def annotate_contour_boxes(self, img, cnts):
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


# Helper functions used by ImageAnalyzer methods above.
# These were module-level functions in opticchiasm.py.

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


def color_key(img):
    channels = cv2.split(img)
    print("CK channels:", len(channels))
    threshold = 200

    out_channels = []
    for channel in channels:
        # This really only works for one channel
        mask = channel <= threshold
        thresholded = oc.apply_mask(channel, mask, 0)
        mask = channel > threshold
        thresholded = oc.apply_mask(thresholded, mask, 255)
        # scale the channel
        # normalized = cv2.normalize(thresholded, thresholded.copy(), 0, 255, cv2.NORM_MINMAX)
        normalized = thresholded
        out_channels.append(normalized)

    return cv2.merge(out_channels)


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


def draw_grid(img):
    grid_incr = 25
    height, width, channels = img.shape
    for x in range(grid_incr, width, grid_incr):
        cv2.line(img, (x, 0), (x, width), (255, 0, 0), 1)
    for y in range(grid_incr, height, grid_incr):
        cv2.line(img, (0, y), (width, y), (255, 0, 0), 1)


def filter_contours(img, contours, select_colors="r"):
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
        color_str = color_string(avg_color)
        this_c = contours[i]
        area = cv2.contourArea(this_c)
        if color_str[0] in select_colors:
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
