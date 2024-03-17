
import os
import sys

from vnavslib import vnavs_comms as vcomm


class FileServer(vcomm.SocketWrapperServer):
    __slots__ = "file_dirs"

    def __init__(self, verbose=True):
        super().__init__(
            BufferLen=vcomm.TCPIP_XFR_BUFLEN, ini_section="FileServer", verbose=verbose
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
                self.queue_message("0\x00", s=s)
                return
            else:
                raise
        print("SEND FILE", fp, len(c))
        ix = 0
        while ix < len(c):
            rec = c[ix : ix + self.buffer_len]
            if ix == 0:
                rec = (
                    repr(len(c)).encode() + "\x00".encode() + rec
                )  # add file size to first block
            self.queue_message(rec, s=s)
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
        vcomm.status_info()
