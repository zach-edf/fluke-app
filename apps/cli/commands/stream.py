from __future__ import annotations

import argparse
import asyncio

from apps.cli.runtime import build_device_manager
from fluke_core.models.reading import Reading


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("stream", help="Connect and print normalized live readings")
    parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    parser.add_argument("--duration", type=float, default=0.0, help="Stop after N seconds; 0 runs until interrupted")
    parser.add_argument("--count", type=int, default=0, help="Stop after N readings")
    parser.set_defaults(func=handle)


async def handle(args: argparse.Namespace) -> int:
    manager = build_device_manager()

    received = 0
    finished = asyncio.Event()

    def on_reading(reading: Reading) -> None:
        nonlocal received
        received += 1
        print(_format_reading(reading))
        if args.count and received >= args.count:
            finished.set()

    manager.subscribe_readings(on_reading)

    await manager.connect(args.device, profile_id=args.profile)
    await manager.start_stream()
    print(f"Streaming from {args.device}. Press Ctrl+C to stop.")

    try:
        if args.duration > 0 and args.count > 0:
            await asyncio.wait_for(finished.wait(), timeout=args.duration)
        elif args.duration > 0:
            await asyncio.sleep(args.duration)
        elif args.count > 0:
            await finished.wait()
        else:
            await asyncio.Future()
    except asyncio.TimeoutError:
        pass
    finally:
        await manager.disconnect()

    return 0


def _format_reading(reading: Reading) -> str:
    value = "-" if reading.value is None else f"{reading.value:.6g}"
    mode = reading.mode or "-"
    return (
        f"{reading.timestamp_utc.isoformat()} | "
        f"{reading.display_text or '-'} | "
        f"value={value} {reading.unit or ''}".rstrip()
        + f" | type={reading.measurement_type.value} | mode={mode} | status={reading.status.value}"
    )
