import sys

from create_serial import create
from vnavsrun import helmsman


class HelmsmanCreate(helmsman.Helmsman):
    def __init__(self):
        self.robot = None
        self.current_rad_per_sec = 0.0
        super().__init__()

    def vehicle_init(self):
        self.robot = create.Create()
        self.speed_max = 50.0  # cm/sec
        self.steering_max = 4.36  # rad/sec (~250 deg/sec)
        self.vehicle_steering_type = helmsman.STEERING_TYPE_DIFFERENTIAL
        self.wheelbase = 26.0  # cm

    def vehicle_estop(self):
        self.robot.stop()
        self.current_cm_per_sec = 0.0
        self.current_rad_per_sec = 0.0

    def vehicle_set_speed(self, cm_per_sec):
        self.current_cm_per_sec = cm_per_sec

    def vehicle_set_steering(self, rad_per_sec):
        self.current_rad_per_sec = rad_per_sec

    def vehicle_tick(self):
        self.robot.go_differential(self.current_cm_per_sec, self.current_rad_per_sec)

    def vehicle_cleanup(self):
        self.robot.stop()
        self.robot.close()


if __name__ == "__main__":
    if sys.argv[1] == "node":
        m = HelmsmanCreate()
        m.main_loop()
