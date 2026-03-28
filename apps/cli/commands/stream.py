from __future__ import annotations

import argparse
import asyncio

from fluke_app import DeviceManager, EventBus, ReadingStreamService
from fluke_core.models.reading import Reading
from fluke_protocol import ProfileRegistry
from fluke_protocol.profiles.fluke_376fc import Fluke376FCProfile


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("stream", help="Connect and print normalized live readings")
    parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    parser.add_argument("--duration", type=float, default=0.0, help="Stop after N seconds; 0 runs until interrupted")
    parser.add_argument("--count", type=int, default=0, help="Stop after N readings")
    parser.set_defaults(func=handle)


async def handle(args: argparse.Namespace) -> int:
    try:
        from fluke_ble.bleak_adapter import BleakAdapter
    except ModuleNotFoundError as exc:
        raise RuntimeError("BLE support requires the `bleak` package. Install `requirements.txt`.") from exc

    manager = DeviceManager(
        ble_adapter=BleakAdapter(),
        profile_registry=ProfileRegistry([Fluke376FCProfile()]),
        event_bus=EventBus(),
        reading_stream=ReadingStreamService(),
    )

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
