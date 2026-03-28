from __future__ import annotations

import argparse

from apps.cli.runtime import build_device_manager


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("scan", help="Scan nearby BLE devices")
    parser.add_argument("--timeout", type=float, default=10.0, help="Scan duration in seconds")
    parser.add_argument("--name", type=str, default="", help="Optional name filter")
    parser.set_defaults(func=handle)


async def handle(args: argparse.Namespace) -> int:
    manager = build_device_manager()
    devices = await manager.scan(timeout_s=args.timeout)
    if args.name:
        devices = [device for device in devices if args.name.lower() in (device.nickname or "").lower()]

    if not devices:
        print("No matching BLE devices found.")
        return 0

    print("Found devices:")
    for device in sorted(devices, key=lambda item: item.rssi if item.rssi is not None else -999, reverse=True):
        print(f"- name={device.nickname or '(no name)'}")
        print(f"  id={device.device_id}")
        print(f"  rssi={device.rssi if device.rssi is not None else '-'}")
        print(f"  model={device.model_name}")
        print(f"  support={device.support_level}")
        if device.profile_id:
            print(f"  profile={device.profile_id}")
    return 0
