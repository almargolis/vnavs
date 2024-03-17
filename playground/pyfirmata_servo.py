from __future__ import absolute_import, division, print_function
from builtins import bytes, str, open, super, range, zip, round, input, int, pow, object

import time
from pyfirmata import Arduino, util

board = Arduino("/dev/ttyUSB0")
servo = board.get_pin("d:10:s")

ct = 0
start_time = time.time()
for z in range(90, 150, 10):
    ct += 1
    servo.write(z)
end_time = time.time()
print("TIME", ct, end_time - start_time)
