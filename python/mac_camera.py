import cameraman
import cv2

c = cameraman.macbook_camera()
i = c.capture_opencv()
cv2.imwrite('test.jpeg', i)
