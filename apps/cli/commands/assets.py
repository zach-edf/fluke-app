from __future__ import annotations

import argparse
import json
from uuid import uuid4

from apps.cli.formatters import asset_to_dict, format_asset, output_list, positive_int
from apps.cli.runtime import default_database_path, open_store
from fluke_app import AssetTrendService, ExportService
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter
from fluke_core.models.asset import SUGGESTED_ASSET_TYPES, Asset


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("assets", help="Manage tracked equipment and trend its readings")
    parser.add_argument("--database", default=None, help="SQLite database path (default: platform data dir)")
    asset_subparsers = parser.add_subparsers(dest="assets_command", required=True)

    list_parser = asset_subparsers.add_parser("list", help="List tracked assets")
    list_parser.add_argument("--limit", type=positive_int, default=200, help="How many assets to show")
    list_parser.set_defaults(func=handle_list)

    create_parser = asset_subparsers.add_parser("create", help="Create a new asset")
    create_parser.add_argument("--name", required=True, help="Asset name")
    create_parser.add_argument(
        "--type",
        dest="asset_type",
        default="",
        help="Free-text asset type. Suggested: " + ", ".join(SUGGESTED_ASSET_TYPES),
    )
    create_parser.add_argument("--location", default="", help="Where the asset lives")
    create_parser.add_argument("--notes", default="", help="Free-form notes")
    create_parser.add_argument("--id", dest="asset_id", default=None, help="Optional explicit asset id")
    create_parser.set_defaults(func=handle_create)

    show_parser = asset_subparsers.add_parser("show", help="Show one asset and its linked sessions")
    show_parser.add_argument("--asset", required=True, help="Asset id to show")
    show_parser.set_defaults(func=handle_show)

    trend_parser = asset_subparsers.add_parser("trend", help="Print per-session trend statistics for an asset")
    trend_parser.add_argument("--asset", required=True, help="Asset id to trend")
    trend_parser.add_argument(
        "--measurement",
        default=None,
        help="Filter to one measurement type (e.g. current_inrush, voltage_dc)",
    )
    trend_parser.add_argument("--csv-output", default=None, help="Optional path to write the trend CSV export")
    trend_parser.set_defaults(func=handle_trend)


async def handle_list(args: argparse.Namespace) -> int:
    store = open_store(args.database or default_database_path())
    try:
        assets = store.assets.list_all(limit=args.limit)
    finally:
        store.close()

    if not assets:
        print("[]" if getattr(args, "json", False) else "No assets found.")
        return 0

    if getattr(args, "json", False):
        output_list(assets, True, format_asset, asset_to_dict)
    else:
        print("Assets:")
        output_list(assets, False, format_asset, asset_to_dict)
    return 0


async def handle_create(args: argparse.Namespace) -> int:
    asset = Asset(
        asset_id=args.asset_id or f"asset-{uuid4().hex[:12]}",
        name=args.name,
        asset_type=args.asset_type,
        location=args.location,
        notes=args.notes,
    )
    store = open_store(args.database or default_database_path())
    try:
        created = store.assets.create(asset)
    finally:
        store.close()

    if getattr(args, "json", False):
        print(json.dumps(asset_to_dict(created), indent=2))
    else:
        print(f"Created asset {created.asset_id}")
        print(format_asset(created))
    return 0


async def handle_show(args: argparse.Namespace) -> int:
    store = open_store(args.database or default_database_path())
    try:
        asset = store.assets.get(args.asset)
        sessions = store.sessions.list_for_asset(args.asset) if asset else []
    finally:
        store.close()

    if asset is None:
        print(f"Unknown asset: {args.asset}")
        return 1

    if getattr(args, "json", False):
        payload = asset_to_dict(asset)
        payload["sessions"] = [
            {
                "session_id": s.session_id,
                "title": s.title,
                "started_at": s.started_at.isoformat(),
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            }
            for s in sessions
        ]
        print(json.dumps(payload, indent=2))
        return 0

    print(format_asset(asset))
    if asset.notes:
        print(f"  notes={asset.notes}")
    if asset.created_at:
        print(f"  created_at={asset.created_at.isoformat()}")
    print(f"  sessions ({len(sessions)}):")
    for s in sessions:
        print(f"    - {s.session_id} | started={s.started_at.isoformat()} | title={s.title or '-'}")
    return 0


async def handle_trend(args: argparse.Namespace) -> int:
    store = open_store(args.database or default_database_path())
    try:
        asset = store.assets.get(args.asset)
        if asset is None:
            print(f"Unknown asset: {args.asset}")
            return 1
        service = AssetTrendService(store.sessions, store.readings)
        trend = service.build_trend(args.asset, measurement_type=args.measurement)
        csv_path = None
        if args.csv_output:
            export = ExportService(
                store.sessions,
                store.readings,
                store.markers,
                SessionCsvExporter(),
                SessionJsonExporter(device_repo=store.devices),
            )
            csv_path = export.export_asset_trend_csv(args.asset, args.csv_output)
    finally:
        store.close()

    if getattr(args, "json", False):
        payload = {
            "asset_id": trend.asset_id,
            "session_count": trend.session_count,
            "series": [
                {
                    "measurement": s.context_id,
                    "label": s.label,
                    "unit": s.unit,
                    "points": [
                        {
                            "session_id": p.session_id,
                            "session_title": p.session_title,
                            "started_at": p.started_at.isoformat(),
                            "reading_count": p.reading_count,
                            "numeric_count": p.numeric_count,
                            "min": p.min_value,
                            "max": p.max_value,
                            "avg": p.avg_value,
                            "median": p.median_value,
                        }
                        for p in s.points
                    ],
                }
                for s in trend.series
            ],
        }
        if csv_path:
            payload["csv_output"] = csv_path
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Trend for asset {trend.asset_id} ({trend.session_count} session(s)):")
    if not trend.series:
        print("  No numeric measurements found for this asset.")
    for s in trend.series:
        print(f"\n  {s.label} [{s.context_id}] ({s.unit or '-'})")
        print(f"    {'date':<12} {'min':>10} {'max':>10} {'avg':>10} {'median':>10}  session")
        for p in s.points:
            print(
                f"    {p.started_at.date().isoformat():<12} "
                f"{_fmt(p.min_value):>10} {_fmt(p.max_value):>10} "
                f"{_fmt(p.avg_value):>10} {_fmt(p.median_value):>10}  "
                f"{p.session_title or p.session_id}"
            )
    if csv_path:
        print(f"\nWrote trend CSV: {csv_path}")
    return 0


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.4g}"
