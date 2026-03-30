"""Minimal single-line live reading display.

Updates in-place on a single terminal line with ANSI colors.
Activated via: fluke watch --device <id>
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from apps.cli.runtime import build_device_manager
from fluke_core.models.reading import Reading


# ANSI color codes
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_RESET = "\033[0m"

_STATUS_COLORS = {
    "ok": _GREEN,
    "hold": _YELLOW,
    "over_range": _RED,
    "under_range": _RED,
    "invalid": _RED,
    "no_signal": _RED,
}


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "watch",
        help="Minimal single-line live reading display with color",
    )
    parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    parser.add_argument("--duration", type=float, default=0.0, help="Stop after N seconds; 0 runs until interrupted")
    parser.set_defaults(func=handle)


async def handle(args: argparse.Namespace) -> int:
    manager = build_device_manager()
    samples = 0
    finished = asyncio.Event()

    def on_reading(reading: Reading) -> None:
        nonlocal samples
        samples += 1

        value_text = reading.display_text or ("OL" if reading.value is None else f"{reading.value:.4g}")
        unit = reading.unit or ""
        mtype = reading.measurement_type.value.replace("_", " ").upper()
        status_key = reading.status.value
        color = _STATUS_COLORS.get(status_key, _GREEN)
        status_label = status_key.upper().replace("_", " ")

        line = (
            f"\r{_BOLD}{color}  {value_text} {unit}{_RESET}"
            f"  {mtype}"
            f"  [{color}{status_label}{_RESET}]"
            f"  Samples: {samples}"
            f"    "
        )
        sys.stdout.write(line)
        sys.stdout.flush()

    manager.subscribe_readings(on_reading)

    print(f"Connecting to {args.device}...", file=sys.stderr)
    await manager.connect(args.device, profile_id=args.profile)
    print(f"\033[2KWatching {args.device}. Press Ctrl+C to stop.\n", file=sys.stderr)
    await manager.start_stream()

    try:
        if args.duration > 0:
            await asyncio.sleep(args.duration)
        else:
            await asyncio.Future()
    except asyncio.TimeoutError:
        pass
    finally:
        sys.stdout.write("\n")
        await manager.disconnect()

    return 0
