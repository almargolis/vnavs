# Calibrating the DonkeyCar helmsman (PCA9685)

`HelmsmanDonkeycar` (`vnavsrun/helmsman_donkeycar.py`) drives a steering servo
and an ESC through a PCA9685 PWM board. All numbers live in the `[Helmsman]`
section of `vnavs.ini`; nothing here needs a code change.

**Do all of this with the wheels off the ground.** Channel 0 is normally the
ESC — it *will* spin the drive motor.

## Tool: `python -m vnavslib.pca9685`

Run it from inside a repo dir with the venv active.

- `--hold US` — drive the channel(s) to one fixed pulse width and hold it, so
  you can watch the servo/ESC and read off an endpoint. It prints the 12-bit
  **count** actually written — that count is what goes in `vnavs.ini`.
  Ctrl-C stops and de-energises the channel.
- no `--hold` — sweep the channel(s) through a range (a quick "is it alive"
  check). Any keypress aborts.
- `--channels 1` steering only, `--channels 0` throttle only (default `1,0`).
- `--freq` must match `[Helmsman] pwmfrequencyhz` (default 60).

`count = round(4096 * microseconds * freq / 1_000_000)` — e.g. 1500 µs at
60 Hz ≈ 369.

## Steering (channel 1, servo)

```bash
python -m vnavslib.pca9685 --channels 1 --hold 1500     # roughly centred
```

Nudge `--hold` up/down ~25 µs at a time and re-run until you find:

| value | `vnavs.ini` key | what to look for |
|-------|-----------------|------------------|
| wheels dead ahead | `steeringcenterpwm` | straight, no buzz |
| full left, not straining | `steeringleftpwm` | servo not buzzing/stalled at the stop |
| full right, not straining | `steeringrightpwm` | same |

Left is usually a *higher* count than right (that's the default: 460 / 375 /
290) but it depends on servo orientation — whichever way the wheels actually
go is what matters. Put the printed counts in `vnavs.ini`, restart the
helmsman, and check in the Drive tab that **Steer +** turns right.

## Throttle (channel 0, ESC)

1. **Neutral / arm point.** With the ESC powered, sweep a narrow band and
   listen for the arm tones:
   ```bash
   python -m vnavslib.pca9685 --channels 0 --hold 1500
   ```
   Adjust until the ESC arms and the motor is silent/stopped. That count →
   `throttlestoppedpwm`.

2. **Full forward / reverse.** `--hold 1900` (forward) and `--hold 1100`
   (reverse) are typical extremes; back off to where the ESC still responds
   cleanly. Counts → `throttleforwardpwm` / `throttlereversepwm`.
   (Many car ESCs need reverse enabled in the ESC's own setup, or a
   brake-then-reverse tap.)

3. **Deadband.** Starting from `throttlestoppedpwm`, raise `--hold` in small
   steps until the wheels *just* begin to turn. Then set:
   ```
   throttledeadbandpwm = <that count> - <throttlestoppedpwm>
   ```
   The helmsman adds this offset to every non-zero throttle command, so a
   small command still produces motion instead of sitting in the deadband
   (the "ESC beeps but nothing moves" symptom). `0` disables it.

## `[Helmsman]` reference

```ini
[Helmsman]
type              = donkeycar
i2cbus            = 1
i2caddress        = 0x40
pwmfrequencyhz    = 60
steeringchannel   = 1
throttlechannel   = 0
steeringleftpwm   = 460      # <- calibrate
steeringcenterpwm = 375      # <- calibrate
steeringrightpwm  = 290      # <- calibrate
throttleforwardpwm  = 500    # <- calibrate
throttlestoppedpwm  = 370    # <- calibrate
throttlereversepwm  = 220    # <- calibrate
throttledeadbandpwm = 0      # <- calibrate (0 = off)
steeringgain      = 0.012    # navigator PID pixels*Kp -> normalized steering
maxsteeringradians = 0.6     # scales Ackerman `angle` commands
maxspeedcmpersec  = 200      # scales navigator `cm_per_sec` commands
```

`steeringgain` / `maxspeedcmpersec` only affect **autonomous** commands from
the navigator, not the Drive tab (which sends normalized `throttle` /
`steering`, -1..1, straight onto the calibrated range above). Tune
`steeringgain` together with the mission's PID `Kp`.

## First powered test

1. Calibrate everything above, wheels up.
2. Start the stack, open mission control, Drive tab. Confirm the log shows
   `HELMSMAN - broker connected` and orders arriving when you click.
3. Throttle 0.3, Steer 0.7. Click **Forward** — expect motion. Click **Left**
   / **Right** — expect the wheels to turn the matching way.
4. `./stop_all` (or Ctrl-C) — the helmsman neutralises and de-energises the
   PWM chip on exit. If it ever doesn't, pull the battery.
