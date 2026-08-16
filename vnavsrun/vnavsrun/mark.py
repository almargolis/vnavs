"""Calibration CLI tool for lane marking.

Publishes a mark payload to cameraman/mark topic, triggering the cameraman
to sample or apply an HSV color spec at a given rectangle in the image.

Usage:
    python -m vnavsrun.mark --rect y,x,w,h
    python -m vnavsrun.mark --rect y,x,w,h --hsv hue,huerange,sat,satrange,val,valrange
    python -m vnavsrun.mark --rect y,x,w,h --save lane_color
"""

import argparse
import sys
import time

from ezcomms import vnavs_node as vmqtt
from ezcomms import vnavs_const as vconst


def build_payload(args):
    parts = [int(v) for v in args.rect.split(",")]
    if len(parts) != 4:
        print("--rect requires exactly 4 values: y,x,w,h")
        sys.exit(1)
    payload = {"y": parts[0], "x": parts[1], "w": parts[2], "h": parts[3]}

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
        "--rect", required=True,
        help="Rectangle as y,x,w,h (pixels from top-left)",
    )
    parser.add_argument(
        "--hsv", default=None,
        help="HSV spec as hue,huerange,saturation,saturationrange,value,valuerange",
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
