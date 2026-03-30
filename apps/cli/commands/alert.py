"""Stream readings with threshold-based alerts.

Prints each reading and triggers a visual + audible alert (bell)
when the value crosses the configured high or low threshold.

Activated via: fluke alert --device <id> --high 120 --low 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from apps.cli.formatters import format_reading, nonneg_float
from apps.cli.runtime import build_device_manager
from fluke_core.models.reading import Reading


# ANSI color codes
_GREEN = "\033[32m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "alert",
        help="Stream readings and alert when value crosses thresholds",
    )
    parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    parser.add_argument("--high", type=float, default=None, help="Alert when reading exceeds this value")
    parser.add_argument("--low", type=float, default=None, help="Alert when reading drops below this value")
    parser.add_argument("--duration", type=nonneg_float, default=0.0, help="Stop after N seconds; 0 runs until interrupted")
    parser.add_argument("--bell", action="store_true", default=True, help="Sound terminal bell on alert (default: on)")
    parser.add_argument("--no-bell", action="store_false", dest="bell", help="Disable terminal bell")
    parser.set_defaults(func=handle)


async def handle(args: argparse.Namespace) -> int:
    if args.high is None and args.low is None:
        print("Warning: no thresholds set. Use --high and/or --low to enable alerts.", file=sys.stderr)

    manager = build_device_manager()
    alert_count = 0

    def on_reading(reading: Reading) -> None:
        nonlocal alert_count
        is_alert = False
        alert_reason = ""

        if reading.value is not None:
            if args.high is not None and reading.value > args.high:
                is_alert = True
                alert_reason = f"HIGH ({reading.value:.4g} > {args.high:.4g})"
            elif args.low is not None and reading.value < args.low:
                is_alert = True
                alert_reason = f"LOW ({reading.value:.4g} < {args.low:.4g})"

        line = format_reading(reading)

        if is_alert:
            alert_count += 1
            prefix = f"{_BOLD}{_RED}ALERT {alert_reason}{_RESET} "
            bell = "\a" if args.bell else ""
            print(f"{bell}{prefix}{line}")
        else:
            print(f"{_GREEN}\u2713{_RESET} {line}")

    manager.subscribe_readings(on_reading)

    thresholds = []
    if args.low is not None:
        thresholds.append(f"low={args.low}")
    if args.high is not None:
        thresholds.append(f"high={args.high}")
    threshold_text = ", ".join(thresholds) if thresholds else "none"

    print(f"Connecting to {args.device}...", file=sys.stderr)
    await manager.connect(args.device, profile_id=args.profile)
    print(f"Streaming with alerts ({threshold_text}). Press Ctrl+C to stop.", file=sys.stderr)
    await manager.start_stream()

    try:
        if args.duration > 0:
            await asyncio.sleep(args.duration)
        else:
            await asyncio.Future()
    except asyncio.TimeoutError:
        pass
    finally:
        await manager.disconnect()
        if alert_count:
            print(f"\n{_RED}{alert_count} alert(s) triggered.{_RESET}", file=sys.stderr)

    return 0
