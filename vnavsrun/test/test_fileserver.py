import cv2
import numpy as np

from vnavsrun import fileserver


def _make_jpeg(width, height, color=(128, 128, 128)):
    """Create a synthetic JPEG as bytes."""
    img = np.full((height, width, 3), color, dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes()


def _make_png(width, height):
    """Create a synthetic PNG as bytes."""
    img = np.full((height, width, 3), (64, 64, 64), dtype=np.uint8)
    _, encoded = cv2.imencode(".png", img)
    return encoded.tobytes()


def _decode_dims(data):
    """Decode image bytes and return (width, height)."""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
    return img.shape[1], img.shape[0]


def test_maybe_resize_jpeg_larger_than_limit():
    original = _make_jpeg(640, 480)
    resized = fileserver.FileServer._maybe_resize(original, "photo.jpg", 320, 240)
    assert resized != original
    w, h = _decode_dims(resized)
    assert w == 320
    assert h == 240


def test_maybe_resize_jpeg_smaller_than_limit():
    original = _make_jpeg(160, 120)
    result = fileserver.FileServer._maybe_resize(original, "photo.jpg", 320, 240)
    assert result is original


def test_maybe_resize_non_image_extension():
    data = b"some plain text data"
    result = fileserver.FileServer._maybe_resize(data, "notes.txt", 320, 240)
    assert result is data


def test_maybe_resize_both_zero():
    original = _make_jpeg(640, 480)
    result = fileserver.FileServer._maybe_resize(original, "photo.jpg", 0, 0)
    assert result is original


def test_maybe_resize_one_dimension_constrained():
    original = _make_jpeg(640, 480)
    resized = fileserver.FileServer._maybe_resize(original, "photo.jpg", 320, 0)
    w, h = _decode_dims(resized)
    assert w == 320
    assert h == 240


def test_maybe_resize_preserves_aspect_ratio_wide():
    original = _make_jpeg(800, 200)
    resized = fileserver.FileServer._maybe_resize(original, "pic.jpg", 0, 100)
    w, h = _decode_dims(resized)
    assert h == 100
    assert w == 400


def test_maybe_resize_png():
    original = _make_png(640, 480)
    resized = fileserver.FileServer._maybe_resize(original, "img.png", 320, 240)
    assert resized != original
    w, h = _decode_dims(resized)
    assert w == 320
    assert h == 240
