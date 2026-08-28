import configparser

import cv2
import numpy as np
from cvpipeline import opticchiasm as oc
from vnavsrun import cameraman


def _make_cameraman():
    """Create a Cameraman instance without calling __init__."""
    cam = object.__new__(cameraman.Cameraman)
    cam.blob_specs = {}
    return cam


def _cameraman_with_config(cameraman_section):
    cam = object.__new__(cameraman.Cameraman)
    cam.config = configparser.ConfigParser()
    cam.config.read_dict({"Cameraman": cameraman_section})
    return cam


def test_read_camera_options_flips_and_controls():
    cam = _cameraman_with_config(
        {"HFlip": "1", "VFlip": "1", "Controls": '{"Sharpness": 2.0, "FrameRate": 40}'}
    )
    hflip, vflip, controls = cam.read_camera_options()
    assert hflip is True
    assert vflip is True
    assert controls == {"Sharpness": 2.0, "FrameRate": 40}


def test_read_camera_options_defaults_when_absent():
    cam = object.__new__(cameraman.Cameraman)
    cam.config = configparser.ConfigParser()  # no [Cameraman] section
    assert cam.read_camera_options() == (False, False, {})


def test_read_camera_options_bad_controls_json_ignored():
    cam = _cameraman_with_config({"VFlip": "1", "Controls": "{not json}"})
    hflip, vflip, controls = cam.read_camera_options()
    assert (hflip, vflip, controls) == (False, True, {})


def test_on_cameraman_blob_spec_set():
    cam = _make_cameraman()
    payload = {
        "action": "set",
        "label": "red_sign",
        "hue": 170,
        "huerange": 10,
        "saturation": 200,
        "saturationrange": 55,
        "value": 200,
        "valuerange": 55,
        "y_min": 0,
        "y_max": 120,
        "x_min": 0,
        "x_max": 320,
    }
    cam.on_cameraman_blob_spec(payload)
    assert "red_sign" in cam.blob_specs
    hsv_spec, rect = cam.blob_specs["red_sign"]
    assert hsv_spec.hue == 170
    assert hsv_spec.huerange == 10
    assert hsv_spec.saturation == 200
    assert rect.y_min == 0
    assert rect.y_max == 120
    assert rect.x_min == 0
    assert rect.x_max == 320


def test_on_cameraman_blob_spec_no_rect():
    cam = _make_cameraman()
    payload = {
        "action": "set",
        "label": "green_marker",
        "hue": 60,
        "huerange": 20,
        "saturation": 150,
        "saturationrange": 50,
        "value": 150,
        "valuerange": 50,
    }
    cam.on_cameraman_blob_spec(payload)
    assert "green_marker" in cam.blob_specs
    hsv_spec, rect = cam.blob_specs["green_marker"]
    assert hsv_spec.hue == 60
    assert rect is None


def test_on_cameraman_blob_spec_clear():
    cam = _make_cameraman()
    cam.blob_specs["red_sign"] = (
        oc.HsvSpec(hue=170, huerange=10),
        None,
    )
    payload = {"action": "clear", "label": "red_sign"}
    cam.on_cameraman_blob_spec(payload)
    assert "red_sign" not in cam.blob_specs


def test_on_cameraman_blob_spec_clear_all():
    cam = _make_cameraman()
    cam.blob_specs["red_sign"] = (oc.HsvSpec(hue=170), None)
    cam.blob_specs["green_marker"] = (oc.HsvSpec(hue=60), None)
    payload = {"action": "clear_all"}
    cam.on_cameraman_blob_spec(payload)
    assert cam.blob_specs == {}
