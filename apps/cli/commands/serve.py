from __future__ import annotations

import argparse
import asyncio
import sys

from apps.cli.formatters import nonneg_float, parse_tags
from apps.cli.runtime import (
    attach_connection_diagnostics,
    build_device_manager,
    default_database_path,
    open_store,
)
from fluke_app import ExportService, SessionRecorder, new_session
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter
from fluke_core.models.reading import Reading


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "serve",
        help="Serve a LAN-only live web view of the meter reading (read-only)",
    )
    parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    parser.add_argument("--port", type=int, default=8765, help="TCP port to bind (default 8765)")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Interface to bind. Default 0.0.0.0 exposes on all LAN interfaces (trusted LAN only).",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional shared secret; clients must pass ?token=... to reach the page, WS, and API.",
    )
    parser.add_argument(
        "--stale-after",
        type=nonneg_float,
        default=3.0,
        help="Seconds without a fresh reading before the view flags data as stale (default 3.0)",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        default=True,
        help="Read-only serving (default). The web view never controls the meter.",
    )
    parser.add_argument("--duration", type=nonneg_float, default=0.0, help="Stop after N seconds; 0 runs until interrupted")
    parser.add_argument("--no-qr", action="store_true", help="Do not render the terminal QR code")

    # --log mirrors `fluke log`: record readings to SQLite alongside serving.
    parser.add_argument("--log", action="store_true", help="Also record readings to SQLite (like `fluke log`)")
    parser.add_argument("--database", default=None, help="SQLite database path (default: platform data dir)")
    parser.add_argument("--title", default=None, help="Session title when --log is set")
    parser.add_argument("--notes", default=None, help="Session notes when --log is set")
    parser.add_argument("--tags", default="", help="Comma-separated session tags when --log is set")
    parser.add_argument("--csv-output", default=None, help="Export session CSV after --log serving ends")
    parser.add_argument("--json-output", default=None, help="Export session JSON after --log serving ends")
    parser.set_defaults(func=handle)


def _print_access(urls: list[str], token: str | None, render_qr: bool) -> None:
    from fluke_web import render_qr_ascii

    print("Live web view is running. Open on a phone on the same network:")
    for url in urls:
        print(f"  {url}")
    if not urls:
        print("  (no LAN IP detected; try http://127.0.0.1:<port>/)")

    if render_qr and urls:
        qr = render_qr_ascii(urls[0])
        if qr is not None:
            print()
            print(qr)
        else:
            print("(install the `qrcode` package or `.[web]` extra for a scannable QR code)")

    print()
    print("Security: this is a trusted-LAN tool. It binds to all interfaces by")
    print("default and has no authentication in v1. Use --token for a basic gate")
    print("and only run it on networks you trust. The view is strictly read-only.")
    if token:
        print("A token is required; it is already included in the URLs above.")
    print("Press Ctrl+C to stop.")


async def handle(args: argparse.Namespace) -> int:
    from fluke_web import LiveState, WebLiveServer, build_urls, enumerate_lan_ips

    manager = build_device_manager()
    attach_connection_diagnostics(manager)

    state = LiveState(stale_after_s=args.stale_after)
    server = WebLiveServer(state, token=args.token)

    # Optional SQLite logging session, reusing the `fluke log` plumbing.
    store = None
    recorder: SessionRecorder | None = None
    db_path = args.database or default_database_path()
    if args.log:
        store = open_store(db_path)
        recorder = SessionRecorder(store.sessions, store.readings, store.markers)

    finished = asyncio.Event()

    def on_reading(reading: Reading) -> None:
        if recorder is not None:
            recorder.on_reading(reading)
        server.on_reading(reading)

    def on_disconnect() -> None:
        status = manager.latest_connection_diagnostics()
        detail = "" if status is None else (status.last_error_text or status.message)
        server.set_connection_status("disconnected", detail)

    def on_diagnostics(status) -> None:
        phase = status.phase
        if phase in ("connected", "recovered"):
            server.set_connection_status("connected")
        elif phase in ("connect_failed", "recovery_failed"):
            server.set_connection_status("error", status.last_error_text or status.message)
        elif status.is_recovery:
            server.set_connection_status("reconnecting", status.message)
        else:
            server.set_connection_status("connecting", status.message)

    manager.subscribe_readings(on_reading)
    manager.subscribe_disconnects(on_disconnect)
    manager.subscribe_connection_diagnostics(on_diagnostics)

    await server.start(host=args.host, port=args.port)

    urls = build_urls(enumerate_lan_ips(), args.port, args.token)
    _print_access(urls, args.token, render_qr=not args.no_qr)

    print(f"Connecting to {args.device}...", file=sys.stderr)
    session = None
    try:
        device = await manager.establish_session(args.device, profile_id=args.profile)
        server.set_connection_status("connected")

        if recorder is not None and store is not None:
            store.upsert_device(device)
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
            print(f"Logging session {session.session_id} to {db_path}.")

        try:
            if args.duration > 0:
                await asyncio.wait_for(finished.wait(), timeout=args.duration)
            else:
                await finished.wait()
        except asyncio.TimeoutError:
            pass
    finally:
        completed = recorder.stop() if recorder is not None else None
        await manager.disconnect()
        await server.stop()
        if store is not None:
            store.close()

    if recorder is not None and completed is not None:
        _export_session(db_path, completed.session_id, args)

    return 0


def _export_session(db_path: str, session_id: str, args: argparse.Namespace) -> None:
    if not (args.csv_output or args.json_output):
        print(f"Saved logging session {session_id} to {db_path}.")
        return
    store = open_store(db_path)
    try:
        export_service = ExportService(
            store.sessions,
            store.readings,
            store.markers,
            SessionCsvExporter(),
            SessionJsonExporter(device_repo=store.devices),
        )
        print(f"Saved logging session {session_id} to {db_path}.")
        if args.csv_output:
            print(f"CSV export: {export_service.export_csv(session_id, args.csv_output)}")
        if args.json_output:
            print(f"JSON export: {export_service.export_json(session_id, args.json_output)}")
    finally:
        store.close()
