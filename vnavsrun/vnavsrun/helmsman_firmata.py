import sys

from vnavsrun import helmsman

Arduino = None
util = None

TICK_PATTERNS = [
    [],  # 0 tick bits
    [],  # 1 tick bits
    [  # 2 tick bits
        [True, True, True, True],
        [True, False, False, False],
        [True, False, True, False],
        [True, True, True, False],
    ],
]

RAMP_NONE = 0
RAMP_UP = 1
RAMP_DOWN = -1

SPEED_STOP = 0


class SteeringPlanStep:
    def __init__(self, direction):
        self.direction = direction


class Vehicle:
    def __init__(self):
        global Arduino
        global util
        from pyfirmata import Arduino, util

        self.board = Arduino("/dev/ttyUSB0")
        self.motor = self.board.get_pin("d:9:s")
        self.tickBits = 2
        self.tickMax = 1 << self.tickBits
        self.tickMask = (1 << self.tickBits) - 1
        self.mot_offset = 90
        self.mot_tick_clock = 0
        self.mot_pulse_dead_zone_f = 7
        self.mot_pulse_dead_zone_r = 4
        self.mot_jump_f = 3
        self.mot_jump_r = -1
        self.mot_ramp_increment = 0
        self.mot_this_pulse = 0
        self.mot_this_tick = 0
        self.mot_last_pulse = 0
        self.mot_last_tick = 0
        self.mot_speed_goal = SPEED_STOP
        self.mot_speed_ramp = SPEED_STOP
        self.servo_speed_max = 40
        #
        self.steering = self.board.get_pin("d:10:s")
        self.steering_offset = 90
        self.steering_increment = 10
        self.servo_steering_max = 90
        self.steering_last = 0
        self.steering_plan = None
        self.Estop()

    def ConvertSpeedToPulseParameter(self, speed):
        if speed == SPEED_STOP:
            return (0, 0)
        if speed < 0:
            speed = -speed
            xsign = -1
        else:
            xsign = 1
        tick = speed & self.tickMask
        pulse = (speed >> self.tickBits) * xsign
        if xsign > 0:
            pulse += self.mot_pulse_dead_zone_f
        else:
            pulse -= self.mot_pulse_dead_zone_r
        return (pulse, tick)

    def NewSpeedGoal(self, speed_goal):
        new_speed_goal = int(speed_goal)
        if self.mot_speed_goal == new_speed_goal:
            return
        self.mot_speed_goal = new_speed_goal
        if self.mot_speed_goal == SPEED_STOP:
            self.mot_speed_ramp = SPEED_STOP
            self.mot_ramp_increment = RAMP_NONE
            return
        if self.mot_speed_ramp == SPEED_STOP:
            if self.mot_speed_goal >= self.mot_jump_f:
                self.mot_speed_ramp = self.mot_speed_goal
                self.mot_ramp_increment = RAMP_NONE
                return
            elif self.mot_speed_goal <= self.mot_jump_r:
                self.mot_speed_ramp = self.mot_speed_goal
                self.mot_ramp_increment = RAMP_NONE
                return
            elif self.mot_speed_goal > SPEED_STOP:
                self.mot_speed_ramp = self.mot_jump_f
                self.mot_ramp_increment = RAMP_DOWN
                return
            else:
                self.mot_speed_ramp = self.mot_jump_r
                self.mot_ramp_increment = RAMP_UP
                return
        self.mot_speed_ramp = self.mot_speed_goal
        self.mot_ramp_increment = RAMP_NONE

    def RampSpeed(self):
        self.mot_speed_ramp += self.mot_ramp_increment
        if self.mot_speed_goal > SPEED_STOP:
            if self.mot_ramp_increment > RAMP_NONE:
                if self.mot_speed_ramp >= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp_increment = RAMP_NONE
            else:
                if self.mot_speed_ramp <= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp_increment = RAMP_NONE
        else:
            if self.mot_ramp_increment > RAMP_NONE:
                if self.mot_speed_ramp >= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp_increment = RAMP_NONE
            else:
                if self.mot_speed_ramp <= self.mot_speed_goal:
                    self.mot_speed_ramp = self.mot_speed_goal
                    self.mot_ramp_increment = RAMP_NONE

    def Estop(self):
        self.motor.write(self.mot_offset)
        self.mot_speed_goal = SPEED_STOP
        self.mot_speed_ramp = SPEED_STOP

    def MotorTick(self):
        if self.mot_speed_goal == SPEED_STOP:
            self.motor.write(self.mot_offset)
            return
        if self.mot_ramp_increment != RAMP_NONE:
            self.RampSpeed()
        self.mot_this_pulse, self.mot_this_tick = self.ConvertSpeedToPulseParameter(
            self.mot_speed_ramp
        )
        tick_pattern = TICK_PATTERNS[self.tickBits][self.mot_this_tick]
        tick_rule = tick_pattern[self.mot_tick_clock]
        if tick_rule:
            if self.mot_this_tick == 0:
                self.actualPulse = self.mot_offset + self.mot_this_pulse
            elif self.mot_tick_clock <= self.mot_this_tick:
                if self.mot_this_pulse > 0:
                    self.actualPulse = self.mot_offset + self.mot_this_pulse + 1
                else:
                    self.actualPulse = self.mot_offset + self.mot_this_pulse - 1
        else:
            self.actualPulse = self.mot_offset
        self.motor.write(self.actualPulse)
        self.mot_tick_clock += 1
        if self.mot_tick_clock > self.tickMask:
            self.mot_tick_clock = 0
        self.mot_last_pulse = self.mot_this_pulse
        self.mot_last_tick = self.mot_this_tick

    def NewSteeringGoal(self, steering_goal):
        step = SteeringPlanStep(steering_goal)
        self.steering_plan = [step]

    def SteeringTick(self):
        if self.steering_plan is None:
            direction = 0
        else:
            direction = self.steering_plan[0].direction
        try:
            self.steering.write(self.steering_offset + direction)
        except ValueError:
            pass
        self.steering_last = direction


# Conversion constants for Firmata servo-based vehicle.
# These map between cm/sec / rad/sec and internal servo units.
# Adjust per vehicle calibration.
FIRMATA_CM_PER_SEC_TO_SERVO = 1.0  # cm/sec -> servo speed units
FIRMATA_RAD_PER_SEC_TO_SERVO_DEG = 30.0  # rad/sec -> servo steering degrees
FIRMATA_ANGLE_TO_SERVO_DEG = 57.2958  # 180/pi, radians -> degrees


class HelmsmanFirmata(helmsman.Helmsman):
    def __init__(self, steering_type=helmsman.STEERING_TYPE_ACKERMAN):
        self.v = None
        self._steering_type = steering_type
        super().__init__()

    def vehicle_init(self):
        self.v = Vehicle()
        self.speed_max = 40.0  # cm/sec
        self.steering_max = 3.0  # rad/sec (~172 deg/sec)
        self.vehicle_steering_type = self._steering_type
        if self.vehicle_steering_type == helmsman.STEERING_TYPE_DIFFERENTIAL:
            self.wheelbase = 20.0  # cm, set per vehicle calibration

    def vehicle_estop(self):
        self.v.Estop()

    def vehicle_set_speed(self, cm_per_sec):
        servo_speed = int(cm_per_sec * FIRMATA_CM_PER_SEC_TO_SERVO)
        self.v.NewSpeedGoal(servo_speed)

    def vehicle_set_steering(self, rad_per_sec):
        servo_deg = int(rad_per_sec * FIRMATA_RAD_PER_SEC_TO_SERVO_DEG)
        self.v.NewSteeringGoal(servo_deg)

    def vehicle_set_steering_angle(self, angle, angle_rate):
        servo_deg = int(angle * FIRMATA_ANGLE_TO_SERVO_DEG)
        self.v.NewSteeringGoal(servo_deg)

    def vehicle_tick(self):
        self.v.MotorTick()
        self.v.SteeringTick()

    def vehicle_cleanup(self):
        self.v.Estop()


if __name__ == "__main__":
    if sys.argv[1] == "node":
        steering_type = helmsman.STEERING_TYPE_ACKERMAN
        if len(sys.argv) > 2:
            steering_type = sys.argv[2]
        m = HelmsmanFirmata(steering_type=steering_type)
        m.main_loop()
