from __future__ import annotations

import argparse
import asyncio
import sys

from apps.cli.formatters import format_reading, nonneg_float, nonneg_int, parse_tags
from apps.cli.runtime import (
    add_mqtt_arguments,
    attach_connection_diagnostics,
    build_device_manager,
    build_mqtt_publisher,
    default_database_path,
    open_store,
)
from fluke_app import ExportService, SessionRecorder, new_session
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter
from fluke_core.models.reading import Reading


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("log", help="Connect, record readings to SQLite, and optionally export")
    parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    parser.add_argument("--database", default=None, help="SQLite database path (default: platform data dir)")
    parser.add_argument("--duration", type=nonneg_float, default=0.0, help="Stop after N seconds; 0 runs until interrupted")
    parser.add_argument("--count", type=nonneg_int, default=0, help="Stop after N readings")
    parser.add_argument("--title", default=None, help="Optional session title")
    parser.add_argument("--notes", default=None, help="Optional session notes")
    parser.add_argument("--tags", default="", help="Comma-separated session tags")
    parser.add_argument("--csv-output", default=None, help="Optional export path for session CSV")
    parser.add_argument("--json-output", default=None, help="Optional export path for session JSON")
    parser.add_argument("--quiet", action="store_true", help="Do not print each reading while logging")
    add_mqtt_arguments(parser)
    parser.set_defaults(func=handle)


async def handle(args: argparse.Namespace) -> int:
    db_path = args.database or default_database_path()
    manager = build_device_manager()
    attach_connection_diagnostics(manager)
    store = open_store(db_path)
    recorder = SessionRecorder(store.sessions, store.readings, store.markers)
    publisher = build_mqtt_publisher(args)

    recorded = 0
    finished = asyncio.Event()
    terminal_error: str | None = None

    def on_reading(reading: Reading) -> None:
        nonlocal recorded
        recorder.on_reading(reading)
        recorded += 1
        if publisher is not None:
            publisher.publish_reading(reading)
        if not args.quiet:
            print(format_reading(reading))
        if args.count and recorded >= args.count:
            finished.set()

    manager.subscribe_readings(on_reading)
    manager.subscribe_disconnects(lambda: _mark_logging_disconnect(manager, finished, _set_terminal_error))

    def _set_terminal_error(message: str) -> None:
        nonlocal terminal_error
        terminal_error = message

    try:
        print(f"Connecting to {args.device}...", file=sys.stderr)
        device = await manager.establish_session(args.device, profile_id=args.profile)
        store.upsert_device(device)

        if publisher is not None:
            try:
                publisher.connect(device.device_id, device=device)
                print(f"Publishing readings to MQTT broker {args.mqtt_host}.", file=sys.stderr)
            except Exception as exc:
                print(f"Warning: MQTT publishing disabled ({exc}).", file=sys.stderr)
                publisher = None

        session = recorder.start(
            new_session(
                device_id=device.device_id,
                title=args.title,
                notes=args.notes,
                tags=parse_tags(args.tags),
                app_version="0.1.0",
                profile_id=device.profile_id or args.profile,
            )
        )

        print(f"Starting logging session {session.session_id} from {device.device_id}. Press Ctrl+C to stop.")

        try:
            if args.duration > 0 and args.count > 0:
                await asyncio.wait_for(finished.wait(), timeout=args.duration)
            elif args.duration > 0:
                await asyncio.wait_for(finished.wait(), timeout=args.duration)
            elif args.count > 0:
                await finished.wait()
            else:
                await finished.wait()
        except asyncio.TimeoutError:
            pass
    finally:
        completed = recorder.stop()
        await manager.disconnect()
        if publisher is not None:
            try:
                publisher.disconnect()
            except Exception:
                pass
        store.close()

    if completed is None:
        raise RuntimeError("Session did not start.")
    if terminal_error:
        raise RuntimeError(f"Logging stopped because recovery failed: {terminal_error}")

    print(f"Saved session {completed.session_id} with {recorded} readings to {db_path}.")

    if args.csv_output or args.json_output:
        store = open_store(db_path)
        try:
            export_service = ExportService(
                store.sessions,
                store.readings,
                store.markers,
                SessionCsvExporter(),
                SessionJsonExporter(device_repo=store.devices),
            )
            if args.csv_output:
                print(f"CSV export: {export_service.export_csv(completed.session_id, args.csv_output)}")
            if args.json_output:
                print(f"JSON export: {export_service.export_json(completed.session_id, args.json_output)}")
        finally:
            store.close()

    return 0


def _mark_logging_disconnect(manager, finished: asyncio.Event, set_message) -> None:
    status = manager.latest_connection_diagnostics()
    set_message("" if status is None else (status.last_error_text or status.message))
    finished.set()
