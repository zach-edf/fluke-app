from __future__ import annotations

import argparse
import json
from pathlib import Path

from apps.cli.formatters import output_list, format_session, positive_float, positive_int, session_to_dict
from apps.cli.runtime import default_database_path, open_store, require_bleak_adapter
from fluke_app import ExportService, LOGGING_VALUE_SOURCES, download_logging_data, import_logging_sessions
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("sessions", help="List, export, and import recorded sessions")
    parser.add_argument("--database", default=None, help="SQLite database path (default: platform data dir)")
    session_subparsers = parser.add_subparsers(dest="sessions_command", required=True)

    list_parser = session_subparsers.add_parser("list", help="List recent sessions")
    list_parser.add_argument("--limit", type=positive_int, default=20, help="How many sessions to show")
    list_parser.set_defaults(func=handle_list)

    export_parser = session_subparsers.add_parser("export", help="Export a recorded session")
    export_parser.add_argument("--session", required=True, help="Session id to export")
    export_parser.add_argument("--format", choices=["csv", "json"], default="csv")
    export_parser.add_argument("--output", required=True, help="Output path")
    export_parser.set_defaults(func=handle_export)

    import_parser = session_subparsers.add_parser(
        "import-device-memory",
        help="Download saved device-memory logs and import them as normal sessions",
    )
    import_parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    import_parser.add_argument(
        "--value-source",
        choices=list(LOGGING_VALUE_SOURCES),
        default="average",
        help="Which decoded value to store for each detail block",
    )
    import_parser.add_argument(
        "--data-output",
        default=None,
        help="Optional file path to write the raw downloaded logging bytes",
    )
    import_parser.add_argument(
        "--download-report-output",
        default=None,
        help="Optional file path to write the low-level download report JSON",
    )
    import_parser.add_argument(
        "--max-blocks-per-request",
        type=positive_int,
        default=500,
        help="Maximum number of 18-byte blocks to request per control-point command",
    )
    import_parser.add_argument(
        "--command-timeout-seconds",
        type=positive_float,
        default=5.0,
        help="Maximum time to wait for each lock/download step",
    )
    import_parser.set_defaults(func=handle_import_device_memory)


async def handle_list(args: argparse.Namespace) -> int:
    store = open_store(args.database or default_database_path())
    try:
        sessions = store.sessions.list_recent(limit=args.limit)
    finally:
        store.close()

    if not sessions:
        if not getattr(args, "json", False):
            print("No sessions found.")
        else:
            print("[]")
        return 0

    if getattr(args, "json", False):
        output_list(sessions, True, format_session, session_to_dict)
    else:
        print("Recent sessions:")
        output_list(sessions, False, format_session, session_to_dict)
    return 0


async def handle_export(args: argparse.Namespace) -> int:
    store = open_store(args.database or default_database_path())
    try:
        service = ExportService(
            store.sessions,
            store.readings,
            store.markers,
            SessionCsvExporter(),
            SessionJsonExporter(device_repo=store.devices),
        )
        if args.format == "csv":
            output = service.export_csv(args.session, args.output)
        else:
            output = service.export_json(args.session, args.output)
    finally:
        store.close()

    print(output)
    return 0


async def handle_import_device_memory(args: argparse.Namespace) -> int:
    adapter = require_bleak_adapter()()
    await adapter.connect(args.device)
    try:
        download_report = await download_logging_data(
            adapter=adapter,
            device_id=args.device,
            data_output=Path(args.data_output) if args.data_output else None,
            max_blocks_per_request=args.max_blocks_per_request,
            command_timeout_seconds=args.command_timeout_seconds,
        )
    finally:
        await adapter.disconnect(args.device)

    if args.download_report_output:
        output_path = Path(args.download_report_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(download_report, indent=2), encoding="utf-8")

    if "decode_error" in download_report:
        raise RuntimeError(f"Could not decode downloaded device-memory payload: {download_report['decode_error']}")

    store = open_store(args.database or default_database_path())
    try:
        import_report = import_logging_sessions(
            device_repo=store.devices,
            session_repo=store.sessions,
            reading_repo=store.readings,
            device_id=args.device,
            decoded_sessions=download_report.get("decoded_sessions", []),
            value_source=args.value_source,
        )
    finally:
        store.close()

    report = {
        "device_id": args.device,
        "value_source": args.value_source,
        "downloaded_bytes": download_report.get("downloaded_bytes", 0),
        "downloaded_blocks": download_report.get("downloaded_blocks", 0),
        "decoded_session_count": import_report["decoded_session_count"],
        "imported_count": import_report["imported_count"],
        "skipped_count": import_report["skipped_count"],
        "imported_sessions": import_report["imported_sessions"],
        "skipped_sessions": import_report["skipped_sessions"],
        "status_before": download_report.get("status_before"),
        "status_after": download_report.get("status_after"),
    }
    if args.data_output:
        report["data_output"] = args.data_output
    if args.download_report_output:
        report["download_report_output"] = args.download_report_output

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        _print_import_report(report)
    return 0


def _print_import_report(report: dict[str, object]) -> None:
    print(f"Device: {report['device_id']}")
    print(f"Downloaded bytes: {report['downloaded_bytes']}")
    print(f"Downloaded blocks: {report['downloaded_blocks']}")
    print(f"Decoded sessions: {report['decoded_session_count']}")
    print(f"Imported sessions: {report['imported_count']}")
    print(f"Skipped sessions: {report['skipped_count']}")
    print(f"Value source: {report['value_source']}")
    status_before = report.get("status_before") or {}
    status_after = report.get("status_after") or {}
    if status_before:
        print(
            "Status before: "
            f"{status_before.get('state_label', 'unknown')} "
            f"(bytes_logged={status_before.get('bytes_logged', 0)}, "
            f"blocks_logged={status_before.get('blocks_logged', 0)})"
        )
    if status_after:
        print(
            "Status after: "
            f"{status_after.get('state_label', 'unknown')} "
            f"(bytes_logged={status_after.get('bytes_logged', 0)}, "
            f"blocks_logged={status_after.get('blocks_logged', 0)})"
        )
    if report.get("data_output"):
        print(f"Saved raw data: {report['data_output']}")
    if report.get("download_report_output"):
        print(f"Saved download report: {report['download_report_output']}")
    imported_sessions = report.get("imported_sessions") or []
    if imported_sessions:
        print()
        print("Imported:")
        for entry in imported_sessions:
            print(
                f"- {entry['session_id']} | started={entry['started_at']} | "
                f"readings={entry['reading_count']} | title={entry['title']}"
            )
    skipped_sessions = report.get("skipped_sessions") or []
    if skipped_sessions:
        print()
        print("Skipped:")
        for entry in skipped_sessions:
            print(f"- {entry['session_id']} | reason={entry['reason']}")
