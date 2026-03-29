from __future__ import annotations

import argparse
import sys

from apps.cli.formatters import device_to_dict, format_device, output_list, positive_float
from apps.cli.runtime import build_device_manager


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("scan", help="Scan nearby BLE devices")
    parser.add_argument("--timeout", type=positive_float, default=10.0, help="Scan duration in seconds")
    parser.add_argument("--name", type=str, default="", help="Optional name filter")
    parser.set_defaults(func=handle)


async def handle(args: argparse.Namespace) -> int:
    manager = build_device_manager()

    print("Scanning for BLE devices...", file=sys.stderr)
    devices = await manager.scan(timeout_s=args.timeout)
    print("Scan complete.", file=sys.stderr)

    if args.name:
        devices = [device for device in devices if args.name.lower() in (device.nickname or "").lower()]

    if not devices:
        if not getattr(args, "json", False):
            print("No matching BLE devices found.")
        else:
            print("[]")
        return 0

    devices = sorted(devices, key=lambda item: item.rssi if item.rssi is not None else -999, reverse=True)

    if getattr(args, "json", False):
        output_list(devices, True, format_device, device_to_dict)
    else:
        print("Found devices:")
        output_list(devices, False, format_device, device_to_dict)
    return 0
