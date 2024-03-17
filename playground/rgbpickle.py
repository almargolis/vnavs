import cv2
import os
import pickle

fn = "R20170324212042_0_1310.bgr"
fn = "R20170324214145_0_0001.bgr"
fn = "R20170324215710_0_0001.bgr"
fnp = os.path.join("temp", fn)
ifile = open(fnp, "rb")
buffer = ifile.read()
print("FILE", len(buffer))
# bgr = pickle.loads(buffer)
bgr = cPickle.load(ifile)
opencv = bgr[..., ::-1]
# print("IMAGE", fn, len(buffer), opencv.shape)
cv2.imwrite("bgr.jpeg", opencv)
print("IMWRITE")
