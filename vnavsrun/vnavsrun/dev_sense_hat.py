import random
random.seed()
import time

from sense_hat import SenseHat
hat = SenseHat()

class accelerometer(object):
    def __init__(self):
        hat.set_imu_config(False, True, False)

    def get_orientation_degrees(self):
        return hat.get_orientation_degrees()
        # orientation['yaw']
        # orientation['pitch']
        # orientation['roll']

class display(object):
    def __init__(self):
        hat.clear()

    def fill_random_colors(self, sleep_secs=None):
        hat.clear()
        for y in range(8):
            for x in range(8):
                r = random.randint(0,255)
                g = random.randint(0,255)
                b = random.randint(0,255)
                hat.set_pixel(x, y, r, g, b)
                if sleep_secs is not None:
                    time.sleep(sleep_secs)

if __name__ == "__main__":
    d = display()
    d.fill_random_colors(sleep_secs=0.25)
    hat.clear()
