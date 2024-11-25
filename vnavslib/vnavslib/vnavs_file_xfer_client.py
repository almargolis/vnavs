FILE_TRANSFER_IDLE = 0
FILE_TRANSFER_STARTED = 1
FILE_TRANSFER_COMPLETE = 2


class FileClient(vcomms.SocketWrapperClient):
    def __init__(self, buffer_len=vcomms.TCPIP_XFR_BUFLEN, verbose=False):
        super().__init__(
            buffer_len=buffer_len,
            ini_section="FileClient",
            IsZeroOneProtocol=False,
            verbose=verbose,
        )
        self.init_file_client()

    def init_file_client(self):
        self.file_name = None
        self.file_out = None
        self.buffer = ""
        self.transfer_state = FILE_TRANSFER_IDLE
        self.start_time = 0
        self.timeout = False

    def get_file(self, dir_code, filename, path=None):
        self.start_transfer(dir_code=dir_code, filename=filename, path=path)
        while True:
            if self.check_transfer():
                return True
            if self.timeout:
                return False

    def start_transfer(self, dir_code, filename, path=None):
        self.Init()
        retry_ct = 0
        while (not self.connected) and (retry_ct < 5):
            retry_ct += 1
            # There is an issue here that effects all connects.
            # Possibly just OSX connecting to RPI, but not sure.
            # First connect fails -- or seems to
            # If you try to reconnect immediately, you get a fail
            #    socket.error: [Errno 37] Operation already in progress
            # So some patience is needed. Somewhere there is some latency or
            # inconsistency of block / no block. Or one of the OSes trying to be polite.
            time.sleep(1)
            print(
                "FileClient.start_transfer() - Attempt Connect",
                self.socket_host,
                self.socket_port,
            )
            self.Connect()
        # print("FileClient.start_transfer() - CONNECTED", self.socket_host, self.socket_port)
        self.file_name = filename
        if path is None:
            self.file_path = filename
        else:
            self.file_path = path
        self.file_out = open(self.file_path, "wb")
        self.transfer_state = FILE_TRANSFER_STARTED
        self.timeout = False
        self.buffer = bytearray()
        self.buf_sum = 0
        self.queue_message_z([dir_code, filename])
        self.start_time = time.time()
        self.select(timeout=0.1)

    def check_transfer(self, timeout=30.0):
        if self.transfer_state == FILE_TRANSFER_STARTED:
            self.select(timeout=0.1)
        if (self.transfer_state == FILE_TRANSFER_STARTED) and (
            (time.time() - self.start_time) > timeout
        ):
            self.file_out.close()
            self.transfer_state = FILE_TRANSFER_COMPLETE
            print("FileClient.check_transfer() Timeout", self.file_name)
            self.timeout = True  # stays true until next transfer started
        if self.transfer_state == FILE_TRANSFER_COMPLETE:
            self.transfer_state = FILE_TRANSFER_IDLE
            return True
        return False

    def recv_data(self, s, data):
        self.buffer += data
        self.buf_sum += len(data)
        p = self.buffer.find(b"\x00")
        # print("RCV DATA", len(data), len(self.buffer), self.buf_sum)
        if p > 0:
            try:
                file_len = int(self.buffer[:p])
            except:
                # need to do something specific here to restart / recover transfer
                # or neatly notify as not complete.
                # got an "invalid literal" exception. maybe due to noisy network.
                # raise
                # maybe we don't have enough data to figure out
                print("EX", p, len(data))
                return
            # print("FILE LEN", file_len)
            buf_len = p + file_len + 1
            if len(self.buffer) == buf_len:
                self.file_out.write(self.buffer[p + 1 :])
                self.file_out.close()
                self.transfer_state = FILE_TRANSFER_COMPLETE
                # print("FileClient.recv_data() Transfer Complete", time.time() - self.start_time, self.file_name, file_len)
