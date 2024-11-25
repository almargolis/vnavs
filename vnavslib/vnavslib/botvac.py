import serial
import sys


class Botvac:
    __slots__ = ("ser_connection",)

    def __init__(self):
        self.ser_connection = serial.Serial(
            "/dev/ttyUSB0", 115200, rtscts=True, dsrdtr=True, timeout=0.1
        )

    def disconnect():
        self.ser_connection.close()

    def send(self, cmd):
        scmd = cmd + "\n"
        self.ser_connection.write(scmd)
        res = ser.readline()[:-2]
        print(res)
        if res == cmd:
            return True
        else:
            return False

    def get_rest(self):
        data = []
        while True:
            res = self.ser_connection.readline()[:-2]
            if (res.find("\x1a") >= 0) or (res == ""):
                break
            print(res)
            data.append(res)
        return data

    def check_bump(self):
        self.send("GetDigitalSensors")
        res = self.get_rest()
        for this_line in res:
            parts = this_line.split(",")
            if parts[0] == "RFRONTBIT":
                if parts[1] == "1":
                    return True
        return False

    def check_if_stopped(self):
        sself.send("GetMotors LeftWheel")
        res = self.get_rest()
        for this_line in res:
            parts = this_line.split(",")
            if parts[0] == "LeftWheel_Speed":
                if parts[1] == "0":
                    return True
        return False


def test():
    bot = Botvac()
    if bot.send("GetVersion"):
        bot.get_rest()
    else:
        print("Unable To Talk To Botvac")
        sys.exit(-1)

    move_fwd_command = "SetMotor LWheelDist 99 RWheelDist 99 Speed 100"
    move_bkw_command = "SetMotor LWheelDist -99 RWheelDist -99 Speed 100"

    bot.send("TestMode On")

    bot.send(move_fwd_command)
    while True:
        if bot.check_bump():
            break
        if bot.check_if_stopped():
            bot.send(move_fwd_command)

    back_steps = 0
    while back_steps < 6:
        if bot.check_if_stopped():
            bot.send(move_bkw_command)
            back_steps += 1

    bot.send("TestMode Off")
    bot.disconnect()
