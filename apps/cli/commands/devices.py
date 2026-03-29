from __future__ import annotations

import argparse

from apps.cli.formatters import format_profile, output_list, profile_to_dict
from fluke_plugins import build_profile_registry


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("devices", help="Show built-in supported device profiles")
    device_subparsers = parser.add_subparsers(dest="devices_command", required=True)

    supported_parser = device_subparsers.add_parser("supported", help="List supported device profiles")
    supported_parser.set_defaults(func=handle_supported)


async def handle_supported(args: argparse.Namespace) -> int:
    profiles = build_profile_registry().all()

    if getattr(args, "json", False):
        output_list(profiles, True, format_profile, profile_to_dict)
    else:
        print("Supported device profiles:")
        output_list(profiles, False, format_profile, profile_to_dict)
    return 0
