import io
import socket
import time
import picamera
from picamera.array import PiRGBArray
#from PIL import Image
import OpticChiasm
import cv2

class Method1(object):
    # from http://raspberrypi.stackexchange.com/questions/22040/take-images-in-a-short-time-using-the-raspberry-pi-camera-module
    def outputs(self):
        stream = io.BytesIO()
        for i in range(40):
            # This returns the stream for the camera to capture to
            yield stream
            # Once the capture is complete, the loop continues here
            # (read up on generator functions in Python to understand
            # the yield statement). Here you could do some processing
            # on the image...
            #stream.seek(0)
            #img = Image.open(stream)
            # Finally, reset the stream for the next capture
            stream.seek(0)
            stream.truncate()

    def Run(self):
        with picamera.PiCamera() as camera:
            camera.resolution = (640, 480)
            camera.framerate = 80
            time.sleep(2)
            start = time.time()
            camera.capture_sequence(self.outputs(), 'jpeg', use_video_port=True)
            finish = time.time()
            print('Captured 40 images at %.2ffps' % (40 / (finish - start)))

class Method2(object):
    def Run(self):
        with picamera.PiCamera() as camera:
            camera.resolution = (640, 480)
            camera.framerate = 80
            #camera.start_preview()
            start = time.time()
            try:
                for i, filename in enumerate(camera.capture_continuous('temp/T{counter:02d}.jpg')):
                    print(filename)
                    if i == 40:
                        break
            finally:
                pass
                #camera.stop_preview()
            finish = time.time()
            print('Captured 40 images at %.2ffps' % (ix / (finish - start)))


class Method3(object):
    def Run(self):
        camera = picamera.PiCamera()
        camera.resolution = (640, 480)
        camera.framerate = 80
        rawCapture = PiRGBArray(camera, size=(640, 480))
 
        # allow the camera to warmup
        time.sleep(0.1)
 
        # capture frames from the camera
        write_file = False
        write_file = True
        canny_image = False
        canny_image = True
        capture_ct = 20
        start = time.time()
        for ix, frame in enumerate(camera.capture_continuous(rawCapture, format="bgr", use_video_port=True)):
            # grab the raw NumPy array representing the image, then initialize the timestamp
            # and occupied/unoccupied text
            image = frame.array
            if canny_image:
                imagex = image[240:480, 220:420]
                bw_image = cv2.blur(imagex, (5,5))  # or maybe (3,3)
                c_image = OpticChiasm.auto_canny(bw_image, 0.33) 
            if write_file:
                fn = 'temp/Z{counter:02d}.jpg'.format(counter=ix)
                cv2.imwrite(fn, image)
            # clear the stream in preparation for the next frame
            rawCapture.truncate(0)
            if ix >= capture_ct:
                break
        finish = time.time()
        print('Captured %d images at %.2ffps' % (capture_ct, capture_ct / (finish - start)))
 
class Method4(object):
    def __init__(self):
        self.ims = []

    def Run(self):
        camera = picamera.PiCamera()
        camera.resolution = (640, 480)
        camera.framerate = 80
        rawCapture = PiRGBArray(camera, size=(640, 480))
 
        # allow the camera to warmup
        time.sleep(0.1)
 
        # capture frames from the camera
        capture_ct = 10
        start = time.time()
        for ix, frame in enumerate(camera.capture_continuous(rawCapture, format="bgr", use_video_port=True)):
            print ix
            img = frame.array.copy()
            imgRGB = cv2.cvtColor(img,cv2.COLOR_BGR2RGB)
            r, jpg = cv2.imencode(".jpg",imgRGB)
            self.ims.append(jpg)
            rawCapture.truncate(0)
            if ix >= capture_ct:
                break
        finish = time.time()
        print('Captured %d images at %.2ffps' % (capture_ct, capture_ct / (finish - start)))

    def Writer(self):
        server_ip = "192.168.8.11"
        server_socket = 3050
        capture_ct = 0
        start = time.time()
        for this_im in self.ims:
            capture_ct += 1
            s = socket.socket()
            s.connect((server_ip, server_socket))
            ix = 0
            im_size = len(this_im)
            while ix < im_size:
                ix_end = ix + 1024
                if ix_end > im_size:
                    ex_end = im_size
                s.send(this_im[ix:ix_end])
                ix += 1024
            s.close()
        finish = time.time()
        print('Sent %d images at %.2ims' % (capture_ct, capture_ct / (finish - start)))


a = Method4()
a.Run()
a.Writer()
