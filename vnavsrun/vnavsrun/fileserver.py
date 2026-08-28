import os
import sys

import cv2
import numpy as np

from ezcomms import vnavs_comms as vcomms

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


class FileServer(vcomms.SocketWrapperServer):
    __slots__ = "file_dirs"

    def __init__(self, verbose=True):
        super().__init__(
            buffer_len=vcomms.TCPIP_XFR_BUFLEN, ini_section="FileServer", verbose=verbose
        )
        self.file_dirs = {}
        specs = self.config.items("FileServer")
        print("FileServer", specs)
        for key, value in specs:
            # the ini modules translates keys to lower case, so dir codes must be lower case
            if key[0] == "x":
                code = key[1:]
                path = os.path.expanduser(value)
                self.file_dirs[code] = path

    @staticmethod
    def _maybe_resize(file_bytes, filename, max_width, max_height):
        if max_width == 0 and max_height == 0:
            return file_bytes
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _IMAGE_EXTENSIONS:
            return file_bytes
        arr = np.frombuffer(file_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        if img is None:
            return file_bytes
        h, w = img.shape[:2]
        scales = []
        if max_width > 0:
            scales.append(max_width / w)
        if max_height > 0:
            scales.append(max_height / h)
        scale = min(scales)
        if scale >= 1.0:
            return file_bytes
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        _, encoded = cv2.imencode(ext, img)
        return encoded.tobytes()

    def process_message(self, s, message):
        dir_code = message[0]
        source_dir = self.file_dirs[dir_code]
        fn = message[1]
        fp = os.path.join(source_dir, fn)
        print("FS", dir_code, fn, fp, message)
        try:
            f = open(fp, "rb")
            c = f.read()
            f.close()
        except IOError as e:
            # IOError: [Errno 2] No such file or directory: '/bot1/images/R20170513114208_0_11202.jpeg'
            if e.errno == 2:
                self.queue_message_str("0\x00", s=s)
                return
            else:
                raise
        if len(message) >= 4:
            max_w = int(message[2])
            max_h = int(message[3])
            c = self._maybe_resize(c, fn, max_w, max_h)
        print("SEND FILE", fp, len(c))
        ix = 0
        while ix < len(c):
            rec = c[ix : ix + self.buffer_len]
            if ix == 0:
                rec = (
                    repr(len(c)).encode() + "\x00".encode() + rec
                )  # add file size to first block
            self.queue_message_str(rec, s=s)
            ix += self.buffer_len


if __name__ == "__main__":
    if "verbose" in sys.argv:
        print("verbose")
        verbose = True
    else:
        print("QUIET")
        verbose = False
    if sys.argv[1] == "f":
        # s = FileServer(verbose=verbose)
        s = FileServer(verbose=False)
        s.server()
    elif sys.argv[1] == "s":
        vcomms.status_info()
