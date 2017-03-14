import socket
import sys
import time

my_ip = "192.168.8.11"
my_socket = 3050
s = socket.socket()
s.bind((my_ip, my_socket))
s.listen(10)

image_ct = 0
timer_ct = 0
timer_start = time.clock()
while True:
    sc, address = s.accept()

    #print image_ct,  address
    fn = 'temp/Q%d.jpg' % image_ct
    f = open(fn,'wb') #open in binary
    image_ct += 1
    image_sz = 0
    json_str = ''
    json_rdy = False
    socket_data = sc.recv(1024)
    while (socket_data):
        if json_rdy:
            # we are past the json packet, write the image file
            img_ix = 0
        else:
            # collect the json packet
            ix = socket_data.find(chr(26))
            if ix >= 0:
                # this is the end of the json packet
                json_str += socket_data[:ix]
                img_ix = ix + 1
                json_rdy = True
            else:
                # this is an intermediate part of the json packet
                json_str += socket_data
        if json_rdy:
            image_sz += len(socket_data) - img_ix
            f.write(socket_data[img_ix:])
        socket_data = sc.recv(1024)
    f.close()
    sc.close()
    print image_sz, fn, json_str
    timer_ct += 1
    if timer_ct >= 10:
        timer_stop = time.clock()
        print("Received %d in %f seconds" % (timer_ct, timer_stop - timer_start))
        timer_ct = 0
        timer_start = timer_stop
s.close()
