import socket
import sys

my_ip = "192.168.8.11"
my_socket = 3050
s = socket.socket()
s.bind((my_ip, my_socket))
s.listen(10)

image_ct = 0

while True:
    sc, address = s.accept()

    print image_ct,  address
    fn = 'temp/Q%d.jpg' % image_ct
    f = open(fn,'wb') #open in binary
    image_ct += 1
    image_sz = 0
    l = 1
    while(l):
        l = sc.recv(1024)
        while (l):
            image_sz += len(l)
            f.write(l)
            l = sc.recv(1024)
        f.close()
        print image_sz, fn
    sc.close()

s.close()
