"""Shared, UI-free mission/drive helpers.

Both mission_control (Tk, usually on a laptop) and headless_control (Pi-side
joystick node in a screen session) need to do the same handful of things --
send a normalized manual drive order, start/stop a recording (broker archive
+ cameraman image capture), build a status payload -- and they must stay
consistent. Put that logic here; the callers only supply a node with a
``.publish(topic, dict)`` method.

Nothing in this module imports tkinter or pygame.
"""

import time

from ezcomms import vnavs_const as vconst
from ezcomms import vnavs_node as vmqtt
from vnavsrun import helmsman

# Deadman window (seconds) attached to every manual drive order. Short: a
# manually driven vehicle should stop almost immediately when the orders stop
# arriving (node killed, joystick unplugged, laptop closed). The helmsman also
# has its own ManualDriveMaxHoldSeconds backstop against a stuck sender.
MANUAL_DRIVE_TIMER = 1

STATUS_TOPIC = vconst.headless_control_status_topic


def clamp(value, low, high):
    return max(low, min(high, value))


def apply_deadzone(value, frac):
    """Zero out |value| < frac, then rescale the rest to the full 0..1 range so
    control doesn't jump when leaving the deadzone."""
    if frac <= 0.0:
        return clamp(value, -1.0, 1.0)
    if abs(value) < frac:
        return 0.0
    sign = 1.0 if value > 0 else -1.0
    return sign * clamp((abs(value) - frac) / (1.0 - frac), 0.0, 1.0)


def publish_manual_drive(node, throttle, steer, timer=MANUAL_DRIVE_TIMER):
    """Publish a direct normalized (-1..1) manual drive order. Bypasses cm/s
    and the PID steering gain -- the helmsman maps these straight onto the
    calibrated ESC / servo range. Returns the payload sent."""
    payload = {
        helmsman.HELMSMAN_THROTTLE: clamp(throttle, -1.0, 1.0),
        helmsman.HELMSMAN_STEERING: clamp(steer, -1.0, 1.0),
        helmsman.HELMSMAN_TIMER: timer,
    }
    node.publish(vconst.helmsman_orders_topic, payload)
    return payload


def publish_stop(node):
    """Explicit zero-throttle / zero-steer order (also clears the helmsman's
    manual-hold backstop)."""
    return publish_manual_drive(node, 0.0, 0.0)


def publish_estop(node):
    """Immediate E-stop: the helmsman neutralises the ESC and clears its
    orders queue until a moving-state order is received."""
    node.publish(
        vconst.helmsman_orders_topic, {helmsman.HELMSMAN_STATE: helmsman.STATE_ESTOPPED}
    )


def new_mission_id(mission_name):
    return "{}_{}".format(mission_name, vmqtt.NowStr())


def start_recording(node, mission_name="headless"):
    """Begin a recording: the broker archives every message and the cameraman
    saves every frame, both keyed by a fresh mission_id. Returns the id.

    Mirrors what the navigator does at stage `init` + a StartLog step, so the
    download / replay tooling in mission_control sees these exactly like a
    normal mission.
    """
    mission_id = new_mission_id(mission_name)
    node.publish(
        vconst.mission_init_topic,
        {"mission_id": mission_id, "mission_name": mission_name},
    )
    node.publish(vconst.mission_log_start_topic, {"mission_id": mission_id})
    return mission_id


def stop_recording(node):
    node.publish(vconst.mission_log_stop_topic, {})


def build_status_payload(
    *,
    armed,
    recording,
    mission_id,
    throttle,
    steering,
    joystick_name="",
    note="",
):
    """One flat dict for headless_control -> mission_control status display."""
    return {
        "armed": bool(armed),
        "recording": bool(recording),
        "mission_id": mission_id or "",
        "throttle": round(float(throttle), 3),
        "steering": round(float(steering), 3),
        "joystick": joystick_name,
        "note": note,
        "t": time.time(),
    }


def format_status(payload):
    """Short one-line rendering of a status payload, for a label or a log."""
    armed = "ARMED" if payload.get("armed") else "safe"
    rec = "REC" if payload.get("recording") else "---"
    mid = payload.get("mission_id") or "-"
    return "{} {} thr={:+.2f} str={:+.2f} {}{}".format(
        armed,
        rec,
        payload.get("throttle", 0.0),
        payload.get("steering", 0.0),
        mid,
        (" " + payload["note"]) if payload.get("note") else "",
    )
