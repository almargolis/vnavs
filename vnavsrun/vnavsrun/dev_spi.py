# spitest.py
# A brief demonstration of the Raspberry Pi SPI interface, using the Sparkfun
# Pi Wedge breakout board and a SparkFun Serial 7 Segment display:
# https://www.sparkfun.com/products/11629

import time
import spidev

# We only have SPI bus 0 available to us on the Pi
bus = 0

# Device is the chip select pin. Set to 0 or 1, depending on the connections
device = 0

# Enable SPI
spi = spidev.SpiDev()

# Open a connection to a specific bus and device (chip select pin)
spi.open(bus, device)

# Set SPI speed and mode
# spi.max_speed_hz = 500000
spi.max_speed_hz = 1000
spi.mode = 0

# Start Communication
msg = [0x01]
spi.xfer2(msg)

# time.sleep(5)

# Turn on one segment of each character to show that we can
# address all of the segments
while True:
    msg = [ord("a"), ord("b"), ord("c")]
    result = spi.xfer2(msg)
    print("SPI", result)
    time.sleep(1)
