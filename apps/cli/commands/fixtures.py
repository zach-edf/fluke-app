from __future__ import annotations

import argparse

from apps.cli.runtime import require_bleak_adapter
from fluke_plugins import build_profile_registry
from fluke_testing import capture_fixture


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("fixtures", help="Capture raw BLE notification fixtures for contributor workflows")
    fixture_subparsers = parser.add_subparsers(dest="fixtures_command", required=True)

    capture_parser = fixture_subparsers.add_parser("capture", help="Capture a raw BLE fixture JSON")
    capture_parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    capture_parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to capture")
    capture_parser.add_argument("--duration", type=float, default=10.0, help="Capture duration in seconds")
    capture_parser.add_argument("--count", type=int, default=0, help="Stop after N frames; 0 means duration only")
    capture_parser.add_argument("--output", required=True, help="Output JSON file")
    capture_parser.set_defaults(func=handle_capture)


async def handle_capture(args: argparse.Namespace) -> int:
    adapter = require_bleak_adapter()()
    profiles = build_profile_registry()
    fixture = await capture_fixture(
        adapter,
        profiles,
        device_id=args.device,
        profile_id=args.profile,
        duration_s=args.duration,
        max_frames=args.count,
    )
    output = fixture.export_json(args.output)
    print(f"{output} ({len(fixture.frames)} frame(s))")
    return 0
