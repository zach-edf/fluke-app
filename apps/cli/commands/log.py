from __future__ import annotations

import argparse
import asyncio

from apps.cli.runtime import build_device_manager, open_store
from fluke_app import ExportService, SessionRecorder, new_session
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter
from fluke_core.models.reading import Reading


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("log", help="Connect, record readings to SQLite, and optionally export")
    parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    parser.add_argument("--database", default="data/fluke.db", help="SQLite database path")
    parser.add_argument("--duration", type=float, default=0.0, help="Stop after N seconds; 0 runs until interrupted")
    parser.add_argument("--count", type=int, default=0, help="Stop after N readings")
    parser.add_argument("--title", default=None, help="Optional session title")
    parser.add_argument("--notes", default=None, help="Optional session notes")
    parser.add_argument("--tags", default="", help="Comma-separated session tags")
    parser.add_argument("--csv-output", default=None, help="Optional export path for session CSV")
    parser.add_argument("--json-output", default=None, help="Optional export path for session JSON")
    parser.add_argument("--quiet", action="store_true", help="Do not print each reading while logging")
    parser.set_defaults(func=handle)


async def handle(args: argparse.Namespace) -> int:
    manager = build_device_manager()
    store = open_store(args.database)
    recorder = SessionRecorder(store.sessions, store.readings, store.markers)
    export_service = ExportService(
        store.sessions,
        store.readings,
        store.markers,
        SessionCsvExporter(),
        SessionJsonExporter(device_repo=store.devices),
    )

    recorded = 0
    finished = asyncio.Event()

    def on_reading(reading: Reading) -> None:
        nonlocal recorded
        recorder.on_reading(reading)
        recorded += 1
        if not args.quiet:
            print(_format_reading(reading))
        if args.count and recorded >= args.count:
            finished.set()

    manager.subscribe_readings(on_reading)

    try:
        device = await manager.connect(args.device, profile_id=args.profile)
        store.upsert_device(device)

        session = recorder.start(
            new_session(
                device_id=device.device_id,
                title=args.title,
                notes=args.notes,
                tags=_parse_tags(args.tags),
                app_version="0.1.0",
                profile_id=device.profile_id or args.profile,
            )
        )

        await manager.start_stream()
        print(f"Logging session {session.session_id} from {device.device_id}. Press Ctrl+C to stop.")

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
        completed = recorder.stop()
        await manager.disconnect()
        store.close()

    if completed is None:
        raise RuntimeError("Session did not start.")

    print(f"Saved session {completed.session_id} with {recorded} readings to {args.database}.")

    if args.csv_output or args.json_output:
        store = open_store(args.database)
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


def _parse_tags(raw: str) -> list[str]:
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def _format_reading(reading: Reading) -> str:
    value = "-" if reading.value is None else f"{reading.value:.6g}"
    mode = reading.mode or "-"
    return (
        f"{reading.timestamp_utc.isoformat()} | "
        f"{reading.display_text or '-'} | "
        f"value={value} {reading.unit or ''}".rstrip()
        + f" | type={reading.measurement_type.value} | mode={mode} | status={reading.status.value}"
    )
