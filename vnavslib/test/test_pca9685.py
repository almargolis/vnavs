from vnavslib import pca9685


class FakeSMBus:
    """Records register traffic instead of touching a real I2C bus."""

    instances = []

    def __init__(self, bus):
        self.bus = bus
        self.byte_writes = []  # (addr, reg, value)
        self.block_writes = []  # (addr, reg, [values])
        self.registers = {}
        FakeSMBus.instances.append(self)

    def write_byte_data(self, addr, reg, value):
        self.byte_writes.append((addr, reg, value))
        self.registers[reg] = value

    def read_byte_data(self, addr, reg):
        return self.registers.get(reg, 0)

    def write_i2c_block_data(self, addr, reg, values):
        self.block_writes.append((addr, reg, list(values)))

    def close(self):
        self.closed = True


def make_chip(monkeypatch, **kw):
    FakeSMBus.instances = []
    monkeypatch.setattr(pca9685, "SMBus", FakeSMBus)
    chip = pca9685.Pca9685(**kw)
    return chip, FakeSMBus.instances[0]


def test_init_sets_prescale_for_frequency(monkeypatch):
    chip, fake = make_chip(monkeypatch, freq_hz=60.0)
    # prescale = round(25e6 / (4096 * 60)) - 1 == 101
    prescale_writes = [v for (_, reg, v) in fake.byte_writes if reg == pca9685.PRESCALE]
    assert prescale_writes == [101]


def test_set_pwm_writes_four_ordered_bytes(monkeypatch):
    chip, fake = make_chip(monkeypatch)
    fake.block_writes.clear()
    chip.set_pwm(2, 0, 2048)
    addr, reg, values = fake.block_writes[-1]
    assert addr == pca9685.DEFAULT_ADDRESS
    assert reg == pca9685.LED0_ON_L + 4 * 2
    assert values == [0x00, 0x00, 2048 & 0xFF, 2048 >> 8]


def test_set_pulse_us_scales_to_counts(monkeypatch):
    chip, fake = make_chip(monkeypatch, freq_hz=50.0)
    fake.block_writes.clear()
    chip.set_pulse_us(0, 1500)  # 1.5 ms of a 20 ms period -> 7.5% -> ~307
    _, _, values = fake.block_writes[-1]
    off_count = values[2] | (values[3] << 8)
    assert 305 <= off_count <= 309


def test_all_off_uses_full_off_bit(monkeypatch):
    chip, fake = make_chip(monkeypatch)
    fake.block_writes.clear()
    chip.all_off()
    _, reg, values = fake.block_writes[-1]
    assert reg == pca9685.ALL_LED_ON_L
    assert values == [0x00, 0x00, 0x00, 0x10]


def test_radians_to_norm_clamps():
    assert pca9685.radians_to_norm(0.0, 0.6) == 0.0
    assert pca9685.radians_to_norm(0.3, 0.6) == 0.5
    assert pca9685.radians_to_norm(5.0, 0.6) == 1.0
    assert pca9685.radians_to_norm(-5.0, 0.6) == -1.0
    assert pca9685.radians_to_norm(1.0, 0.0) == 0.0


def test_angle_to_pulse_us():
    assert pca9685.angle_to_pulse_us(0.0, 1500, 400) == 1500
    assert pca9685.angle_to_pulse_us(1.0, 1500, 400) == 1900
    assert pca9685.angle_to_pulse_us(-1.0, 1500, 400) == 1100
    assert pca9685.angle_to_pulse_us(2.0, 1500, 400) == 1900  # clamped
