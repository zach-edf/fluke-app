from __future__ import annotations

import argparse

from fluke_protocol.profiles.fluke_376fc import Fluke376FCProfile


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("devices", help="Show built-in supported device profiles")
    device_subparsers = parser.add_subparsers(dest="devices_command", required=True)

    supported_parser = device_subparsers.add_parser("supported", help="List supported device profiles")
    supported_parser.set_defaults(func=handle_supported)


async def handle_supported(args: argparse.Namespace) -> int:
    del args
    profiles = [Fluke376FCProfile()]
    print("Supported device profiles:")
    for profile in profiles:
        capabilities = ", ".join(profile.capabilities())
        print(f"- {profile.model_name} ({profile.profile_id})")
        print(f"  capabilities={capabilities}")
    return 0
