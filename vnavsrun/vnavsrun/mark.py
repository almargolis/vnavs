"""Calibration CLI tool for lane marking.

Publishes a mark payload to cameraman/mark topic, triggering the cameraman
to sample or apply an HSV color spec at a given rectangle in the image.

Usage:
    python -m vnavsrun.mark --rect y,x,w,h
    python -m vnavsrun.mark --rect y,x,w,h --hsv hue,huerange,sat,satrange,val,valrange
    python -m vnavsrun.mark --rect y,x,w,h --save lane_color

    # Noisy mask? --open drops isolated speckle (erode+dilate) before
    # detection; --minrange broadens the auto-sampled color match:
    python -m vnavsrun.mark --rect y,x,w,h --open 3 --minrange 40

    # Two-line lane centering (follow_lane_center step): calibrate each edge
    # under its own label; the cameraman chases both every frame.
    python -m vnavsrun.mark --label left  --rect 150,10,90,50 --hsv 0,179,15,18,235,25
    python -m vnavsrun.mark --label right --rect 150,220,90,50 --hsv 0,179,15,18,235,25
    python -m vnavsrun.mark --label left --clear     # drop one
    python -m vnavsrun.mark --clear                  # drop all lane lines
"""

import argparse
import sys
import time

from ezcomms import vnavs_node as vmqtt
from ezcomms import vnavs_const as vconst


def build_payload(args):
    if args.clear:
        # A clear needs no rectangle. --label names one line; without it,
        # every lane line is dropped.
        if args.label is not None:
            return {"action": "clear", "label": args.label}
        return {"action": "clear_all"}

    if args.rect is None:
        print("--rect is required unless --clear is given")
        sys.exit(1)
    parts = [int(v) for v in args.rect.split(",")]
    if len(parts) != 4:
        print("--rect requires exactly 4 values: y,x,w,h")
        sys.exit(1)
    payload = {"y": parts[0], "x": parts[1], "w": parts[2], "h": parts[3]}

    if args.label is not None:
        payload["label"] = args.label

    if args.open_dim is not None:
        payload["open"] = args.open_dim

    if args.minrange is not None:
        payload["minrange"] = args.minrange

    if args.hsv is not None:
        hsv_parts = [int(v) for v in args.hsv.split(",")]
        if len(hsv_parts) != 6:
            print("--hsv requires exactly 6 values: hue,huerange,saturation,saturationrange,value,valuerange")
            sys.exit(1)
        payload["hue"] = hsv_parts[0]
        payload["huerange"] = hsv_parts[1]
        payload["saturation"] = hsv_parts[2]
        payload["saturationrange"] = hsv_parts[3]
        payload["value"] = hsv_parts[4]
        payload["valuerange"] = hsv_parts[5]

    if args.save is not None:
        payload["save"] = args.save

    return payload


def main():
    parser = argparse.ArgumentParser(description="Publish a cameraman mark payload.")
    parser.add_argument(
        "--rect", default=None,
        help="Rectangle as y,x,w,h (pixels from top-left). Required unless --clear.",
    )
    parser.add_argument(
        "--label", default=None,
        help="Track as a named lane-edge line (e.g. left, right) for the "
        "follow_lane_center step, instead of the single center line.",
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="Remove the --label lane line (or all lane lines if no --label).",
    )
    parser.add_argument(
        "--hsv", default=None,
        help="HSV spec as hue,huerange,saturation,saturationrange,value,valuerange",
    )
    parser.add_argument(
        "--open", dest="open_dim", type=int, default=None,
        help="Morphological-opening kernel (px) to drop isolated speckle "
        "before line detection. 0 = off. Try 2-3; keep below the line width.",
    )
    parser.add_argument(
        "--minrange", type=int, default=None,
        help="Floor on the auto-sampled HSV channel range (default 20). "
        "Raise for a broader, more forgiving color match.",
    )
    parser.add_argument(
        "--save", default=None,
        help="Persist the HSV spec under this data name",
    )
    args = parser.parse_args()

    payload = build_payload(args)

    node = vmqtt.VnavsNode(
        node_name="mark",
        subscriptions=[],
        broker_type="F",
        wait_if_not_connected=False,
        verbose=False,
    )
    connected = node.connect_to_mqtt_server()
    if not connected:
        print("Could not connect to FastMqttServer")
        sys.exit(1)

    node.publish(vconst.cameraman_mark_topic, payload)
    print("Published to", vconst.cameraman_mark_topic, payload)
    time.sleep(0.1)


if __name__ == "__main__":
    main()
