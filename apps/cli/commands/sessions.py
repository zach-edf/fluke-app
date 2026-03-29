from __future__ import annotations

import argparse

from apps.cli.formatters import output_list, format_session, session_to_dict, positive_int
from apps.cli.runtime import default_database_path, open_store
from fluke_app import ExportService
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("sessions", help="List and export recorded sessions")
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
