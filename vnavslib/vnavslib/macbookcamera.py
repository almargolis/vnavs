import cv2

from vnavslib import opticchiasm as oc


class MacbookCamera(object):
    # This s a wrapper around OpenCv image capture that makes a macbbok
    # built-in camera work like a picamera as closely as I need to.
    # This likely works on the pi too, but is probably slower because it
    # doesn't take full advantage of the hardwre for continuous reads.
    __slots__ = (
        "colorcode",
        "device_id",
        "hflip",
        "_iso",
        "vflip",
        "resolution",
        "shutter_speed",
        "source_fn",
        "_video",
    )

    def __init__(self, device_id=0, resolution=(640, 480), source_fn=None):
        # macbook default resolution was 1280x720
        self.colorcode = oc.IM_RGB
        self._iso = 0
        self.hflip = False
        self.vflip = False
        self.resolution = resolution
        self.shutter_speed = 0
        self.source_fn = source_fn
        self.device_id = device_id
        if self.source_fn is not None:
            self._video = cv2.VideoCapture(self.source_fn)
        else:
            self._video = cv2.VideoCapture(self.device_id)
            self._video.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
            self._video.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])

    @property
    def exposure_speed(self):
        return 0

    @property
    def iso(self):
        return self._iso

    @iso.setter
    def iso(self, value):
        self._iso = value

    def read(self):
        ret, frame = self._video.read()
        if frame is not None:
            self._iso = self._video.get(cv2.CAP_PROP_ISO_SPEED)
            self.shutter_speed = self._video.get(cv2.CAP_PROP_EXPOSURE)
        return ret, frame

    def capture(
        self,
        output,
        format=None,
        use_video_port=False,
        resize=None,
        splitter_port=0,
        bayer=False,
        **options
    ):
        assert isinstance(output, str)
        assert format == "jpeg"
        ret, frame = self.read()
        if frame is None:
            return False
        if isinstance(output, str):
            rgb_image = oc.BGR2RGB(frame)
            cv2.imwrite(output, rgb_image)
            return True
        else:
            return False

    def capture_opencv(self):
        ret, frame = self.read()
        return frame

    def capture_image(self):
        ret, frame = self.read()
        return oc.Image(im=frame, colorcode=oc.IM_BGR)

    def capture_continuous(
        self,
        output,
        format=None,
        use_video_port=False,
        resize=None,
        splitter_port=0,
        burst=False,
        bayer=False,
        **options
    ):
        kwargs = options
        kwargs["format"] = format
        kwargs["use_video_port"] = use_video_port
        kwargs["resize"] = resize
        kwargs["splitter_port"] = splitter_port
        kwargs["bayer"] = bayer
        ctr = 0
        while True:
            ctr += 1
            if isinstance(output, str):
                path = output.format(counter=ctr)
                if self.capture(path, **kwargs):
                    yield path
                else:
                    raise StopIteration
            else:
                self.capture(output, **kwargs)
                yield "buffer"
