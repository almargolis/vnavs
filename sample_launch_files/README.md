# sample_launch_files

A worked example of the recommended way to run a VNAVS robot: a **launch
directory** that holds the robot's `vnavs.ini` next to one small shell script
per node. Every node reads `vnavs.ini` from its current working directory
(`vnavs_const.resolve_config_path()`), so each script `cd`s into this
directory before starting its node.

Copy this directory somewhere outside the repo (e.g. `~/launch/`), then:

```bash
cp vnavs.ini.sample vnavs.ini      # then edit for your robot
python -c "from ezcomms import vnavs_const; vnavs_const.UpdateIni()"  # fill gaps
./launch_all                        # start broker + fileserver + the 3 nodes
screen -ls                          # see the sessions
screen -r navigator                 # attach to one (Ctrl-A D to detach)
./stop_all                          # stop them
```

## Files

| Script | Node | Session | Mode |
|--------|------|---------|------|
| `launch_fastmqtt` | `vnavsrun.fastmqttserver m` | `fastmqtt` | detached |
| `launch_fileserver` | `vnavsrun.fileserver f` | `fileserver` | detached |
| `launch_cameraman` | `vnavsrun.cameraman node` | `cameraman` | detached |
| `launch_navigator` | `vnavsrun.navigator node` | `navigator` | detached |
| `launch_helmsman` | `vnavsrun.helmsman_donkeycar node` | `helmsman` | detached |
| `launch_cvpipeline` | `cvpipeline.cvpipeline` | `cvpipeline` | **foreground** |
| `launch_mission_control` | `vnavsrun.mission_control gui` | `mission_control` | **foreground** |
| `launch_all` / `stop_all` | the five detached nodes (not the GUIs) | | |

`_launch_common.sh` is the shared logic sourced by each script (cd here,
activate the venv, start the node). Each script also accepts `-f`
(foreground) / `-d` (detached) to override its default.

## Adapt to your robot

- **Virtualenv**: scripts activate `$VNAVS_VENV`, default
  `/home/al/projects/robot/.venv`. Set `VNAVS_VENV` or edit
  `_launch_common.sh`.
- **helmsman**: `launch_helmsman` runs the DonkeyCar/PCA9685 driver. Swap
  `NODE_CMD` for `vnavsrun.helmsman_firmata` (Ackerman) or another helmsman.
- **tmux instead of screen**: replace the `screen -h 20000 -dmS` line in
  `_launch_common.sh` with `tmux new -d -s`.
- Detached nodes run inside a shell that stays open after the node exits, so
  `screen -r <name>` still shows a crash traceback (up-arrow re-runs the node).
