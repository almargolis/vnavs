import serial
import sys

ser = serial.Serial("/dev/ttyUSB0", 115200, rtscts=True, dsrdtr=True, timeout=0.1)


def Send(cmd):
    scmd = cmd + "\n"
    ser.write(scmd)
    res = ser.readline()[:-2]
    print(res)
    if res == cmd:
        return True
    else:
        return False


def GetRest():
    data = []
    while True:
        res = ser.readline()[:-2]
        if (res.find("\x1a") >= 0) or (res == ""):
            break
        print(res)
        data.append(res)
    return data


def CheckBump():
    Send("GetDigitalSensors")
    res = GetRest()
    for this_line in res:
        parts = this_line.split(",")
        if parts[0] == "RFRONTBIT":
            if parts[1] == "1":
                return True
    return False


def CheckIfStopped():
    Send("GetMotors LeftWheel")
    res = GetRest()
    for this_line in res:
        parts = this_line.split(",")
        if parts[0] == "LeftWheel_Speed":
            if parts[1] == "0":
                return True
    return False


if Send("GetVersion"):
    GetRest()
else:
    print("Unable To Talk To Botvac")
    sys.exit(-1)

move_fwd_command = "SetMotor LWheelDist 99 RWheelDist 99 Speed 100"
move_bkw_command = "SetMotor LWheelDist -99 RWheelDist -99 Speed 100"

Send("TestMode On")

Send(move_fwd_command)
while True:
    if CheckBump():
        break
    if CheckIfStopped():
        Send(move_fwd_command)

back_steps = 0
while back_steps < 6:
    if CheckIfStopped():
        Send(move_bkw_command)
        back_steps += 1

Send("TestMode Off")

ser.close()
