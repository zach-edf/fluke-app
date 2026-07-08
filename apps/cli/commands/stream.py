from __future__ import annotations

import argparse
import asyncio
import sys

from apps.cli.formatters import format_reading, nonneg_float, nonneg_int
from apps.cli.runtime import (
    add_mqtt_arguments,
    add_reconnect_flag,
    add_speech_arguments,
    attach_connection_diagnostics,
    build_device_manager,
    build_mqtt_publisher,
    build_speech_service,
)
from fluke_core.models.reading import Reading


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("stream", help="Connect and print normalized live readings")
    parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    parser.add_argument("--duration", type=nonneg_float, default=0.0, help="Stop after N seconds; 0 runs until interrupted")
    parser.add_argument("--count", type=nonneg_int, default=0, help="Stop after N readings")
    parser.add_argument("--dashboard", action="store_true", help="Show retro sci-fi live dashboard instead of plain output")
    add_reconnect_flag(parser)
    add_speech_arguments(parser)
    add_mqtt_arguments(parser)
    parser.set_defaults(func=handle)


async def handle(args: argparse.Namespace) -> int:
    manager = build_device_manager(auto_reconnect=not getattr(args, "no_reconnect", False))
    attach_connection_diagnostics(manager)

    if getattr(args, "dashboard", False):
        from apps.cli.dashboard import run_dashboard
        return await run_dashboard(manager, args)

    speech = build_speech_service(args)
    publisher = build_mqtt_publisher(args)

    received = 0
    finished = asyncio.Event()
    terminal_error: str | None = None

    def on_reading(reading: Reading) -> None:
        nonlocal received
        received += 1
        print(format_reading(reading))
        if speech is not None:
            speech.on_reading(reading)
        if publisher is not None:
            publisher.publish_reading(reading)
        if args.count and received >= args.count:
            finished.set()

    def on_disconnect() -> None:
        nonlocal terminal_error
        status = manager.latest_connection_diagnostics()
        terminal_error = None if status is None else (status.last_error_text or status.message)
        finished.set()

    manager.subscribe_readings(on_reading)
    manager.subscribe_disconnects(on_disconnect)

    print(f"Connecting to {args.device}...", file=sys.stderr)
    device = await manager.establish_session(args.device, profile_id=args.profile)
    if publisher is not None:
        try:
            publisher.connect(device.device_id, device=device)
            print(f"Publishing readings to MQTT broker {args.mqtt_host}.", file=sys.stderr)
        except Exception as exc:  # keep streaming even if the broker is unreachable
            print(f"Warning: MQTT publishing disabled ({exc}).", file=sys.stderr)
            publisher = None
    print(f"Starting stream from {args.device}. Press Ctrl+C to stop.")

    try:
        if args.duration > 0:
            await asyncio.wait_for(finished.wait(), timeout=args.duration)
        else:
            await finished.wait()
    except asyncio.TimeoutError:
        pass
    finally:
        await manager.disconnect()
        if publisher is not None:
            try:
                publisher.disconnect()
            except Exception:
                pass

    if terminal_error:
        print(f"Stream ended because recovery failed: {terminal_error}", file=sys.stderr)
        return 1
    return 0
